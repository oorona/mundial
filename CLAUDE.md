# CLAUDE.md — Baseline Framework Quick Reference

This file is the first thing AI coding assistants should read. It contains the essential rules for extending this framework correctly.

## What This Is

A **framework** for building Discord bots with web dashboards. You extend it by adding cogs, API routes, frontend pages, and migrations. **You never modify core infrastructure files.**

## Four Golden Rules

Every piece of code you generate must follow all four of these rules:

1. **`bot.services.llm`** — the LLM service is always accessed as `bot.services.llm` (never `bot.llm_service` or any other path)
2. **`get_guild_db` for guild data** — endpoints that touch guild-scoped tables use `Depends(get_guild_db)`, not `Depends(get_db)`. Using `get_db` silently bypasses Row-Level Security and can leak cross-guild data
3. **`withPermission` on every frontend page** — every `page.tsx` under `dashboard/` must be exported as `withPermission(Page, PermissionLevel.X)`. A bare `export default function` has no auth guard and no breadcrumb
4. **`SETTINGS_SCHEMA` for configurable cogs** — any cog that reads guild settings declares a `SETTINGS_SCHEMA` class attribute; the dashboard Settings page renders the form automatically with no frontend code needed. The schema **must** use the nested structure below — a flat dict of field names is invalid and will be rejected by the validator:

```python
SETTINGS_SCHEMA = {
    "id": "my_plugin",          # unique snake_case identifier
    "label": "My Plugin",       # display name in dashboard
    "description": "...",       # optional subtitle
    "fields": [
        {"key": "enabled",    "type": "boolean",        "label": "Enable",          "default": True},
        {"key": "channel_id", "type": "channel_select", "label": "Channel",         "default": None},
        {"key": "role_id",    "type": "role_select",    "label": "Role",            "default": None},
        {"key": "prefix",     "type": "text",           "label": "Prefix",          "default": "!"},
        {"key": "limit",      "type": "number",         "label": "Max Items",       "default": 10},
        {"key": "modes",      "type": "multiselect",    "label": "Modes",           "default": [],
         "choices": [{"value": "a", "label": "Mode A"}, {"value": "b", "label": "Mode B"}]},
    ],
}
```

Valid `"type"` values: `"boolean"`, `"text"`, `"number"` (optionally with `min`/`max`/`step`), `"channel_select"`, `"role_select"`, `"multiselect"`, `"select"` (single-choice enum, with `choices`), `"color"` (single hex), `"color_list"` (ordered palette, with `count`). **Never use** `"string"` or `"integer"` — the validator will reject them. `channel_select` and `role_select` dropdowns are populated automatically from the Discord API; you do not provide `choices` for them.

> **Audit logging is automatic.** The `GuildAuditMiddleware` in `backend/main.py` writes an `AuditLog` row for every successful POST/PUT/PATCH/DELETE on `/{guild_id}/` routes. Plugin endpoints **must not** add `db.add(AuditLog(...))` — doing so produces duplicate entries and creates FK risk for cross-guild operations. **Exemption (high-frequency routes):** a route that mutates on every interaction (e.g. one row per pixel) would emit one audit row per call. Declare such routes under `router.audit_exempt_paths` in `plugin.json` (e.g. `"audit_exempt_paths": ["/{guild_id}/place"]`) — the middleware then skips them. Routes mounted outside `/{guild_id}/` (e.g. an `/activity` prefix) are never audited.

> **`LLMService.chat()` has no `system_prompt` parameter.** For LLM calls that need a custom system prompt, use `provider.generate_response()` directly (stateless). Use `chat()` only for multi-turn conversations without a custom system prompt.

## Plugin Prompt Files

Any plugin that makes LLM calls with a custom prompt **must** use the prompt file system. Prompts are organized by **context** — a folder named after the purpose (`ticket_intake`, `faq_answers`, `dm_support`). Each context holds its own `system_prompt.txt`, `user_prompt.txt`, and any other files the plugin needs. Admins edit these from the dashboard without restarting.

