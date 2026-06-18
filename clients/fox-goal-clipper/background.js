// background.js — MV3 service worker (ES module).
//
// Per candidate (from content.js):
//   1. dedup (durable, chrome.storage.local)
//   2. download the mp4 variant (Twitter syndication API, prefers <= 8 MB)
//   3. POST the clip + its text to the Mundial server's /goal-clips/ingest
//
// No goal classification on the client — the server translates the text and posts the
// clip. Every decision is written to a viewable log (chrome.storage.local 'log'), shown
// in the toolbar popup, so you can see exactly what the extension did with each post.

import { downloadBestClip } from "./clip-core.js";

const PROCESSED_CAP = 800;
const LOG_CAP = 200;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "fgc_candidate") {
    handleCandidate(msg).catch((e) => logEvent(msg.tweetId, "error", false, String(e)));
  } else if (msg && msg.type === "fgc_scan") {
    // content.js reports each sweep so the log shows the watcher is alive.
    if (msg.found) logEvent("", "scan", true, `${msg.found} new video post(s) detected`);
  } else if (msg && msg.type === "fgc_heartbeat") {
    // Live "still watching" status (not a log entry — shown at the top of the popup).
    chrome.storage.local.set({
      status: { ts: Date.now(), handle: msg.handle, url: msg.url, videos: msg.videos, mine: msg.mine },
    });
  }
});

// ── Decision log ────────────────────────────────────────────────────────────────
async function logEvent(tweetId, stage, ok, detail) {
  const entry = { ts: Date.now(), tweetId: tweetId || "", stage, ok: !!ok, detail: detail || "" };
  console.log(`[fgc] ${stage} ${ok ? "OK" : "—"} ${tweetId ? "tweet=" + tweetId : ""} ${detail || ""}`);
  try {
    const { log = [] } = await chrome.storage.local.get("log");
    log.unshift(entry);
    while (log.length > LOG_CAP) log.pop();
    await chrome.storage.local.set({ log });
  } catch (_) {}
  mirrorToServer(entry); // also send to the server so the activity is visible remotely
}

// Best-effort mirror of a log entry to the server's debug-log endpoint.
async function mirrorToServer(entry) {
  try {
    const cfg = await chrome.storage.local.get(["serverUrl", "uploadKey"]);
    if (!cfg.serverUrl || !cfg.uploadKey) return;
    fetch(cfg.serverUrl.replace(/\/+$/, "") + "/api/v1/goal-clips/debug-log", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Upload-Key": cfg.uploadKey },
      body: JSON.stringify(entry),
    }).catch(() => {});
  } catch (_) {}
}

// ── Config + dedup ──────────────────────────────────────────────────────────────
async function getConfig() {
  return await chrome.storage.local.get([
    "serverUrl", "uploadKey", "handle",
  ]);
}

async function alreadyProcessed(id) {
  const { processed = [] } = await chrome.storage.local.get("processed");
  return processed.includes(id);
}

async function markProcessed(id) {
  const { processed = [] } = await chrome.storage.local.get("processed");
  if (!processed.includes(id)) {
    processed.push(id);
    while (processed.length > PROCESSED_CAP) processed.shift();
    await chrome.storage.local.set({ processed });
  }
}

// ── Pipeline ────────────────────────────────────────────────────────────────────
async function handleCandidate({ tweetId, handle, text }) {
  const cfg = await getConfig();
  if (!cfg.serverUrl || !cfg.uploadKey) {
    logEvent(tweetId, "skip", false, "not configured — open Options");
    return;
  }
  const wantHandle = String(cfg.handle || "").replace(/^@/, "").toLowerCase();
  if (wantHandle && handle !== wantHandle) {
    logEvent(tweetId, "skip", false, `handle @${handle} != @${wantHandle}`);
    return;
  }
  if (await alreadyProcessed(tweetId)) return; // already decided; no log noise

  logEvent(tweetId, "video", true, `relaying video — "${(text || "").slice(0, 120)}"`);

  // 2. download
  let clip;
  try {
    clip = await downloadBestClip(tweetId);
  } catch (e) {
    logEvent(tweetId, "download", false, "error: " + e.message + " (will retry)");
    return;
  }
  if (!clip || !clip.blob) {
    logEvent(tweetId, "download", false, "no mp4 variant (HLS-only?) — skipped");
    await markProcessed(tweetId);
    return;
  }
  logEvent(tweetId, "download", true, `${(clip.bytes / 1048576).toFixed(2)} MB, ${clip.variants} variant(s)`);

  // 3. upload (video + text only)
  try {
    const res = await uploadClip(cfg.serverUrl, cfg.uploadKey, tweetId, handle, text, clip.blob);
    logEvent(tweetId, "upload", true, res?.duplicate ? "server already had it" : `uploaded → clip id ${res?.id}`);
  } catch (e) {
    logEvent(tweetId, "upload", false, e.message + " (will retry)");
    return; // leave UN-marked so a later rescan retries
  }
  await markProcessed(tweetId);
}

async function uploadClip(serverUrl, uploadKey, tweetId, handle, text, blob) {
  const base = serverUrl.replace(/\/+$/, "");
  const fd = new FormData();
  fd.append("video", blob, `${tweetId}.mp4`);
  fd.append("tweet_id", tweetId);
  fd.append("tweet_url", `https://x.com/${handle}/status/${tweetId}`);
  fd.append("text", text || "");

  const resp = await fetch(`${base}/api/v1/goal-clips/ingest`, {
    method: "POST",
    headers: { "X-Upload-Key": uploadKey },
    body: fd,
  });
  if (!resp.ok) throw new Error(`ingest ${resp.status}: ${await resp.text()}`);
  return await resp.json();
}
