// clip-core.js — pure, browser/Node-portable logic with NO chrome.* APIs.
//
// X-clip download + syndication helpers shared by the poller (poll.mjs) and the browser
// extension (background.js). Uses only fetch / FormData / Blob, which exist in service
// workers and in Node 18+. No goal classification lives here anymore — the client relays
// the video + text and the server decides/translates.

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
