# Fox Goal Poller — headless background capture (Windows)

A background process that watches Fox's X account(s) for goal clips and uploads them to
the Mundial server — using the **same** classify → download → upload logic as the browser
extension, but **headless**. There is no visible browser window, so the **OS screen lock
has no effect**: as long as the PC is awake, it keeps capturing goals whether you're at the
desk or away.

Use this instead of the browser extension when the machine's screen locks.

## One-time setup (Windows)

1. **Install Node.js (LTS)** from <https://nodejs.org> (the "LTS" installer). Accept the
   defaults. Then open **PowerShell** (or Command Prompt) and check:
   ```
   node --version
   ```
   It should print v20.x or similar.

2. **Get this folder onto the PC** (copy the whole `fox-goal-poller` folder), then in
   PowerShell `cd` into it:
   ```
   cd path\to\fox-goal-poller
   ```

3. **Install dependencies + a browser engine:**
   ```
   npm install
   npx playwright install chromium
   ```

4. **Create your config:** copy `config.example.json` to `config.json` and fill it in:
   ```
   copy config.example.json config.json
   notepad config.json
   ```
   - `serverUrl` — your Mundial host (e.g. `https://mundial.mexicodev.org`)
   - `uploadKey` — the server's `goal_clips_upload_key`
   - `llmApiKey` — your Google AI Studio (Gemini) key
   - `handles` — the Fox accounts to watch, e.g. `["FOXSports", "FOXSoccer", "FIFAWorldCup"]`
   - `maxAgeMinutes` / `pollSeconds` / `threshold` — leave the defaults unless you want to tune.

5. **Log into X once** (opens a real browser; log in, then press Enter in PowerShell):
   ```
   node login.mjs
   ```
   This saves your session to `auth.json` so the headless poller stays logged in.

## Run it

```
npm start
```

You'll see `[fgp] …` lines for every scan/classify/download/upload. Those also mirror to the
server, so the activity is visible there too. Leave this window running during matches.

## Keep it running automatically

So you don't have to keep a PowerShell window open, run it as a background task that
**auto-restarts** and **starts on boot**:

**Option A — a restart loop (simplest).** Create `run.bat` in this folder:
```bat
@echo off
cd /d %~dp0
:loop
node poll.mjs
echo poller exited, restarting in 10s...
timeout /t 10 >nul
goto loop
```
Double-click `run.bat` (or add a shortcut to it in `shell:startup` so it launches at login).

**Option B — Task Scheduler (starts on boot, no window).** Create a Basic Task → Trigger
"When the computer starts" → Action "Start a program" → Program `node`, Arguments
`poll.mjs`, **Start in** = this folder. Tick "Run whether user is logged on or not."

## Notes & caveats
- **Screen lock is fine** — the poller is headless, so locking the screen doesn't touch it.
  The PC just needs to stay **awake** (you said yours never sleeps — perfect).
- **Don't run the extension and the poller at the same time** for the same handle, or you'll
  upload each clip twice. The server dedups by tweet id, so it's harmless, but pick one.
- **X may change its frontend.** Detection uses the same selectors as the extension
  (`article`, `/handle/status/id`, `data-testid="videoComponent"`); if it stops finding
  posts, those selectors in `poll.mjs` are the first thing to update.
- **Keys stay local** in `config.json` / `auth.json` (git-ignored). Nothing is sent anywhere
  except Google (classification) and your own server (upload).
- HLS-only videos (no MP4 variant) are skipped, same as the extension.
