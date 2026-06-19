// poll.mjs — headless background poller.
//
// Loops forever: opens each configured Fox handle's profile in a HEADLESS browser
// (using the saved login from login.mjs), finds new video posts during a game window, and
// uploads each video + its text to the server (clip-core.js for syndication download). No
// goal classification on the client — the server translates the text and posts the clip.
// No visible window, so the OS screen lock has no effect — it runs as long as the PC is awake.

import { readFileSync, existsSync, writeFileSync } from "node:fs";
import { downloadBestClip } from "./clip-core.js";
import { launchContext } from "./browser.mjs";

// Print the version first thing, so you can confirm you're running the latest build.
const VERSION = (() => {
  try {
    return JSON.parse(readFileSync(new URL("./package.json", import.meta.url))).version;
  } catch (_) {
    return "?";
  }
})();
console.log(`\n  fox-goal-poller v${VERSION}\n`);

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
const idleMs = (Number(cfg.idleSeconds) || 300) * 1000; // how often to re-check when no game is on
const maxAgeMs = (Number(cfg.maxAgeMinutes) || 20) * 60000;
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

// ── upload: just the video + its text (no classification metadata) ───────────
async function uploadClip(tweetId, handle, text, blob) {
  const fd = new FormData();
  fd.append("video", blob, `${tweetId}.mp4`);
  fd.append("tweet_id", tweetId);
  fd.append("tweet_url", `https://x.com/${handle}/status/${tweetId}`);
  fd.append("text", text || "");
  const resp = await fetch(`${base}/api/v1/goal-clips/ingest`, {
    method: "POST",
    headers: { "X-Upload-Key": cfg.uploadKey },
    body: fd,
  });
  if (!resp.ok) throw new Error(`ingest ${resp.status}: ${await resp.text()}`);
  return await resp.json();
}

// Is a match in its play window right now? (server decides — same window the bot uses)
// Returns { active, matches }. Fails OPEN so a server hiccup never stops capture.
async function activeWindow() {
  try {
    const r = await fetch(`${base}/api/v1/goal-clips/active`);
    if (!r.ok) return { active: true, matches: 0 };
    const d = await r.json();
    return { active: !!d.active, matches: Number(d.matches || 0) };
  } catch (_) {
    return { active: true, matches: 0 };
  }
}

