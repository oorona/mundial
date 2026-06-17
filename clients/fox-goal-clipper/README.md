# Fox Goal Clipper — Mundial 2026 browser extension

Watches the configured Fox account on **x.com**, keeps only the **video** posts that a
client-side LLM classifies as a **goal**, downloads the clip, and uploads it to the
Mundial server. The server holds each clip until the live tracker confirms that goal on
its stream, then posts the **clip instead of a gif** in every server's goal channel and
shows it inline in the web "Now" feed. Fully automatic — there is no approval step, and a
stray non-goal clip now and then is acceptable.

```
x.com (your logged-in tab)
  └─ content.js   detects Fox video posts → tweet id + text
        └─ background.js
             ├─ Gemini: "is this text a goal?"  (your API key, stays on this PC)
             ├─ download the mp4 (Twitter syndication API), preferring <= 8 MB
             └─ POST /api/v1/goal-clips/ingest  (X-Upload-Key)
```

## Install (load unpacked)

1. Open `chrome://extensions` (or `edge://extensions`).
2. Toggle **Developer mode** on.
3. **Load unpacked** → select this `fox-goal-clipper/` folder.
4. Click the extension's **Details → Extension options** (or the toolbar icon) and fill in:
   - **Server URL** — your public Mundial host, e.g. `https://mundial.example.com`.
   - **Upload key** — the exact contents of the server's `secrets/goal_clips_upload_key`.
   - **Gemini API key** — a Google AI Studio key (used only on this machine).
   - **Gemini model** — leave blank for `gemini-flash-latest`.
   - **Monitored handle** — the Fox account, without `@` (e.g. `FoxSoccer`).
   - **Confidence threshold** — default `0.6`.
   - Click **Save** and **allow** the permission prompt for your server origin.

## Use

Open the Fox account's **profile** (or a List that contains only Fox) in a tab and leave
it visible during matches. New video posts are processed as they appear. Watch the
service-worker console (`chrome://extensions` → the extension → **service worker**) for
`[fgc]` log lines.

## Caveats (read these)

- **X changes its frontend often.** Detection relies on x.com's DOM (`data-testid`
  attributes, the `/handle/status/id` permalink). If clips stop being detected, the
  selectors in `content.js` are the first thing to update.
- **Some videos are HLS-only.** The downloader uses Twitter's public syndication API,
  which exposes MP4 variants for most clips; the occasional HLS-only video is skipped.
- **Discord upload limit.** The extension prefers an MP4 variant ≤ 8 MB so the bot can
  upload it natively. Larger clips still upload to the server (and play on the web), but
  the bot may fall back to a text-only goal post on Discord if Discord rejects the size.
- **Keys stay local.** The Gemini key and upload key live only in this browser's
  extension storage on your PC; nothing is sent anywhere except Google (classification)
  and your own server (upload).
- **Dedup.** Each tweet is processed once (tracked in extension storage). Re-scanning the
  timeline will not re-upload an already-handled post.
