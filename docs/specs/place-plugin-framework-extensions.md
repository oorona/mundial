# Framework Extensions Required to Host `place` as a Plugin

**Status:** Proposed spec — no framework code changed yet.
**Author context:** `place` is an r/place-style collaborative pixel-canvas Discord app, built
standalone at `/home/iktdts/apps/website/place` (FastAPI backend + discord.py bot + Next.js
frontend). It is the first real app built against this framework. This document is the result of
evaluating whether `place` can be re-homed as a Baseline **plugin**, and specifies exactly what the
framework must add for that to be possible.

These gaps generalize: any "rich app" (a real-time, partly-public, Activity-based app with
scheduled server-side work) will hit the same four walls. Treat this as the framework's **rich-app
extension spec**, not a one-off for `place`.

---

## 1. Executive summary

The plugin system is real and covers more than expected. **About half of `place` fits today with no
framework change.** The blockers are four framework capabilities that do not yet exist, plus one
audit-volume hazard and one minor settings-form limitation.

| `place` capability | Supported today? | Resolution |
|---|---|---|
| Slash commands (`/place`, `/leaderboard`, `/mystats`, `/place-admin …`) | ✅ Yes | plugin cog |
| Admin UI (settings form, snapshot gallery, heatmap) | ✅ Yes | dashboard page (L4/L5) |
| Guild-scoped admin API (settings CRUD, snapshots, heatmap) | ✅ Yes | router via `get_guild_db` |
| **Public per-guild website** (live canvas, leaderboard, GIF; no login) | ✅ Yes | L0/L1 page keyed on `[guildId]` + public route via `get_guild_db` — see §3 |
| Models + migration | ✅ Yes\* | append to `models.py`; independent alembic branch |
| **Discord Activity** (Embedded App SDK iframe) | ❌ No | **§4 — Gap A** |
| **Real-time updates** (SSE pixel stream) | ❌ No | **§5 — Gap B** |
| **High-frequency placement** (rate limits + audit volume) | ❌ No | **§6 — Gap C** |
| **Scheduled server-side work** (void, snapshots, points flush/decay, activity stream) | ❌ No | **§7 — Gap D** |
| Rich settings (16-color palette, canvas dims, gate-mode enum) | ⚠️ Partial | **§8 — Gap E** |

`*` requires the model/RLS/migration adjustments in §9.

Each gap section below states: **(a)** the framework file(s) to change and the proposed interface;
**(b)** the matching `scripts/plugin_validate.py` rule change; **(c)** the `plugin.json` manifest
addition; **(d)** the docs to update.

---

## 2. Evidence baseline (verified in the current codebase)

- **Public pages already exist and are per-server.** `frontend/lib/permissions.ts` defines
  `PUBLIC = 0` and `PUBLIC_DATA = 1`. `frontend/lib/components/with-permission.tsx` short-circuits
  with `if (requiredLevel <= PermissionLevel.PUBLIC_DATA) return;` (no login required).
  `frontend/middleware.ts` only guards setup state, never auth. `plugins/test_pages/test-l1.page.tsx`
  is a working per-guild public page that reads `guildId` from the URL and calls
  `apiClient.getGuildPublicInfo(guildId)`; the backend `backend/app/api/guilds.py`
  `GET /{guild_id}/public` uses `Depends(get_guild_db)` (RLS keyed on the URL `guild_id`) with **no**
  `get_current_user`. Root-level public pages also exist (`/commands`, L1, Redis-cached).
- **Plugin loader** (`backend/app/plugin_loader.py`) mounts each plugin router at
  `{api_prefix}{prefix}` (prefix default `/guilds`) from `backend/installed_plugins.json`.
- **Validator** (`scripts/plugin_validate.py`): pages must `export default withPermission(...)`,
  must `useTranslation()`, must use the typed `apiClient`; **raw `fetch()`, axios, and `EventSource`
  are rejected**. `{guild_id}` routes must use `get_guild_db`. Mutations must reference `AuditLog`
  (auto-written by middleware). `SETTINGS_SCHEMA` field types are limited to
  `{boolean, channel_select, role_select, multiselect, text, number}`.
- **Installer** (`scripts/plugin_install.py`) copies pages only to
  `frontend/app/dashboard/[guildId]/<plugin>/`.