// ── read the visible posts on a profile (same selectors as content.js) ───────
// X's timeline is VIRTUALIZED: it mounts only the posts near the viewport and unmounts the
// rest. So a single scrape catches whatever ~handful is on screen at that instant — clips
// scroll in and out of the DOM before we read them. We must scroll down step by step and
// ACCUMULATE the posts seen at each step (deduped by id), never scrape just once.
async function scrape(page, handle) {
  await page.goto(`https://x.com/${handle}`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(3500); // let the timeline render

  const EXTRACT = (arts) =>
    arts
      .map((art) => {
        const links = [...art.querySelectorAll('a[href*="/status/"]')];
        const link = links.find((a) => a.querySelector("time")) || links[0];
        const m = link && link.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
        if (!m) return null;
        const textEl = art.querySelector('[data-testid="tweetText"]');
        const timeEl = art.querySelector("time[datetime]");
        return {
          handle: m[1],
          id: m[2],
          text: textEl ? textEl.innerText : "",
          time: timeEl ? timeEl.getAttribute("datetime") : null,
        };
      })
      .filter(Boolean);

  const byId = new Map();
  let lastY = -1;
  for (let i = 0; i < 12; i++) {
    const batch = await page.$$eval("article", EXTRACT);
    for (const p of batch) if (!byId.has(p.id)) byId.set(p.id, p);
    await page.evaluate(() => window.scrollBy(0, Math.round(window.innerHeight * 1.5)));
    await page.waitForTimeout(800);
    const y = await page.evaluate(() => window.scrollY);
    if (y === lastY) break; // reached the bottom — nothing more to load
    lastY = y;
  }
  return [...byId.values()];
}

async function handlePost(p, handle) {
  if (seen.has(p.id)) return;
  if (handle.toLowerCase() !== p.handle.toLowerCase()) return;
  // Every per-post log line carries the channel (@handle) it was found on.
  const plog = (stage, ok, detail) => log(stage, ok, p.id, `@${handle} ${detail}`);
  let text1 = (p.text || "").replace(/\s+/g, " ").trim();
  if (p.time && Date.now() - Date.parse(p.time) > maxAgeMs) {
    const age = Math.round((Date.now() - Date.parse(p.time)) / 60000);
    console.log(`[fgp]   ⏭  @${handle} old post (${age}min) skipped: "${text1.slice(0, 70)}"`);
    markSeen(p.id);
    return;
  }

  // Decide "is this a video?" from the SYNDICATION API, not the page DOM. X lazy-loads
  // video players, so the DOM's video flag silently misses clips that aren't scrolled into
  // view — that dropped real goal clips. downloadBestClip resolves the tweet's mp4 (and its
  // canonical text) regardless of what rendered. No mp4 variant → it's not a video → skip.
  let clip;
  try {
    clip = await downloadBestClip(p.id);
  } catch (e) {
    plog("download", false, "error: " + e.message + " (will retry)");
    return; // leave UN-seen so a later scan retries
  }
  if (!clip || !clip.blob) {
    markSeen(p.id); // not a video post (text/image, or HLS-only) — done with it, quietly
    return;
  }
  // Prefer the page text; fall back to the syndication text (downloadBestClip returns it).
  if (text1.length < 5 && clip.text) text1 = String(clip.text).replace(/\s+/g, " ").trim();

  plog("video", true, `found video — "${text1.slice(0, 500)}"`);
  plog("download", true, `got clip ${(clip.bytes / 1048576).toFixed(2)} MB`);

  // Upload to the server (video + text only — the server vets/translates/posts).
  try {
    const r = await uploadClip(p.id, handle, text1, clip.blob);
    plog("upload", true, r?.duplicate ? "server already had it" : `uploaded → clip id ${r?.id}`);
    markSeen(p.id);
  } catch (e) {
    plog("upload", false, e.message + " (will retry)");
  }
}

(async () => {
  const ctx = await launchContext(true); // headless
  const page = ctx.pages()[0] || (await ctx.newPage());
  console.log(`[fgp] watching ${handles.map((h) => "@" + h).join(", ")} every ${pollMs / 1000}s → ${base}`);
  log("watching", true, "", `@${handles.join(", @")}`);

  let lastMirror = 0;
  let active = null; // unknown until the first check → the first state is always announced
  for (;;) {
    // Only work during a match window (+ buffer). Off-hours clips are ignored.
    const w = await activeWindow();
    if (w.active !== active) {
      active = w.active;
      if (active) {
        // STREAM START — a game window opened; begin capturing.
        log("stream-start", true, "",
          `▶ STREAM START — ${w.matches || "a"} match(es) live; capturing ${handles.map((h) => "@" + h).join(", ")}`);
      } else {
        // STREAM END — the game window closed; stop capturing until the next match.
        log("stream-end", false, "", "■ STREAM END — no match in play window; pausing scans");
      }
    }
    if (!active) {
      await new Promise((r) => setTimeout(r, idleMs));
      continue;
    }
    for (const handle of handles) {
      try {
        const posts = await scrape(page, handle);
        const fresh = posts.filter((p) => !seen.has(p.id)).length;
        // Per-scan heartbeat so it's obvious it's alive and reading the timeline. "new" =
        // not yet processed (video detection now happens per-post via the syndication API).
        const t = new Date().toISOString().slice(11, 19);
        console.log(`[fgp] ${t} scan @${handle}: ${posts.length} posts (${fresh} new)`);
        if (posts.length === 0) {
          console.log(`[fgp]   ↳ 0 posts — X may be showing a login wall to the headless browser (re-check your session)`);
        }
        // Mirror a heartbeat to the server at most every 5 min (don't flood the log).
        if (Date.now() - lastMirror > 300000) {
          log("scan", posts.length > 0, "", `@${handle}: ${posts.length} posts (${fresh} new)`);
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
