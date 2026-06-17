// background.js — service worker.
//
// Pipeline per candidate (from content.js):
//   1. dedup (durable, chrome.storage.local)
//   2. LLM goal check on the post TEXT (client-side, Gemini) — false positives are OK
//   3. if goal: fetch the tweet's mp4 variant (Twitter syndication API), preferring
//      one <= 8 MB so Discord can upload it natively
//   4. POST the clip + parsed metadata to the Mundial server's /goal-clips/ingest
//
// The server holds the clip until the live tracker confirms that goal on the stream,
// then posts the clip instead of a gif. No human approval — this is fully automatic.

const DISCORD_MAX = 8 * 1024 * 1024; // prefer a variant Discord can upload natively
const PROCESSED_CAP = 800;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "fgc_candidate") {
    handleCandidate(msg).catch((e) => console.warn("[fgc] candidate failed", e));
  }
  // no async response needed
});

async function getConfig() {
  return await chrome.storage.local.get([
    "serverUrl", "uploadKey", "llmApiKey", "llmModel", "handle", "threshold",
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

async function handleCandidate({ tweetId, handle, text }) {
  const cfg = await getConfig();
  if (!cfg.serverUrl || !cfg.uploadKey || !cfg.llmApiKey) {
    console.warn("[fgc] not configured — open the extension Options");
    return;
  }
  const wantHandle = String(cfg.handle || "").replace(/^@/, "").toLowerCase();
  if (wantHandle && handle !== wantHandle) return;
  if (await alreadyProcessed(tweetId)) return;

  // 2. classify the text
  const verdict = await classifyGoal(text, cfg.llmApiKey, cfg.llmModel);
  const threshold = Number(cfg.threshold ?? 0.6);
  if (!verdict || !verdict.is_goal || Number(verdict.confidence ?? 0) < threshold) {
    await markProcessed(tweetId); // not a goal — don't look at it again
    return;
  }

  // 3. fetch the clip
  const clip = await fetchClip(tweetId);
  if (!clip) {
    console.warn("[fgc] no mp4 variant for tweet", tweetId, "(HLS-only or syndication miss) — skipping");
    await markProcessed(tweetId);
    return;
  }

  // 4. upload
  try {
    await uploadClip(cfg.serverUrl, cfg.uploadKey, tweetId, handle, text, verdict, clip);
    console.log("[fgc] uploaded goal clip", tweetId, verdict);
  } catch (e) {
    console.warn("[fgc] upload failed", tweetId, e);
    // leave UN-marked so a later rescan can retry the upload
    return;
  }
  await markProcessed(tweetId);
}

// ── LLM goal classifier (Gemini generateContent, structured JSON) ────────────────
async function classifyGoal(text, apiKey, model) {
  const mdl = (model && model.trim()) || "gemini-flash-latest";
  const prompt =
    "You are classifying a social-media post from a football (soccer) account during " +
    "the 2026 FIFA World Cup. Decide whether the post is announcing that a GOAL was JUST " +
    "scored in a live match. It is NOT a goal post if it is a fixture preview, a lineup, a " +
    "near-miss/chance, a save, a card, a full-time recap of a finished match, general news, " +
    "or commentary. If it is a goal, extract the teams, the score AFTER the goal, the scorer, " +
    "and the minute when present. Respond with strict JSON only.\n\nPOST TEXT:\n" + (text || "");

  const body = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: {
      responseMimeType: "application/json",
      responseSchema: {
        type: "object",
        properties: {
          is_goal: { type: "boolean" },
          home_team: { type: "string" },
          away_team: { type: "string" },
          home_score: { type: "integer" },
          away_score: { type: "integer" },
          scorer: { type: "string" },
          minute: { type: "string" },
          confidence: { type: "number" },
        },
        required: ["is_goal", "confidence"],
      },
    },
  };

  const url =
    `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(mdl)}:generateContent?key=` +
    encodeURIComponent(apiKey);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      console.warn("[fgc] gemini http", resp.status, await resp.text());
      return null;
    }
    const data = await resp.json();
    const raw = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    console.warn("[fgc] gemini error", e);
    return null;
  }
}

// ── Clip download (Twitter syndication API → mp4 variant) ────────────────────────
// react-tweet's token trick: a deterministic token derived from the tweet id lets the
// public syndication endpoint return the tweet (incl. video variants) without auth.
function synToken(id) {
  return ((Number(id) / 1e15) * Math.PI).toString(36).replace(/(0+|\.)/g, "");
}

async function fetchClip(tweetId) {
  const token = synToken(tweetId);
  const url =
    `https://cdn.syndication.twimg.com/tweet-result?id=${tweetId}&lang=en&token=${token}`;
  let json;
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    json = await r.json();
  } catch (e) {
    console.warn("[fgc] syndication fetch failed", e);
    return null;
  }

  const media = json.mediaDetails || (json.video ? [json.video] : []);
  let variants = [];
  for (const md of media) {
    const vs = md?.video_info?.variants || md?.variants || [];
    for (const v of vs) {
      if (v && v.url && (v.content_type === "video/mp4" || /\.mp4/.test(v.url))) {
        variants.push({ url: v.url, bitrate: v.bitrate || 0 });
      }
    }
  }
  if (!variants.length) return null;
  variants.sort((a, b) => b.bitrate - a.bitrate); // high → low

  // Prefer the highest-quality variant that fits Discord's native upload limit.
  for (const v of variants) {
    let len = 0;
    try {
      const head = await fetch(v.url, { method: "HEAD" });
      len = Number(head.headers.get("content-length") || 0);
    } catch (_) {
      len = 0;
    }
    if (len && len <= DISCORD_MAX) {
      const blob = await (await fetch(v.url)).blob();
      return { blob };
    }
  }
  // None confirmed <= 8 MB (or HEAD unsupported) → take the smallest and let the
  // server/Discord decide (web playback still works regardless of size).
  const smallest = variants[variants.length - 1];
  try {
    const blob = await (await fetch(smallest.url)).blob();
    return { blob };
  } catch (e) {
    return null;
  }
}

// ── Upload to the Mundial server ────────────────────────────────────────────────
async function uploadClip(serverUrl, uploadKey, tweetId, handle, text, verdict, clip) {
  const base = serverUrl.replace(/\/+$/, "");
  const fd = new FormData();
  fd.append("video", clip.blob, `${tweetId}.mp4`);
  fd.append("tweet_id", tweetId);
  fd.append("tweet_url", `https://x.com/${handle}/status/${tweetId}`);
  fd.append("text", text || "");
  fd.append("home_team", verdict.home_team || "");
  fd.append("away_team", verdict.away_team || "");
  fd.append("home_score", verdict.home_score != null ? String(verdict.home_score) : "");
  fd.append("away_score", verdict.away_score != null ? String(verdict.away_score) : "");
  fd.append("scorer", verdict.scorer || "");
  fd.append("minute", verdict.minute || "");
  fd.append("confidence", verdict.confidence != null ? String(verdict.confidence) : "");

  const resp = await fetch(`${base}/api/v1/goal-clips/ingest`, {
    method: "POST",
    headers: { "X-Upload-Key": uploadKey },
    body: fd,
  });
  if (!resp.ok) {
    throw new Error(`ingest ${resp.status}: ${await resp.text()}`);
  }
  return await resp.json();
}