- **DB** (`backend/app/db/session.py`, `guild_session.py`): single shared schema via `search_path`;
  RLS via `app.current_guild_id`; `get_guild_db(guild_id)`, `get_admin_db` (RLS bypass +
  `verify_platform_admin`), `get_db` (RLS bypass). `Base = declarative_base()`; guild tables marked
  `__guild_scoped__ = True`.
- **Bot** (`bot/core/bot.py`): `commands.AutoShardedBot`; cogs auto-loaded by `bot/core/loader.py`.
  The bot carries `self.services` (config, redis, llm — `bot/services/`) and an aiohttp
  `self.session`. **There is no DB session on the bot** — cogs reach data over HTTP to the backend.
- **Audit middleware** (`backend/main.py`, `GuildAuditMiddleware`): writes one `AuditLog` row for
  **every** successful `POST/PUT/PATCH/DELETE` whose path matches `/guilds/(\d+)/`. Plugins must not
  write `AuditLog` themselves.
- **Rate limiter** (`backend/main.py` → `app/core/limiter.py`, slowapi): registered globally; the
  per-route mechanism is slowapi's `@limiter.limit(...)` decorator.
- **Migrations** run at backend startup (`run_alembic_migrations()` → `alembic upgrade head` in the
  lifespan), and plugin migrations are designed as independent alembic branches applied from the
  dashboard DB-management page.

---

## 3. Gap 0 — Public per-server surface (IMPLEMENTED as a framework slug system)

> **Decision update (superseding the original "drop slugs" guidance below).** Rather than dropping
> slugs, the framework now owns a **first-class slug system** so Level 0 (PUBLIC) supports public
> per-server sites by slug **plus** a generic project-wide landing page. Slugs are kept and
> generalized; `place` reuses them instead of carrying its own.

What shipped:
- **`slug` on the framework `Guild` model** (`backend/app/models.py`), globally unique, auto-assigned
  on guild create (`slugify`/`unique_slug` in `backend/app/core/slugs.py`), Redis-cached
  (`slug:{slug}`→id), renamable by guild admins via `PUT /guilds/{id}/slug`.
- **`get_public_guild_db(slug)`** (`backend/app/db/guild_session.py`): the reusable primitive for
  public per-server routes — resolves the slug RLS-bypassed (the chicken-and-egg of looking up a
  guild-scoped table by a non-id column), 404s on miss, then yields an RLS-active session scoped to
  the resolved guild. Plugins build their public reads on this.
- **Configurable URL prefix** (default `/p`): canonical route group `frontend/app/(public)/p/[slug]/`
  with a generic landing page at `/p` (`app/(public)/p/page.tsx`). `next.config` rewrites a custom
  `NEXT_PUBLIC_SLUG_PREFIX` onto the canonical group; `LayoutChrome` serves the group full-bleed.
- **Public pages** are declared `"public_pages"` in `plugin.json` (installer → `(public)/p/[slug]/<path>`)
  and exported with `withPublicPage(...)`. Public reads are Redis-cached like the L1 `/commands` route.
- `place` accordingly **reuses** the framework slug + `get_public_guild_db` instead of its own
  `services/slugs.py` / `app/[slug]` / `place:slug:*` subsystem.

Live updates on the public page degrade gracefully to polling via `apiClient` with **zero**
framework change; true server push is Gap B (§5).

---

## 4. Gap A — Discord Embedded App SDK Activity surface

**Problem.** The framework has Discord OAuth for the dashboard, but no concept of a Discord
*Activity* (an Embedded App SDK iframe loaded inside Discord). The plugin frontend model installs
dashboard pages only; there is no Activity route, no Activity auth handshake, and no iframe/CSP
configuration. `place`'s interactive in-Discord canvas requires all three.

**(a) Framework changes**

- **Frontend route group + installer.** Add an Activity route group, e.g.
  `frontend/app/activity/[plugin]/` (outside `dashboard/`, no `withPermission`). Extend
  `scripts/plugin_install.py` to copy a plugin's Activity page(s) there based on a new manifest
  section (below). Serve these routes with Activity-appropriate headers — `Content-Security-Policy`
  with `frame-ancestors https://discord.com https://*.discord.com` and `X-Frame-Options` removed for
  this route group (set via `next.config` headers or a scoped middleware branch). Document
  `@discord/embedded-app-sdk` as a permitted plugin frontend dependency.
