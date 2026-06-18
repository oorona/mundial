// clip-core.js — pure, browser/Node-portable logic with NO chrome.* APIs.
//
// Imported by both background.js (the MV3 service worker) and validate.mjs (the
// headless test harness), so the X-clip download and the Gemini goal classifier are
// validated as the SAME code the extension actually runs (no parallel reimplementation
// that can drift). Uses only fetch / FormData / Blob, which exist in service workers
// and in Node 18+.

export const DISCORD_MAX = 8 * 1024 * 1024; // prefer a variant Discord can upload natively

// react-tweet's token trick: a deterministic token derived from the tweet id lets the
// public syndication endpoint return the tweet (incl. video variants) without auth.
export function synToken(id) {
  return ((Number(id) / 1e15) * Math.PI).toString(36).replace(/(0+|\.)/g, "");
}

export function parseTweetId(input) {
  const s = String(input || "").trim();
  const m = s.match(/status\/(\d+)/) || s.match(/^(\d{6,25})$/);
  return m ? m[1] : null;
}

export async function fetchSyndication(tweetId, fetchImpl = fetch) {
  const token = synToken(tweetId);
  const url = `https://cdn.syndication.twimg.com/tweet-result?id=${tweetId}&lang=en&token=${token}`;
  const r = await fetchImpl(url);
  if (!r.ok) throw new Error(`syndication HTTP ${r.status}`);
  return await r.json();
}

export function extractMp4Variants(json) {
  const media = json.mediaDetails || (json.video ? [json.video] : []);
  const variants = [];
  for (const md of media) {
    const vs = md?.video_info?.variants || md?.variants || [];
    for (const v of vs) {
      if (v && v.url && (v.content_type === "video/mp4" || /\.mp4/.test(v.url))) {
        variants.push({ url: v.url, bitrate: v.bitrate || 0 });
      }
    }
  }
  variants.sort((a, b) => b.bitrate - a.bitrate); // high → low
  return variants;
}

// Download the best mp4 that fits Discord's native upload limit (else the smallest).
// Returns { blob, text, variants, bytes }. blob is null when there is no mp4 variant.
export async function downloadBestClip(tweetId, fetchImpl = fetch) {
  const json = await fetchSyndication(tweetId, fetchImpl);
  const variants = extractMp4Variants(json);
  const text = json.text || "";
  if (!variants.length) return { blob: null, text, variants: 0 };

  for (const v of variants) {
    let len = 0;
    try {
      const head = await fetchImpl(v.url, { method: "HEAD" });
      len = Number(head.headers.get("content-length") || 0);
    } catch (_) {
      len = 0;
    }
    if (len && len <= DISCORD_MAX) {
      const blob = await (await fetchImpl(v.url)).blob();
      return { blob, text, variants: variants.length, bytes: blob.size };
    }
  }
  const smallest = variants[variants.length - 1];
  const blob = await (await fetchImpl(smallest.url)).blob();
  return { blob, text, variants: variants.length, bytes: blob.size };
}

// Classify a post's text as a goal (or not) with Gemini structured output.
export async function classifyGoal(text, apiKey, model = "gemini-flash-latest", fetchImpl = fetch) {
  const mdl = (model && String(model).trim()) || "gemini-flash-latest";
  const prompt =
    "You are classifying a VIDEO post from a football (soccer) account during the 2026 FIFA " +
    "World Cup. Almost every video here is a goal highlight. Set is_goal=true if the text " +
    "describes a goal being SCORED in ANY tense or phrasing. ALL of these are goals: 'GOAL', " +
    "'scores' / 'scored', 'gets the goal', 'nets' / 'finds the net', 'finish' / 'header' / " +
    "'strike' / 'volley', 'golazo', 'converts', 'puts it in', 'on the scoresheet', 'opens the " +
    "scoring', 'doubles the lead', 'equalizes' / 'levels', 'bags a brace', 'hat-trick', 'instant " +
    "impact ... scores', a player's CELEBRATION after scoring, or a montage of a player's goals. " +
    "LEAN YES: if it plausibly describes a goal that was scored, answer is_goal=true with " +
    "confidence >= 0.75 (a stray non-goal clip is acceptable). Set is_goal=false ONLY when it is " +
    "clearly NOT a goal: a save / denied chance, a near-miss, a goal DISALLOWED or ruled out by " +
    "VAR, a yellow/red card, a penalty MISS, a fixture preview / lineup / prediction, an " +
    "interview, a stat graphic, or a crowd / anthem / stadium shot. When present, extract the " +
    "teams, the score after the goal, the scorer, and the minute (blank if not stated). " +
    "IMPORTANT: set scoring_team to the name of the team that SCORED — the post usually says it " +
    "(e.g. \"UZBEKISTAN'S goal\", \"scores for Switzerland\") → use that team's name; blank only " +
    "if genuinely unclear. Respond with strict JSON only.\n\nPOST TEXT:\n" + (text || "");

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
          scoring_team: { type: "string" },
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
  const resp = await fetchImpl(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`gemini HTTP ${resp.status}: ${await resp.text()}`);
  const data = await resp.json();
  const raw = data?.candidates?.[0]?.content?.parts?.[0]?.text;
  return raw ? JSON.parse(raw) : null;
}
