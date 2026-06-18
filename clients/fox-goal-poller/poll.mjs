// poll.mjs — headless background poller.
//
// Loops forever: opens each configured Fox handle's profile in a HEADLESS browser
// (using the saved login from login.mjs), finds new video posts, runs the same Gemini
// goal check + syndication download + upload as the extension (clip-core.js). No visible
// window, so the OS screen lock has no effect — it runs as long as the PC is awake.

import { readFileSync, existsSync, writeFileSync } from "node:fs";
import { classifyGoal, downloadBestClip } from "./clip-core.js";
import { launchContext } from "./browser.mjs";

if (!existsSync("config.json")) {
  console.error("Missing config.json — copy config.example.json to config.json and fill it in.");
  process.exit(1);
}
if (!existsSync("profile") && !existsSync("auth.json")) {
  console.error("No X session — log in with:  node login.mjs   (or import cookies:  node import-cookies.mjs)");
  process.exit(1);
}

const cfg = JSON.parse(readFileSync("config.json", "utf8"));
const handles = (cfg.handles && cfg.handles.length ? cfg.handles : ["FOXSports"]).map((h) =>
  String(h).replace(/^@/, "")
);
const pollMs = (Number(cfg.pollSeconds) || 45) * 1000;
const maxAgeMs = (Number(cfg.maxAgeMinutes) || 20) * 60000;
const threshold = Number(cfg.threshold ?? 0.6);
const base = String(cfg.serverUrl || "").replace(/\/+$/, "");

// ── durable dedup ────────────────────────────────────────────────────────────
const SEEN_FILE = "seen.json";
let seen = existsSync(SEEN_FILE) ? new Set(JSON.parse(readFileSync(SEEN_FILE, "utf8"))) : new Set();
function markSeen(id) {
  seen.add(id);
  if (seen.size > 3000) seen = new Set([...seen].slice(-2000));
  try { writeFileSync(SEEN_FILE, JSON.stringify([...seen])); } catch (_) {}
}

// ── activity log (console + mirror to the server, like the extension) ────────
function log(stage, ok, id, detail) {
  console.log(`[fgp] ${new Date().toISOString().slice(11, 19)} ${stage} ${ok ? "OK" : "—"} ${id ? "#" + String(id).slice(-6) : ""} ${detail || ""}`);
  if (!base || !cfg.uploadKey) return;
  fetch(`${base}/api/v1/goal-clips/debug-log`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Upload-Key": cfg.uploadKey },
    body: JSON.stringify({ ts: Date.now(), stage, ok, tweetId: id || "", detail: detail || "", src: "poller" }),
  }).catch(() => {});
}

// ── upload (same shape as the extension) ─────────────────────────────────────
async function uploadClip(tweetId, handle, text, verdict, blob) {
  const fd = new FormData();
  fd.append("video", blob, `${tweetId}.mp4`);
  fd.append("tweet_id", tweetId);
  fd.append("tweet_url", `https://x.com/${handle}/status/${tweetId}`);
  fd.append("text", text || "");
  fd.append("home_team", verdict.home_team || "");
  fd.append("away_team", verdict.away_team || "");
  fd.append("home_score", verdict.home_score != null ? String(verdict.home_score) : "");
  fd.append("away_score", verdict.away_score != null ? String(verdict.away_score) : "");
  fd.append("scorer", verdict.scorer || "");
  fd.append("scoring_team", verdict.scoring_team || "");
  fd.append("minute", verdict.minute || "");
  fd.append("confidence", verdict.confidence != null ? String(verdict.confidence) : "");
  const resp = await fetch(`${base}/api/v1/goal-clips/ingest`, {
    method: "POST",
    headers: { "X-Upload-Key": cfg.uploadKey },
    body: fd,
  });
  if (!resp.ok) throw new Error(`ingest ${resp.status}: ${await resp.text()}`);
  return await resp.json();
}