**Declare in `plugin.json`:**

```json
{
  "components": { "prompts": true },
  "prompts": [
    {
      "context": "ticket_intake",
      "label": "Ticket Intake",
      "description": "Handles DM messages when a user opens a ticket.",
      "files": [
        {
          "name": "system_prompt",
          "label": "System Prompt",
          "description": "AI persona for ticket intake.",
          "default": "You are a helpful ticket assistant."
        },
        {
          "name": "user_prompt",
          "label": "User Prompt Template",
          "description": "Template for each user message. Use {message} and {username}.",
          "default": "{message}"
        }
      ]
    }
  ]
}
```

**Provide source files** in `plugins/{name}/prompts/{context}/{file_name}.txt` — the installer copies them to `/data/prompts/{plugin_name}/{context}/`. The `"default"` string is used if no source file exists.

**Load in a cog:**

```python
system = self.llm.load_prompt("my_plugin", "ticket_intake", "system_prompt")
user_tmpl = self.llm.load_prompt("my_plugin", "ticket_intake", "user_prompt")

formatted = (user_tmpl or "{message}").format(message=query, username=user.display_name)

provider = self.llm.providers.get("google") or next(iter(self.llm.providers.values()))
from bot.services.llm import LLMMessage
response = await provider.generate_response(
    [LLMMessage(role="user", content=formatted)],
    system_prompt=system or "You are a helpful assistant.",
)
```

`load_prompt()` returns `""` if the file is missing — **always supply a fallback**. Files live at `./data/prompts/{plugin_name}/{context}/{file_name}.txt` on the host. Admins edit them in **LLM Configs → Plugin Prompts** (Developer access).

## Rich-App Extensions (public sites, Activities, SSE, workers, rich settings)

Beyond the basic cog/API/page model, the framework supports "rich apps" (real-time,
partly-public, Activity-based apps with scheduled work). The `plugins/rich_demo` reference
plugin exercises all of these and passes the validator.

**Public site surface (Level 0).** Every guild has a globally-unique `slug` (on the framework
`Guild` model, auto-assigned on join). Public per-server sites live at a configurable prefix
(default `/p/<slug>`); the generic project landing page is at `/p`. A plugin serves public,
no-login per-server pages by:
- declaring them under `"public_pages": [{ "source": "public.tsx", "path": "..." }]` — the
  installer copies them to `frontend/app/(public)/p/[slug]/<path>/page.tsx`. Export them with
  `withPublicPage(Page)` (NOT `withPermission`).
- backing them with API routes that depend on `get_public_guild_db` (from
  `app.db.guild_session`): it resolves the slug RLS-bypassed, 404s on miss, then yields an
  RLS-active session scoped to that guild. Use it for any `/{slug}` route.
- Guild admins rename their slug from the dashboard Settings page (`PUT /guilds/{id}/slug`).

