# Discord Application & Bot Setup

This guide explains how to create a Discord Application, set up a Bot User, and obtain the necessary credentials (`DISCORD_BOT_TOKEN`, `DISCORD_CLIENT_SECRET`) required for this project.

## 1. Create the Application

1.  Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2.  Log in with your Discord account.
3.  Click the **"New Application"** button (top right).
4.  Enter a name for your bot (e.g., "My Awesome Bot") and agree to the terms.
5.  Click **"Create"**.

## 2. Get Client Secret (Application ID & Secret)

1.  You will be redirected to the **"General Information"** page.
2.  Copy the **"Application ID"**. This is your `DISCORD_CLIENT_ID` (if needed later).
3.  Locate the **"Client Secret"** field.
4.  Click **"Reset Secret"** if hidden, then click "Yes, do it!".
5.  **Copy the Client Secret**.
    *   Save this as `DISCORD_CLIENT_SECRET` in your `secrets/discord_client_secret.txt` file.

## 3. Create the Bot User

1.  In the left sidebar, click **"Bot"**.
2.  Click the **"Reset Token"** button to generate your bot's token.
3.  **Copy the Token**.
    *   Save this as `DISCORD_BOT_TOKEN` in your `secrets/discord_bot_token.txt` file.
    *   *Warning: You can only see this token once! If you lose it, you must reset it again.*

## 4. IPrivileged Gateway Intents (CRITICAL)

This framework requires specific "Intents" to function correctly (logging, reading messages, seeing members).

1.  Scroll down on the **"Bot"** page to the **"Privileged Gateway Intents"** section.
2.  Enable the following toggles:
    *   ✅ **Presence Intent**
    *   ✅ **Server Members Intent**
    *   ✅ **Message Content Intent**
3.  Click **"Save Changes"** at the bottom.

## 5. Invite the Bot to Your Server

To verify the bot is working, you need to invite it to a server where you have "Manage Server" permissions.

1.  In the left sidebar, click **"OAuth2"** -> **"URL Generator"**.
2.  **Scopes**: Check the following boxes:
    *   `bot`
    *   `applications.commands` (Critical for slash commands)
3.  **Bot Permissions**: Check the permissions your bot needs. For the Baseline framework, recommended minimums are:
    *   **General**: `View Channels`
    *   **Text**: `Send Messages`, `Embed Links`, `Read Message History`, `Attach Files`
    *   **Threads**: `Create Public Threads`, `Send Messages in Threads` — **required** by the
        live feed (`live_tracker` cog). During a match window (and for the pre-tournament
        news test) the bot opens **one public thread per match** under the configured stream
        channel and posts that match's kickoff/score/final/news there. Without these the bot
        falls back to posting in the parent channel, but the per-match threads will not appear.
        Add `Manage Threads` too if you want the bot to un-archive its own threads after the
        24h auto-archive window.
    *   **Moderation**: `Kick Members`, `Ban Members`, `Manage Messages` (Only if you plan to use these features)
4.  **Copy the Generated URL** at the bottom.
5.  Open the URL in a new browser tab, select your server, and click **"Authorize"**.

---

## 6. Discord Activities (Embedded App SDK)

If your project ships an Activity (a plugin with `activity_pages` in `plugin.json`,
exported with `withActivityPage`), there is **Developer-Portal config** AND there are
**hard architectural rules** the activity code must follow. The framework helpers
(`frontend/lib/activity.ts`, `frontend/app/api-client.ts`, `next.config.mjs`) already
implement the rules below — **do not regress them**.

### Developer-Portal config (operator step, per app)
1. **Activities → Settings** → enable Activities.
2. **Activities → Settings → Supported Platforms**: enable **iOS** and **Android** as well as
   Web/Desktop. If a mobile platform is left off, phones show **"This Activity is not currently
   available on this OS"** and never load the iframe. Save, then fully quit & reopen Discord on the
   device (changes take a couple of minutes to propagate).
3. **Activities → URL Mappings** → map prefix `/` → your domain (e.g. `mundial.example.com`).
   Mobile honors the same mapping — no separate mobile entry is needed.
4. **Supported Contexts**: enable **Guild** (server/voice). Leave **DM/Group DM off** unless
   the activity is built to work without a guild — DMs have **no `guildId`**, so any
   guild-scoped feature (predictions, leaderboard, anything behind `get_activity_user`)
   cannot work there and will look broken.
5. `NEXT_PUBLIC_DISCORD_CLIENT_ID` must be set at **build time** (the frontend Dockerfile
   declares `ARG/ENV NEXT_PUBLIC_DISCORD_CLIENT_ID`, fed from `DISCORD_CLIENT_ID` in `.env`).
   Without it `initActivity()` returns `null` and the activity can never authenticate.

### Three gotchas that WILL bite you (learned the hard way)

**1. Build a SINGLE-PAGE activity — never navigate between `/activity/*` pages.**
The Discord Embedded App SDK handshake (`sdk.ready()` + `authorize()`) reliably succeeds
only on the **first** page Discord loads. A full-page navigation (an `<a href>` to another
`/activity/...` route, or `router.push`) lands on a new page whose re-handshake often
silently fails — and the minted token does **not** survive the navigation. Symptom:
*"works once, then every API call is 401."* Do the handshake **once** on the entry page and
switch screens with in-component **view state / a tab bar** (see `plugins/fixtures_activity`
hub for the reference pattern). Public reference pages (`/worldcup/*`, no auth) can be
separate, but anything needing the session must live in the single page.

**2. The activity token must be held IN MEMORY, not (only) in `localStorage`.**
Discord's activity iframe has **partitioned/unreliable `localStorage`** — a write can
silently no-op and read back `null`. So `authenticateActivity()` calls
`setAuthToken(token)` (an in-memory variable on the API client) and the request interceptor
prefers it over `localStorage`. `localStorage` is written best-effort (wrapped in
`try/catch`) only as a convenience. Because the activity is single-page, the in-memory token
lives for the whole session. Never make activity auth depend on cross-page `localStorage`.
Relatedly: the API client's 401/403 handler must **not** clear the token or redirect to
`/login`/`/access-denied` when `window.location.pathname` starts with `/activity` — those
routes aren't framable and the redirect breaks the activity.

**3. Activity pages must be served `Cache-Control: no-store`.**
Next.js statically prerenders `/activity/*` and serves it with `s-maxage=31536000` (1 year).
Discord/CDN then cache the old HTML shell (which references old JS chunk hashes) and **keep
serving stale code for a year** — your deploys never reach users, even after they restart
Discord. `next.config.mjs` sets `Cache-Control: no-store, must-revalidate` on `/activity/:path*`
(alongside the `frame-ancestors https://discord.com` CSP). If a client already cached the old
shell once, it must clear Discord's cache a single time (quit Discord, delete its `Cache`
folder) to pick up `no-store`; after that it stays fresh.

### Batch writes
High-frequency activity mutations (e.g. saving a page of predictions) should use a **batch**
endpoint guarded by `get_activity_user`, and be listed under `router.audit_exempt_paths` in
`plugin.json` so the audit middleware doesn't write a row per call.

---

**Next Steps:**
Return to the [README](../README.md) and continue with **Step 2 — Generate the encryption key** to complete setup.