- **Backend Activity auth.** Extend `backend/app/api/auth.py` with the Activity handshake:
  - `POST /auth/activity` — exchange the SDK `code` for a Discord token, fetch `/users/@me`, read the
    `guild_id` from the Activity instance, **re-verify membership with the bot token before trusting
    it** (generalize the existing membership lookup in `app/core/discord.py`), then mint an
    *activity session* in Redis (`activity_session:{token}`, scoped to one `{user_id, guild_id}`).
  - Add a dependency `get_activity_user(...)` in `backend/app/api/deps.py` mirroring
    `get_current_user`, reading the activity session. Activity API routes (state, place) depend on
    it instead of `get_current_user`.
- **CORS / CSP / config.** Add the Discord Activity origin(s) to `BACKEND_CORS_ORIGINS`
  (`backend/app/core/config.py`) and ensure the new CSP applies only to the Activity route group, not
  the dashboard.

**(b) Validator change** (`scripts/plugin_validate.py`)

- Add an **activity-page class**: pages declared as Activity pages are exempt from the
  `withPermission` requirement and may import `@discord/embedded-app-sdk`. They must still use
  `useTranslation()` and the sanctioned data helpers (`apiClient` for non-stream calls;
  `subscribeSSE` from Gap B for streams).

**(c) `plugin.json` addition**

```json
"activity_pages": [
  { "source": "activity.tsx", "path": "place" }
]
```
(installer copies `activity.tsx` → `frontend/app/activity/place/page.tsx`).

**(d) Docs to update**

- `docs/PLUGIN_SYSTEM_SPECS.md` — new "Activity surface" layer alongside Cog/API/Frontend.
- `docs/integration/08-plugin-workflow.md` — Activity build steps + the operator step of registering
  the Activity URL mapping and enabling the **Activities** feature in the Discord developer portal.
- `plugins/_template/` — add a minimal `activity.tsx` example.

---

## 5. Gap B — Real-time streaming (SSE)

**Problem.** Live pixel updates need a server→client push channel. The backend exposes only REST,
and the validator rejects raw `fetch()`/`EventSource` on the client. `place` uses an SSE endpoint
tailing a Redis stream.

**(a) Framework changes**

- **Backend SSE helper.** Add `sse_response(async_gen)` (e.g. `backend/app/core/streaming.py`)
  wrapping `starlette.responses.StreamingResponse` with the correct SSE headers, plus a documented
  "tail a Redis stream → yield events" recipe (`XREAD BLOCK` loop with disconnect handling). Plugin
  SSE routes return `sse_response(...)`.
- **Frontend client helper.** Add `subscribeSSE(path, onEvent)` to the frontend lib (e.g.
  `frontend/lib/streaming.ts`) — a thin `EventSource` wrapper that resolves the API base the same way
  `apiClient` does. Plugins use this instead of constructing `EventSource` directly.

**(b) Validator change** (`scripts/plugin_validate.py`)

- Allow `StreamingResponse` / `sse_response` in plugin `api.py`.
- Allow `subscribeSSE` (and, on public/activity pages, `EventSource`) so live updates do not trip the
  "no raw fetch / no EventSource" rule. Keep the rule for ordinary data fetching.

**(c) `plugin.json` addition**

- None required (SSE routes are ordinary router routes). Optionally a `"capabilities": ["sse"]` hint
  for documentation.

**(d) Docs to update**

- `docs/DEVELOPER_MANUAL.md` and `docs/ARCHITECTURE.md` — "Real-time updates" section (SSE pattern,
  Redis-stream tail, disconnect handling).
- `CLAUDE.md` — note the sanctioned `sse_response` / `subscribeSSE` helpers as the only approved
  streaming path.

---

## 6. Gap C — High-frequency mutations: rate limits + audit volume

**Problem (two parts).**

1. **Rate limits.** Pixel placement is high-frequency by design; a single global slowapi limit will
   throttle legitimate play. Placement throttling belongs to the plugin (time cooldown / points
   gate), not the global limiter.
2. **Audit-log volume (hazard).** `GuildAuditMiddleware` writes one `AuditLog` row for **every**
   successful mutation matching `/guilds/(\d+)/`. If placement is mounted under
   `/guilds/{guild_id}/place/...`, every single pixel becomes an audit row — unbounded write
   amplification. This is a real correctness/scale problem, not a style nit.

**(a) Framework changes**

- **Per-route limit override.** Document and support per-route slowapi limits via
  `@limiter.limit("…")` on plugin endpoints, and an *exempt* marker for SSE and public reads. Provide
  a small helper or documented pattern so a plugin can raise/relax limits on specific routes without
  touching `app/core/limiter.py`.