**Discord Activity (Embedded App SDK).** Declare `"activity_pages": [{ "source": "activity.tsx",
"path": "..." }]` → installed to `frontend/app/activity/<path>/page.tsx` (full-bleed, no
`withPermission`; export with `withActivityPage(Page)`). Authenticate with the SDK then call
`authenticateActivity(code, guildId)` (`frontend/lib/activity.ts`) → `POST /auth/activity`, which
re-verifies guild membership with the bot token and mints an `activity_session`. Activity API
routes depend on `get_activity_user` (from `app.api.deps`), not `get_current_user`. The
`/activity` route group gets a `frame-ancestors https://discord.com` CSP from `next.config`.
> **Activity gotchas (do NOT regress — see `docs/DISCORD_APP_SETUP.md` §6):** (1) build a
> **single-page** activity and switch screens with view state / a tab bar — never navigate
> between `/activity/*` pages (the SDK handshake works only on the first page and the token
> won't survive navigation → "works once then 401"); (2) hold the token **in memory**
> (`setAuthToken` in `api-client.ts`), NOT in `localStorage` (partitioned inside the iframe),
> and don't let the 401/403 interceptor redirect/clear on `/activity/*`; (3) `next.config`
> serves `/activity/*` with `Cache-Control: no-store` — without it Next's 1-year `s-maxage`
> makes Discord cache the old bundle forever. Set `NEXT_PUBLIC_DISCORD_CLIENT_ID` at build time.

**Real-time (SSE).** The only sanctioned streaming path: backend routes return
`sse_response(async_gen)` (from `app.core.streaming`; use `redis_stream_source(...)` to tail a
Redis stream); the client subscribes with `subscribeSSE(path, onEvent)` (from
`frontend/lib/streaming.ts`). Do not hand-roll `EventSource`.

**Worker cogs (scheduled DB work).** Set `"worker": true` in `plugin.json`. A `tasks.loop` cog
reads/writes Postgres via `self.bot.services.db` — `worker_session()` (RLS bypassed, cross-guild)
or `scoped_session(guild_id)` (RLS active). **Single-writer rule:** the bot is one
`AutoShardedBot` process — never scale it to multiple processes.

**Rich settings.** `SETTINGS_SCHEMA` field types now also include `color`, `color_list` (with
`count`), and `select` (single-choice enum, with `choices`), plus `min`/`max`/`step` on `number`.
The dashboard auto-renders them; no frontend code needed.

## How to Build a Feature (Plugin Workflow)

**Never write feature code directly into the live project.** Use the plugin staging system:

```bash
cp -r plugins/_template plugins/<name>   # start from the template
# ... build cog.py, api.py, page.tsx, translations/ inside plugins/<name>/
./install_plugin.sh <name>               # validates then installs into live project
```

The validator enforces all five golden rules automatically and will reject code that violates them. See `docs/integration/08-plugin-workflow.md` for the full guide.

**If you are about to edit a file in `bot/core/`, `backend/app/api/auth.py`, `backend/app/api/deps.py`, `frontend/lib/auth-context.tsx`, or any existing migration — stop.** These files are write-protected after `init.sh`. Everything you need can be built within the extension points below.

## Core vs User Code

| Never touch (core) | Safe to extend |
|---|---|
| `bot/core/bot.py` | `bot/cogs/*.py` — add cogs here |
| `bot/core/loader.py` | `bot/services/*.py` — add services here |
| `backend/app/api/auth.py` | `backend/app/api/*.py` — add new router files |
| `backend/app/api/deps.py` | `backend/app/models.py` — append new models |
| `frontend/lib/auth-context.tsx` | `frontend/app/dashboard/[guildId]/*` — add pages |
| `frontend/app/layout.tsx` | `frontend/lib/i18n/translations/` — add strings |
| `backend/alembic/versions/*.py` (existing) | `backend/alembic/versions/` — add new migration files |

## Key File Locations

| What | Where |
|---|---|
| Bot commands (cogs) | `bot/cogs/<feature>.py` |
| Backend API router | `backend/app/api/<feature>.py` |
| Register backend router | `backend/main.py` — add `from app.api.<feature> import router as <feature>_router` + `app.include_router(...)` |
| Frontend dashboard page | `frontend/app/dashboard/[guildId]/<feature>/page.tsx` |
| Navigation cards (dashboard home) | `frontend/app/page.tsx` |
| DB models | `backend/app/models.py` |
| DB migration | `backend/alembic/versions/` (auto-generate: `alembic revision --autogenerate -m "desc"`) |
| Framework version & changelog | `backend/app/core/version.py` |
| i18n strings | `frontend/lib/i18n/translations/en.ts` **AND** `es.ts` |
| Plugin prompt files (host) | `./data/prompts/{plugin_name}/{context}/{file_name}.txt` — bind-mounted at `/data/prompts/` in containers |

## Mandatory Checklist for Every New Feature

- [ ] **Cog**: `description=` on every `@app_commands.command()` — never omit it
- [ ] **Cog**: `SETTINGS_SCHEMA` if the cog reads from guild settings
- [ ] **Cog**: use `self.llm.load_prompt(plugin_name, context, file_name)` + `provider.generate_response()` for LLM calls that need a custom system prompt — never pass `system_prompt` to `chat()`
- [ ] **Backend**: use `Depends(get_guild_db)` for any endpoint under `/{guild_id}/`
- [ ] **Backend**: import and register the new router in `backend/main.py`
- [ ] **Backend**: do NOT add `db.add(AuditLog(...))` — audit logging is automatic via `GuildAuditMiddleware`
- [ ] **Frontend**: export page as `withPermission(Page, PermissionLevel.X)`
- [ ] **Frontend**: add a navigation card in `frontend/app/page.tsx` if the feature needs its own page
- [ ] **i18n**: add all user-visible strings to `en.ts` **and** `es.ts` — never hardcode text
- [ ] **Prompts**: if the plugin makes LLM calls with a custom prompt, declare `"prompts": true` in `components` and add a `"prompts"` array in `plugin.json` — place default `.txt` files in `plugins/{name}/prompts/{context}/`
- [ ] **DB**: if adding tables, `alembic revision --autogenerate`, add RLS block if guild-scoped — `install_plugin.sh` writes the migration entry to `backend/migration_inventory.json` automatically; only manual step is `alembic upgrade head`

## Bot Service Access Patterns

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm          # LLM service (all providers)
        # bot.session is a shared aiohttp.ClientSession — use it for all HTTP calls
        # to the backend; do not create new sessions per-request

    async def _get_settings(self, guild_id: int) -> dict:
        """Standard pattern for fetching guild settings from backend."""
        async with self.bot.session.get(
            f"http://backend:8000/api/v1/guilds/{guild_id}/settings",
            headers={"Authorization": f"Bot {self.bot.services.config.DISCORD_BOT_TOKEN}"}
        ) as resp:
            if resp.status == 200:
                return (await resp.json()).get("settings", {})
        return {}
```

## Backend DB Session Quick Reference

```python
from app.db.guild_session import get_guild_db   # For /{guild_id}/ endpoints — RLS active
from app.db.guild_session import get_admin_db   # For L6 cross-guild endpoints — RLS bypassed
from app.db.session import get_db               # For global tables only (users, shards, etc.)
```

## i18n Quick Reference

Every user-visible string must go through the translation system:

```tsx
// In any 'use client' component:
const { t } = useTranslation();
<h1>{t('myFeature.title')}</h1>
<p>{t('myFeature.greeting', { username: user.username })}</p>

// Add to BOTH translation files:
// frontend/lib/i18n/translations/en.ts
myFeature: {
  title: 'My Feature',
  greeting: 'Hello, {username}!',
},

// frontend/lib/i18n/translations/es.ts  (must mirror en.ts exactly)
myFeature: {
  title: 'Mi Función',
  greeting: '¡Hola, {username}!',
},
```

## Registering a Backend Router in main.py

```python
# backend/main.py — add at the end of the router registration block:
from app.api.myfeature import router as myfeature_router
app.include_router(myfeature_router, prefix=f"{settings.API_V1_STR}/guilds", tags=["myfeature"])
```

## Authoritative Documentation (read in this order)

1. **`docs/DEVELOPER_MANUAL.md`** — architecture, security model, plugin workflow, DB extension guide
2. **`docs/LLM_USAGE_GUIDE.md`** — using the LLM service in cogs and the backend
3. **`docs/SECURITY.md`** — all 6 permission levels with complete code examples
4. **`docs/integration/`** — step-by-step guides for each extension point
5. **`docs/GEMINI_CAPABILITIES.md`** — Gemini advanced features (image gen, TTS, RAG, context caching)