// ── read the visible posts on a profile (same selectors as content.js) ───────
async function scrape(page, handle) {
  await page.goto(`https://x.com/${handle}`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(3500); // let the timeline render
  return await page.$$eval("article", (arts) =>
    arts
      .map((art) => {
        const links = [...art.querySelectorAll('a[href*="/status/"]')];
        const link = links.find((a) => a.querySelector("time")) || links[0];
        const m = link && link.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
        if (!m) return null;
        const video = !!art.querySelector('[data-testid="videoComponent"], [data-testid="videoPlayer"], video');
        const textEl = art.querySelector('[data-testid="tweetText"]');
        const timeEl = art.querySelector("time[datetime]");
        return {
          handle: m[1],
          id: m[2],
          video,
          text: textEl ? textEl.innerText : "",
          time: timeEl ? timeEl.getAttribute("datetime") : null,
        };
      })
      .filter(Boolean)
  );
}

async function handlePost(p, handle) {
  if (seen.has(p.id)) return;
  if (handle.toLowerCase() !== p.handle.toLowerCase()) return;
  if (!p.video) return;
  const text1 = (p.text || "").replace(/\s+/g, " ").trim();
  if (p.time && Date.now() - Date.parse(p.time) > maxAgeMs) {
    const age = Math.round((Date.now() - Date.parse(p.time)) / 60000);
    console.log(`[fgp]   ⏭  old video (${age}min) skipped: "${text1.slice(0, 70)}"`);
    markSeen(p.id);
    return;
  }

  // 1) found a fresh video post from the handle
  log("video", true, p.id, `found video — "${text1.slice(0, 120)}"`);

  // 2) classify the text
  let v;
  try {
    v = await classifyGoal(p.text, cfg.llmApiKey, cfg.llmModel);
  } catch (e) {
    log("classify", false, p.id, "LLM error: " + e.message + " (will retry)");
    return;
  }
  const conf = Number(v?.confidence ?? 0);
  if (!v || !v.is_goal || conf < threshold) {
    log("classify", false, p.id, `NOT a goal (is_goal=${v?.is_goal}, conf=${conf.toFixed(2)})`);
    markSeen(p.id);
    return;
  }
  log("GOAL", true, p.id,
    `GOAL ✓ ${v.home_team || "?"}${v.away_team ? " vs " + v.away_team : ""}` +
    `${v.scorer ? " — " + v.scorer : ""} (conf ${conf.toFixed(2)})`);

  // 3) download the mp4
  let clip;
  try {
    clip = await downloadBestClip(p.id);
  } catch (e) {
    log("download", false, p.id, "error: " + e.message);
    markSeen(p.id);
    return;
  }
  if (!clip || !clip.blob) {
    log("download", false, p.id, "no mp4 variant (HLS-only?) — skipped");
    markSeen(p.id);
    return;
  }
  log("download", true, p.id, `got clip ${(clip.bytes / 1048576).toFixed(2)} MB`);

  // 4) upload to the server
  try {
    const r = await uploadClip(p.id, handle, p.text, v, clip.blob);
    log("upload", true, p.id, r?.duplicate ? "server already had it" : `uploaded → clip id ${r?.id}`);
    markSeen(p.id);
  } catch (e) {
    log("upload", false, p.id, e.message + " (will retry)");
  }
}

(async () => {
  const ctx = await launchContext(true); // headless
  const page = ctx.pages()[0] || (await ctx.newPage());
  console.log(`[fgp] watching ${handles.map((h) => "@" + h).join(", ")} every ${pollMs / 1000}s → ${base}`);
  log("watching", true, "", `@${handles.join(", @")}`);

  let lastMirror = 0;
  for (;;) {
    for (const handle of handles) {
      try {
        const posts = await scrape(page, handle);
        const vids = posts.filter((p) => p.video).length;
        // Per-scan heartbeat so it's obvious it's alive and reading the timeline.
        const t = new Date().toISOString().slice(11, 19);
        console.log(`[fgp] ${t} scan @${handle}: ${posts.length} posts, ${vids} with video`);
        if (posts.length === 0) {
          console.log(`[fgp]   ↳ 0 posts — X may be showing a login wall to the headless browser (re-check your session)`);
        }
        // Mirror a heartbeat to the server at most every 5 min (don't flood the log).
        if (Date.now() - lastMirror > 300000) {
          log("scan", posts.length > 0, "", `@${handle}: ${posts.length} posts, ${vids} video`);
          lastMirror = Date.now();
        }
        for (const p of posts) await handlePost(p, handle);
      } catch (e) {
        log("scan", false, "", `scrape @${handle} failed: ${e.message}`);
      }
    }
    await new Promise((r) => setTimeout(r, pollMs));
  }
})();