- **Audit exemption for high-frequency mutations.** Add a sanctioned way to exclude a route from
  `GuildAuditMiddleware`. Options (pick one in implementation):
  - a path-prefix allowlist the middleware skips (e.g. routes under a plugin-declared
    `audit_exempt` prefix), or
  - mounting high-frequency mutating routes under a non-`/guilds/{guild_id}/` prefix (e.g. the
    Activity router prefix `/activity/...`), which the middleware's `/guilds/(\d+)/` pattern already
    ignores — document this as the recommended placement for placement endpoints.
  Either way, the framework must offer an explicit, documented escape so plugins are not forced to
  emit one audit row per pixel.

**(b) Validator change** (`scripts/plugin_validate.py`)

- The existing rule "mutation endpoints must reference `AuditLog`" assumes middleware coverage. For
  audit-exempt routes, relax it: a route declared audit-exempt (or mounted outside `/guilds/{id}/`)
  is not required to reference `AuditLog`. Make the exemption explicit so it is not a silent bypass.

**(c) `plugin.json` addition**

```json
"router": { "prefix": "/guilds", "tag": "place", "audit_exempt_paths": ["/{guild_id}/place"] }
```
(or document the "place high-frequency mutations under `/activity`" convention instead).

**(d) Docs to update**

- `docs/DEVELOPER_MANUAL.md` — "Rate limiting & audit volume for high-frequency endpoints".
- `CLAUDE.md` — Golden Rule 5 currently says *never* skip audit; add the sanctioned exemption so the
  rule stays honest for real-time apps.

---

## 7. Gap D — Bot-side single-writer background workers with DB access

**Problem.** `place` runs five scheduled server-side jobs (void tick, canvas snapshots, points
flush/decay, points snapshot, activity-channel stream) that read and write Postgres + Redis on a
timer. In `place` these are `tasks.loop` cogs on the bot, relying on a single writer. The framework
bot has **no DB session** — cogs reach data only over HTTP — so these workers cannot run as-is.

