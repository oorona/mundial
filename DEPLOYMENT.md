# Production Deployment — Mundial 2026

This guide deploys the World Cup 2026 Discord app (baseline framework + the 5 `mundial`
plugins + the WC data layer) to a production server.

> Read [`docs/SECURITY.md`](docs/SECURITY.md) §8–9 and [`docs/DISCORD_APP_SETUP.md`](docs/DISCORD_APP_SETUP.md)
> before going live. This guide references both.

---

## 1. Architecture in production

```
                      Internet (TLS)
                            │
                 ┌──────────▼───────────┐
                 │  Reverse proxy (Caddy │  ← HTTPS termination, your domain
                 │  / nginx / Traefik)   │
                 └─────┬───────────┬─────┘
            / (app)    │           │  /api/v1/*  (rate-limited)
                       ▼           ▼
                 frontend:3000   gateway:80 ──► backend:8000
                       │                              │
                       └── Next rewrites /api/v1 ─────┘ (fallback; SSR uses backend:8000)
                            bot (discord.py)  ─────────┤
                            ──────────────────── dbnet ─┴──► Postgres + Redis (shared infra)
```

- **No bundled Postgres/Redis.** The app uses the **shared Postgres + Redis on the `dbnet`
  Docker network** (the same instance the data-capture phase used). Database name **`mundial`**,
  app user **`mundial`** (so the framework's schema = `mundial`, matching the ingest tables).
- **External Docker networks** are required and shared with the infra: `internet`, `intranet`,
  `dbnet`, `bot`.
- The Discord **Activity** (embedded app) is served from your domain via Discord's URL mapping;
  the `/activity/*` routes already send a `frame-ancestors https://discord.com` CSP.

---

## 2. Prerequisites on the server

- Docker Engine + Docker Compose v2.
- The shared **Postgres** and **Redis** containers running and attached to the `dbnet` network
  (from your infra stack, e.g. `/home/iktdts/apps/infra/postgresdb`). Confirm:
  ```bash
  docker network ls | grep -E 'internet|intranet|dbnet|bot'   # all four must exist
  docker ps | grep -E 'postgres|redis'                        # both running on dbnet
  ```
  Create any missing network with `docker network create <name>`.
- A **domain** (e.g. `mundial.example.com`) with DNS A/AAAA pointing at the server.
- A **Discord application** (bot token, OAuth2 client id/secret) — see `docs/DISCORD_APP_SETUP.md`.
- A **Google Gemini API key** (for the `live_tracker` AI worker).

---

## 3. Get the code on the server

Copy the whole `mundial/` project to the server (git clone or rsync). Everything below runs
from the project root.

> **The 5 product plugins must reach the server.** `.gitignore` keeps demo/staging plugins out
> of git but **tracks** the five mundial plugins (`worldcup_data`, `fixtures_activity`,
> `predictions`, `leaderboard`, `live_tracker`), so a normal `git clone`/`pull` includes them.
> If you transfer the tree another way (or with a tool that honors `.gitignore`), copy them and
> the data layer explicitly:
> ```bash
> rsync -av --relative \
>   plugins/worldcup_data plugins/fixtures_activity plugins/predictions \
>   plugins/leaderboard plugins/live_tracker ingest/data \
>   <user>@<server>:/path/to/mundial/
> ```
> Verify on the server before step 7: `ls plugins/` must list the five folders (and
> `./install_plugin.sh` with no args must show them under "Available plugins").

---

## 4. Secrets

```bash
./setup_secrets.sh
```
Creates `secrets/encryption_key` (settings vault) and `secrets/postgres_password.txt`
(Postgres **superuser** password — must match the shared Postgres). Then create the app DB
password file used by the ingest job (the `mundial` role's password):
```bash
printf '%s' '<mundial-db-password>' > secrets/db_password.txt && chmod 600 secrets/db_password.txt
```
Keep the `secrets/` directory `chmod 700` and never commit it.

---

## 5. Database role, schema and WC data

If the `mundial` database/role/schema do not exist yet on the shared Postgres, create them
(schema is auto-named after the user):
```bash
./setup_database.sh --container <postgres_container_name> --user mundial --db mundial
```
Then load the World Cup dataset (teams, stadiums, groups, 104 matches, players, stats) with the
one-shot ingest job:
```bash
docker compose -f docker-compose.ingest.yml run --rm ingest
```
This must run **before** the app migrations (the `worldcup_data` migration ALTERs the `matches`
table created here). Re-running is idempotent.

---

## 6. Provision flag images

The web UI and Discord embeds serve flags from the frontend's public dir:
```bash
mkdir -p frontend/public/flags && cp ingest/data/flags/*.png frontend/public/flags/
```

---

## 7. Install the 5 plugins (before building images)

`install_plugin.sh` copies plugin code into `bot/`, `backend/`, `frontend/` and registers
routers/migrations. Because production builds images **from source**, install the plugins
**before** building. Install in dependency order:
```bash
./install_plugin.sh worldcup_data
./install_plugin.sh fixtures_activity
./install_plugin.sh predictions
./install_plugin.sh leaderboard
./install_plugin.sh live_tracker
```
(Each prints its file copies + registry writes. `main.py` is never edited — routers load from
`backend/installed_plugins.json`.)

---

## 8. Environment file

Create a `.env` next to the compose files (compose auto-loads it). These feed the prod overlay
and the frontend build:
```dotenv
# Public origin of the app (OAuth redirect, postMessage, absolute flag URLs in embeds)
FRONTEND_URL=https://mundial.example.com
# Baked into the Next.js build (client-visible)
NEXT_PUBLIC_APP_NAME=Mundial 2026
DISCORD_CLIENT_ID=<your_discord_application_client_id>
```
`DISCORD_CLIENT_ID` is required for the Discord Activity handshake (`NEXT_PUBLIC_DISCORD_CLIENT_ID`).

---

## 9. Build and start (production overlay)

```bash
docker compose up -d --build
```
The single `docker-compose.yml` runs the backend without `--reload` (4 workers), sets
`ENVIRONMENT=production` (→ Secure cookies) and `FRONTEND_URL`, bakes the `NEXT_PUBLIC_*` build
args, and sets `restart: always`. Only `.env` differs between local and prod.

Then apply migrations. **Use `heads` (plural):** plugin migrations are independent Alembic
branches, so there are multiple heads:
```bash
docker compose exec backend alembic upgrade heads
```
This creates `prediction_pools` + `predictions` (with RLS) and adds the penalty columns to
`matches`.

> The framework `scripts/deploy.sh` runs `alembic upgrade head` (singular) — change it to
> `heads`, or run the command above manually after `deploy.sh`.

---

## 10. TLS reverse proxy

Terminate HTTPS at a reverse proxy on the `internet` network and route the domain to the app.
Do **not** expose the raw container ports publicly — firewall host ports 3000/8000 (or bind them
to `127.0.0.1` in `docker-compose.yml`) and let the proxy reach the containers by name.

**Caddy example** (`Caddyfile`, automatic TLS):
```
mundial.example.com {
    encode zstd gzip
    # API → nginx gateway (rate limiting + security headers + X-Gateway-Request)
    handle_path /api/* {
        reverse_proxy gateway:80
    }
    # Everything else → the Next.js frontend
    reverse_proxy frontend:3000
}
```
Run Caddy attached to the `internet` network so `gateway` / `frontend` resolve by name, e.g. a
small compose service:
```yaml
services:
  caddy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    networks: [internet]
    restart: always
networks:
  internet: { external: true, name: internet }
volumes:
  caddy_data:
```
(nginx/Traefik work equally well — the only requirement is: `/api/*` → `gateway:80`, everything
else → `frontend:3000`, both over HTTPS on your domain.)

---

## 11. Discord application configuration

In the Discord Developer Portal (details in `docs/DISCORD_APP_SETUP.md`):
1. **OAuth2 → Redirects:** add the callback that matches `FRONTEND_URL`
   (`https://mundial.example.com/api/v1/auth/discord/callback`).
2. **Bot → Privileged Intents:** enable what the bot needs (Server Members / Message Content as
   applicable); invite the bot with the `applications.commands` + `bot` scopes.
3. **Activities:** enable Activities and add a **URL Mapping** with target = your domain so the
   embedded app (`/activity/mundial`, `/activity/predicciones`, `/activity/reglas`,
   `/activity/clasificacion`, `/activity/envivo`) loads from your origin.

---

## 12. First-run Setup Wizard

Open `https://mundial.example.com` — you'll be redirected to the Setup Wizard (runs once,
stored encrypted in the `platform_data` volume). Enter:
- **Database:** host `postgres` (the shared container's network name), port `5432`,
  **database `mundial`**, **user `mundial`**, password = the `mundial` role password.
- **Redis:** host/port of the shared Redis on `dbnet`.
- **Discord:** bot token, OAuth client id + secret.
- **Developer access:** `DISCORD_GUILD_ID` + `DEVELOPER_ROLE_ID` for L6 platform admin.
- **AI:** `GOOGLE_API_KEY` (required for `live_tracker`).

After saving, restart so the bot picks up the token:
```bash
docker compose restart bot
```

---

## 13. Per-guild configuration (in the dashboard)

For each server, an admin sets (Dashboard → Settings / plugin pages):
- **worldcup_data:** `public_base_url` = `https://mundial.example.com` (absolute flag URLs in
  embeds), accent color.
- **predictions:** open the pool, set Kicktipp weights + lock lead minutes.
- **leaderboard:** enable + choose the channel for the auto-updated standings message.
- **live_tracker:** enable + choose the live-events channel. **Stage with auto-commit OFF**, watch
  one real match window, then enable auto-commit. Admins can correct any result on the
  live-tracker page.

---

## 14. Verify

```bash
docker compose ps                                   # all healthy
curl -fsS https://mundial.example.com/api/v1/health # gateway → backend OK
curl -fsS https://mundial.example.com/api/v1/worldcup/groups | head -c 300   # 12 groups
docker compose logs -f bot                          # bot logged in, slash commands synced
```
In Discord: `/mundial grupos` renders flags; launch the Activity → it mints a session and the
drill-down/bracket/map load; `/prediccion` + Activity predict screen accept a group pick;
`/clasificacion` and the leaderboard channel update.

---

## 15. Production hardening checklist

From `docs/SECURITY.md` §8–9 — confirm before exposing publicly:
- [x] HTTPS only (reverse proxy); HSTS is set by the gateway.
- [x] `ENVIRONMENT=production` → Secure cookies (set by the prod overlay).
- [ ] **CSP:** remove `unsafe-inline` / `unsafe-eval` from `gateway/nginx.conf` (the file documents
      the production policy). Re-test the dashboard after tightening.
- [ ] Postgres `5432` and Redis `6379` are **not** published to the public internet (dbnet only).
- [ ] Host ports `3000`/`8000` firewalled or bound to `127.0.0.1`; only the proxy is public.
- [ ] `secrets/` is `chmod 700`, owner-only, never committed; rotate the bot token if it ever leaked.
- [ ] Set up DB backups (below) and log retention.
- [ ] Review the remaining items in SECURITY.md §9 (admin-check caching, token cleanup, HMAC on
      bot→backend, refresh-token encryption) as follow-ups.

---

## 16. Updates / redeploys

For app or plugin changes:
```bash
# 1. (if plugins changed) re-install them onto the source tree
./install_plugin.sh <name>
# 2. rebuild + restart with the prod overlay
docker compose up -d --build
# 3. apply any new migrations
docker compose exec backend alembic upgrade heads
# 4. (cogs/frontend) restart to pick up changes
docker compose restart bot frontend
```
`scripts/deploy.sh` automates pull + build + migrate (edit it to use `alembic upgrade heads`).

---

## 17. Backups, logs, troubleshooting

- **Backup** the `mundial` database regularly and the `platform_data` volume (holds the encrypted
  settings vault — losing it re-triggers the Setup Wizard):
  ```bash
  docker exec <postgres_container> pg_dump -U mundial mundial | gzip > mundial_$(date +%F).sql.gz
  docker run --rm -v mundial_platform_data:/data -v "$PWD":/backup alpine \
    tar czf /backup/platform_data_$(date +%F).tgz -C /data .
  ```
- **Logs:** `docker compose logs -f backend|bot|frontend|gateway`.
- **Bot offline / commands missing:** check the token in the wizard, then `docker compose restart bot`.
- **`Multiple head revisions`:** you ran `alembic upgrade head` — use `heads` (plural).
- **Flags 404 / not in embeds:** ensure step 6 ran and `worldcup_data.public_base_url` is set.
- **Activity won't load:** verify the Discord URL mapping points at your domain and
  `DISCORD_CLIENT_ID` was set at build time (`NEXT_PUBLIC_DISCORD_CLIENT_ID`).
- **`Database not configured` (503):** the wizard hasn't been completed, or DB/Redis creds are wrong.
```
