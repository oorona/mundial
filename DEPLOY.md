# Deploy — Mundial 2026

Plugins are already installed into the app and committed, so after your tool copies the files
to the server, run these steps **on the server** (from the project root).

Prereqs: Docker + Compose, the shared Postgres+Redis on the `dbnet` network, and the
`internet`/`intranet`/`dbnet`/`bot` networks existing.

## 1. Secrets
```bash
./setup_secrets.sh                                   # encryption key + postgres superuser pw
printf '%s' '<mundial-db-password>' > secrets/db_password.txt && chmod 600 secrets/db_password.txt
```

## 2. Database + World Cup data (first time only)
```bash
./setup_database.sh --container <postgres_container> --user mundial --db mundial   # if not created yet
docker compose -f docker-compose.ingest.yml run --rm ingest                        # load teams/matches/...
```

## 3. Flags
```bash
mkdir -p frontend/public/flags && cp ingest/data/flags/*.png frontend/public/flags/
```

## 4. Config — create `.env`
```dotenv
FRONTEND_URL=https://mundial.example.com
NEXT_PUBLIC_APP_NAME=Mundial 2026
DISCORD_CLIENT_ID=<discord_application_client_id>
```

## 5. Start + migrate
```bash
docker compose up -d --build
docker compose exec backend alembic upgrade heads
```

## 6. Discord application setup
**Privileged Gateway Intents** (Dev Portal → Bot) — the bot requests these at startup and will
**fail to boot** if they're off:
- ✅ Server Members Intent
- ✅ Message Content Intent
- (Presence Intent: not required)

**OAuth2 Redirect URI** (Dev Portal → OAuth2 → Redirects) — add this **exact** URL:
```
https://mundial.mexicodev.org/api/v1/auth/discord/callback
```
The backend's callback is `/api/v1/auth/discord/callback` (it exchanges the code, then redirects to
`FRONTEND_URL`). This **must match byte-for-byte** the "OAuth Redirect URI" you enter in the Setup
Wizard (step 7) — Discord rejects any mismatch. (Note: it is NOT `/auth/callback`; ignore the wizard's
placeholder.)

**Invite the bot** with scopes `bot` + `applications.commands` and these guild permissions:
View Channels, Send Messages, Embed Links, Read Message History, **Create Public Threads**,
**Send Messages in Threads** (perms integer **309237730304**):
```
https://discord.com/oauth2/authorize?client_id=<CLIENT_ID>&scope=bot+applications.commands&permissions=309237730304
```
The two Threads permissions are required by the live feed (`live_tracker`), which opens one
public thread per match under the configured stream channel. Optionally add **Manage Threads**
(to let the bot un-archive its own threads) → perms integer **326417599488**. If a thread
permission is missing the bot silently falls back to posting in the parent channel.

**Activities** (Dev Portal → Activities): enable, and add a URL Mapping with target = your domain.

## 7. First run — Setup Wizard
HTTPS/routing is handled by Traefik (labels in `docker-compose.yml`: host → `frontend:3000`,
`/api/*` → `backend:8000`). Open the site → it redirects to the wizard. Enter:
- **Database:** host `postgres`, port `5432`, db `mundial`, user `mundial`, + the db password.
- **Redis:** host `redis`, port `6379`.
- **Discord:** bot token, OAuth client id + secret, and **OAuth Redirect URI** =
  `https://mundial.mexicodev.org/api/v1/auth/discord/callback` (the same value registered in the Discord portal).
- **Bot Name** and **Application Name:** e.g. `mundial` (this is what the UI displays).
- **GOOGLE_API_KEY** for the live tracker.

Save, then `docker compose restart bot`.

## Redeploy (after copying updated files)
```bash
docker compose up -d --build
docker compose exec backend alembic upgrade heads
```
