# Plugin Staging Area

This directory is the **staging zone** for new plugins before they are installed into the live project.

## Workflow

```
plugins/<plugin_name>/   ← LLM or developer builds here
        ↓
scripts/plugin_validate.py plugins/<plugin_name>   ← checks all framework contracts
        ↓
scripts/plugin_install.py plugins/<plugin_name>    ← copies files + patches project
```

## Staging Folder Structure

```
plugins/
  <plugin_name>/
    plugin.json           ← required manifest
    cog.py                → bot/cogs/<plugin_name>.py
    api.py                → backend/app/api/<plugin_name>.py
    models.py             → appended to backend/app/models.py
    migration.py          → backend/alembic/versions/<ts>_<plugin_name>.py
    page.tsx              → frontend/app/dashboard/[guildId]/<plugin_name>/page.tsx
    translations/
      en.ts               → merged into frontend/lib/i18n/translations/en.ts
      es.ts               → merged into frontend/lib/i18n/translations/es.ts
```

Not every component is required. Declare only what the plugin uses in `plugin.json`.

### Rich-app extensions

For real-time / partly-public / Activity-based apps, see **`plugins/rich_demo/`** — a reference
plugin that exercises every rich-app capability and passes the validator:

| Capability | Manifest | Installed to | Backend / client helper |
|---|---|---|---|
| Public per-server site (Level 0) | `public_pages` | `frontend/app/(public)/p/[slug]/<path>` | `get_public_guild_db` + `withPublicPage` |
| Discord Activity | `activity_pages` | `frontend/app/activity/<path>` | `POST /auth/activity` + `get_activity_user` + `withActivityPage` |
| Real-time updates (SSE) | `capabilities: ["sse"]` | — | `sse_response`/`redis_stream_source` ↔ `subscribeSSE` |
| Audit-exempt mutations | `router.audit_exempt_paths` | — | skipped by `GuildAuditMiddleware` |
| Worker cog (scheduled DB work) | `worker: true` | `bot/cogs/<name>.py` | `bot.services.db.worker_session()` |
| Rich settings | `SETTINGS_SCHEMA` | — | `color` / `color_list` / `select` / bounded `number` |

See **CLAUDE.md → "Rich-App Extensions"** for the full rules.

## plugin.json Reference

```json
{
  "name": "my_plugin",
  "display_name": "My Plugin",
  "version": "1.0.0",
  "description": "Short description shown in docs",
  "permission_level": 3,
  "components": {
    "cog": true,
    "api": true,
    "models": false,
    "migration": false,
    "frontend": true,
    "translations": true
  },
  "router": {
    "prefix": "/guilds",
    "tag": "my_plugin"
  },
  "navigation": {
    "enabled": true,
    "icon": "Settings",
    "color": "text-blue-500",
    "bg_color": "bg-blue-500/10",
    "border_color": "group-hover:border-blue-500/50"
  }
}
```

**`permission_level`** maps to the 6 framework security levels:
| Level | Name | Who |
|---|---|---|
| 0 | PUBLIC | Anyone |
| 1 | PUBLIC_DATA | Authenticated users |
| 2 | USER | Guild members |
| 3 | AUTHORIZED | Guild admins |
| 4 | OWNER | Guild owner |
| 5 | DEVELOPER | Platform admin |

## Translation Snippets

`translations/en.ts` and `es.ts` contain **only the namespace block** for this plugin — not a full file. The installer merges them into the project translation files.

```typescript
// translations/en.ts  — just the namespace object, no export statement
myPlugin: {
  title: 'My Plugin',
  description: 'What this plugin does',
  someAction: 'Do the thing',
},
```

```typescript
// translations/es.ts  — must mirror en.ts exactly
myPlugin: {
  title: 'Mi Plugin',
  description: 'Lo que hace este plugin',
  someAction: 'Hacer la cosa',
},
```

## Prompting the LLM

When asking Claude (or any LLM) to build a plugin, provide:

1. The `docs/PLUGIN_SYSTEM_SPECS.md` and `CLAUDE.md` as context
2. The target staging path: `plugins/<plugin_name>/`
3. The plugin's functional requirements

The LLM should produce all declared files conforming to the framework contracts.
After generation, run the validator before installing.

## Validation Checks

The validator enforces:

| Layer | Rule |
|---|---|
| Cog | Inherits `commands.Cog` |
| Cog | `description=` on every `@app_commands.command()` |
| Cog | No direct LLM client instantiation (must use `bot.services.llm`) |
| Cog | No `aiohttp.ClientSession()` (must use `bot.session`) |
| Cog | `SETTINGS_SCHEMA` present if reading guild settings |
| API | `get_guild_db` used for all `{guild_id}` routes |
| API | `AuditLog` written in every POST/PUT/PATCH/DELETE handler |
| Frontend | `withPermission()` export |
| Frontend | `useTranslation()` used — no hardcoded strings |
| Frontend | No hardcoded hex/rgb colors |
| i18n | Both `en.ts` and `es.ts` present and namespace keys match |

## After Install — Manual Steps

The installer handles file placement and `main.py` router registration automatically.
Two things always require a manual step:

1. **Database migrations** — run `cd backend && alembic upgrade head`
2. **Navigation card** — add an entry to the `cards` array in `frontend/app/page.tsx`
   (the installer prints the exact object to paste)

## Available Plugins

| Folder | What it does | Install method |
|---|---|---|
| `event_logging/` | Logs guild events (message delete/edit, member join/leave) to a configurable channel. Cog + dashboard settings page. Worked example from the plugin workflow guide. | Standard — `plugin_install.py` |
| `gemini_demo/` | Full Gemini API demo suite: text generation with thinking, image gen, vision, TTS, audio, embeddings, function calling, URL context, caching, RAG. | Manual — see `gemini_demo/plugin.json` for instructions |
| `test_pages/` | Two minimal pages for verifying L1 and L2 permission enforcement during development. | Manual — copy files, see `test_pages/plugin.json` |
| `_template/` | Blank template to copy when starting a new plugin. | — |

Demo plugins are **not installed by default**. To deploy one into the live project, follow the standard plugin workflow:

```bash
./install_plugin.sh <name>
```

For plugins with `"install_mode": "manual"` in their `plugin.json`, follow the instructions in that file instead.

## Using `_template`

Copy `plugins/_template/` to `plugins/<your_plugin_name>/` as a starting point.