Per the chosen direction (and the framework's "never replicate the bot" rule), the worker runs on
the bot: a single-process `AutoShardedBot` is inherently a single writer.

**(a) Framework changes**

- **DB session on the bot.** Add an optional async engine + sessionmaker to `BotServices`
  (`bot/services/`), reading the same `DATABASE_URL` / `effective_schema` as the backend and confined
  to the schema via `search_path` (mirror `backend/app/db/session.py`). Expose it as
  `self.bot.services.db`. Initialize it in `BotServices.initialize(...)` and dispose in `close()`.
- **Worker session helper.** Provide `get_worker_session()` (or
  `services.db.worker_session()`) yielding a session with RLS bypassed
  (`SET LOCAL app.bypass_guild_rls = 'true'`) for cross-guild iteration; workers set
  `app.current_guild_id` per guild when they need RLS-scoped writes. This is the bot-side analogue of
  `get_admin_db`.
- **Documented "worker cog" pattern.** A cog using `tasks.loop`, iterating active guilds, writing via
  the worker session + `self.bot.services.redis`. Document the single-writer guarantee
  (single-process AutoShardedBot) and the explicit warning never to scale the bot to multiple
  processes.

**(b) Validator change** (`scripts/plugin_validate.py`)

- Permit `self.bot.services.db` usage inside a cog (today there is no rule against it; make it
  explicit and documented so it is not mistaken for a violation). Optionally key this on a manifest
  `worker: true` flag.

**(c) `plugin.json` addition**

```json
"worker": true
```

**(d) Docs to update**

- `docs/DEVELOPER_MANUAL.md` and `docs/ARCHITECTURE.md` — "Scheduled work / worker cogs", including
  the single-writer rule and the `services.db` access pattern.
- `plugins/_template/` — add a minimal worker-cog example (`tasks.loop` + `services.db`).

---

## 8. Gap E — Settings richness + plugin-owned settings tables

**Problem.** `SETTINGS_SCHEMA` field types are limited to
`{boolean, channel_select, role_select, multiselect, text, number}`
(`_VALID_FIELD_TYPES` in `scripts/plugin_validate.py`). `place` needs a 16-color **palette editor**,
**canvas dimensions** (bounded integers), and a **gate-mode enum** (`time | points | both`). The
auto-rendered form cannot express the palette today.

**(a) Framework changes**

- Extend `_VALID_FIELD_TYPES` **and** the dashboard auto-form renderer with: `color`, `color_list`
  (an ordered palette of N colors), `select` (single-choice enum), and `number` with
  `min`/`max`/`step`. This lets palette, gate mode, and canvas size render in the standard form.
- Explicitly sanction a **plugin-owned settings table** (e.g. `place_guild_setting`) plus a custom
  dashboard settings page as an alternative to `GuildSettings.settings_json`. Document the trade-off:
  use the JSON blob + `SETTINGS_SCHEMA` for simple settings (auto-form, zero frontend), or a
  plugin-owned table + custom page when the settings are numerous/typed (as `place` is).

**(b) Validator change** (`scripts/plugin_validate.py`)

- Update `_VALID_FIELD_TYPES` and `_validate_settings_schema_in_cog(...)` to accept the new field
  types and their extra keys (`min`, `max`, `step`, `options`, `count`).

**(c) `plugin.json` addition**

- None (settings live in the cog `SETTINGS_SCHEMA` or a plugin-owned table + `models`/`migration`).

**(d) Docs to update**

- `docs/PLUGIN_SYSTEM_SPECS.md` and `docs/integration/08-plugin-workflow.md` — the new field types
  and the "plugin-owned settings table vs `settings_json`" decision.

---

## 9. Plugin-author responsibilities (the eventual `place` refactor — not done now)

Recorded so scope is explicit. Once the framework gains §4–§8, converting `place` to
`plugins/place/` requires the plugin author to:

- Drop per-table `MetaData(schema=…)` in `models.py`; rely on the framework `search_path`. Append
  `place` models to `backend/app/models.py` (or a plugin `models.py` the installer appends).
- Mark guild-scoped tables `__guild_scoped__ = True` (RLS on `guild_id`).
- Ship the schema as a single **independent alembic branch** (installer patches `down_revision = None`
  + a branch label; applied from the dashboard DB-management page, not relying on startup
  `upgrade head`).
- Drop the slug subsystem in favor of `[guildId]` (§3).
- Drop the `InMemoryStore` dev fallback in favor of the framework's `get_redis` (keep an in-memory
  shim only in the plugin's own unit tests).
- Fold `place`'s three Docker services into the shared framework containers: the cog(s) → the bot,
  the routers → the backend, the pages → the frontend. `place` no longer owns a `docker-compose.yml`.
- Mount high-frequency placement under an audit-exempt / non-`/guilds/{id}/` prefix (§6).

---

## 10. Acceptance criteria for this spec

This spec is complete when, for **each** gap (§4–§8) it states: (a) the exact framework file(s) to
change and the proposed interface; (b) the matching `plugin_validate.py` rule change; (c) the
`plugin.json` addition; and (d) the docs to update — which it does. Every `place` capability in the
§1 table maps to either "supported today" or a specific gap section, with none left unaddressed
(verified in §11).

The framework work itself is complete when a reference plugin can: serve a public per-guild page; run
a Discord Activity with the SDK handshake; stream live updates via `sse_response`/`subscribeSSE`;
place high-frequency mutations without per-call audit rows or global-limiter throttling; run a
`tasks.loop` worker cog using `services.db`; and render a palette/enum/bounded-number settings form —
all passing `scripts/plugin_validate.py`.

---

## 11. Appendix — `place` feature → coverage map

| `place` feature | Coverage |
|---|---|
| `/place`, `/leaderboard`, `/mystats` slash commands | Supported (cog) |
| `/place-admin set-activity-channel` / `set-activity-interval` | Supported (cog) |
| `on_message` points earning | Supported (cog) — writes via the bot worker DB session (§7) or backend HTTP |
| Admin settings form / snapshot gallery / heatmap | Supported (dashboard page L4/L5 + `get_guild_db` API) |
| Public canvas / leaderboard / progress GIF (no login) | Supported (L0/L1 per-guild public page, §3) |
| Pretty slug URLs | Optional framework add (§3) — not required |
| Discord Activity interactive canvas | §4 — Gap A |
| Live SSE pixel stream | §5 — Gap B |
| High-frequency pixel placement | §6 — Gap C (rate limits + audit volume) |
| Void tick worker | §7 — Gap D |
| Canvas snapshot worker | §7 — Gap D |
| Points flush / decay / snapshot workers | §7 — Gap D |
| Activity-channel stream worker | §7 — Gap D |
| 16-color palette / canvas dims / gate-mode settings | §8 — Gap E |
| Models + migration | Supported\* (§9 adjustments) |
