# Fox Goal Clipper — Mundial 2026 browser extension

Watches the configured Fox account on **x.com**, downloads every **video** post during a
match, and uploads the clip **+ its text** to the Mundial server. **No classification on
this machine** — the server translates the text to Spanish and posts the **clip** in every
server's goal channel and inline in the web "Now" feed. The web live tracker decides and
announces goals separately; this is just a clip relay. Fully automatic — no approval step.

```
x.com (your logged-in tab)
  └─ content.js   detects Fox video posts (MutationObserver) + keeps the timeline fresh
        └─ background.js  (imports clip-core.js)
             ├─ download the mp4 (Twitter syndication API), preferring <= 8 MB
             ├─ POST /api/v1/goal-clips/ingest  (X-Upload-Key) with the video + post text
             └─ write a line to the activity log (toolbar popup)
```

## Install (load unpacked)

1. Open `chrome://extensions` (or `edge://extensions`) → enable **Developer mode**.
2. **Load unpacked** → select this `fox-goal-clipper/` folder.
3. Open the extension's **Options** and set:
   - **Server URL** — your public Mundial host, e.g. `https://mundial.example.com`.
   - **Upload key** — the exact contents of the server's `secrets/goal_clips_upload_key`.
   - **Monitored handle** — the Fox account, without `@` (e.g. `FoxSoccer`).
   - **Check for new posts every (sec)** — pill-click interval, default `90`.
   - **Hard reload every (sec)** — reload backstop, default `300` (0 = off).
   - Click **Save** and **allow** the permission prompt for your server origin.
4. Open the Fox account's **profile** (or a List of only Fox) in a tab and leave it visible.

## How it works

- **Detection.** A `MutationObserver` in `content.js` watches the page; when a new
  `<article>` containing a video, authored by the monitored handle, is added to the DOM,
  it sends the tweet id + text to the background worker. Each tweet is handled once.
- **Keeping the timeline fresh.** X does **not** auto-inject new profile posts — it queues
  them behind a *"Show N posts"* pill. The extension clicks that pill on the
  *Check for new posts* interval (keeps your scroll position) and hard-reloads the tab on
  the *Hard reload* interval as a backstop. **If both are 0, the extension will only see
  posts already on screen.**
- **Activity log.** Click the toolbar icon to see every decision: detected, downloaded
  (size), uploaded (server clip id), skipped, and errors — newest first, with running
  counts. Also logged to the service-worker console (`[fgc]` lines). Server-side, every
  transferred clip is a row in the `goal_clips` table (`tweet_id`, `status`, `posted_at`).
- **No classification.** The upload includes only the **video** and the post **text**. The
  server translates the text to Spanish and posts the clip during the game window; goal
  decisions/announcements come from the web live tracker, independently.

## Validate (no browser needed for the risky parts)

`validate.mjs` exercises the same `clip-core.js` the extension runs, against the real X
syndication API (Node 18+):

```bash
node validate.mjs                                   # static + X syndication reachability
node validate.mjs https://x.com/FoxSoccer/status/123 # + real clip download from that tweet
```

The DOM detection genuinely needs a browser — validate it manually:
1. `chrome://extensions` → confirm the extension loaded with **no errors**.
2. Click the extension → **service worker** to open its console; watch `[fgc]` lines.
3. Open the Fox profile; the toolbar popup should start showing `scan` / `video` rows.

## Caveats

- **X changes its frontend often.** Detection relies on x.com's DOM (`data-testid`,
  the `/handle/status/id` permalink) and the "Show N posts" pill text. If detection or
  refresh stops working, the selectors in `content.js` are the first thing to update.
- **Some videos are HLS-only** and are skipped (logged as "no mp4 variant").
- **Discord upload limit.** The extension prefers an MP4 variant ≤ 8 MB; larger clips
  still upload (and play on the web), but the bot may post text-only on Discord.
- **Keys stay local** to this browser's extension storage on your PC.
