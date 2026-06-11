# 08 — Plugin Staging Workflow

This guide explains how to develop, validate, and install a plugin using the staging toolchain. The **Event Logging** plugin (`plugins/event_logging/`) is used as the worked example throughout.

---

## Overview

All new functionality is developed as a **plugin** in a staging folder rather than editing the live project directly. This keeps speculative or LLM-generated code isolated until it is verified to meet framework contracts.

```
plugins/<plugin_name>/   ← develop here
        ↓
scripts/plugin_validate.py   ← machine-checks all framework rules
        ↓
scripts/plugin_install.py    ← copies files + patches project
```

---

## Step 0 — Prepare the Staging Folder

Copy the blank template and rename it for your plugin:

```bash
cp -r plugins/_template plugins/my_feature
```

Update `plugins/my_feature/plugin.json` with the plugin name, description, permission level, and which components (`cog`, `api`, `frontend`, `translations`, etc.) it includes. Only declare components you actually build.

**`plugin.json` reference:**

```json
{
  "name": "event_logging",
  "display_name": "Event Logging",
  "version": "1.0.0",
  "description": "Logs guild events to a designated channel.",
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
    "tag": "event_logging"
  },
  "navigation": {
    "enabled": true,
    "icon": "FileText",
    "color": "text-amber-400",
    "bg_color": "bg-amber-500/10",
    "border_color": "group-hover:border-amber-500/50"
  }
}
```

---

## Step 1 — Build the Plugin (manually or with an LLM)

Each component lives in its own file inside the staging folder. The installer knows where to put each one based on `plugin.json`.

### `cog.py` → `bot/cogs/<name>.py`

The bot's event/command logic. Key rules:

- Inherit from `commands.Cog`
- Use `bot.services.llm` for inference (never instantiate your own client)
- Use `bot.session` for HTTP requests (never create a new `aiohttp.ClientSession`)
- Declare `SETTINGS_SCHEMA` if the cog reads guild settings
- Include `async def setup(bot)` at the end

```python
class EventLoggingCog(commands.Cog):
    SETTINGS_SCHEMA = {
        "id": "event_logging",
        "label": "Event Logging",
        "fields": [
            {"key": "logging_enabled", "type": "boolean", "label": "Enable", "default": False},
            {"key": "logging_channel_id", "type": "channel_select", "label": "Log Channel"},
        ],
    }

    def __init__(self, bot):
        self.bot = bot

    async def _get_settings(self, guild_id):
        async with self.bot.session.get(
            f"http://backend:8000/api/v1/guilds/{guild_id}/settings",
            headers={"Authorization": f"Bot {self.bot.services.config.DISCORD_BOT_TOKEN}"},
        ) as resp:
            return (await resp.json()).get("settings", {}) if resp.status == 200 else {}

async def setup(bot):
    await bot.add_cog(EventLoggingCog(bot))
```

> The `SETTINGS_SCHEMA` is the only thing needed to get a settings form in the dashboard — no frontend code required for simple configuration.

**`SETTINGS_SCHEMA` required structure:**

```python
SETTINGS_SCHEMA = {
    "id": "my_plugin",       # REQUIRED — must be a unique snake_case identifier
    "label": "My Plugin",    # REQUIRED — displayed as the section heading
    "fields": [              # REQUIRED — list of field dicts (may be empty)
        {
            "key":     "field_name",   # snake_case key stored in guild settings JSON
            "type":    "boolean",      # see valid types below
            "label":   "Display Name", # shown next to the input
            "default": False,          # optional — used when key is absent
        },
    ],
}
```

**Valid `type` values — only these are supported:**

| Type | Renders as |
|---|---|
| `boolean` | Toggle switch (on/off) |
| `text` | Single-line text input |
| `number` | Numeric input |
| `channel_select` | Dropdown of the guild's channels (auto-populated) |
| `role_select` | Dropdown of the guild's roles (auto-populated) |
| `multiselect` | Multi-value selection list (requires `choices`) |

> `channel_select` and `role_select` are populated automatically from the Discord API — do not add a `choices` list to them.

> **Common mistakes the validator will reject:**
> - `"integer"` → use `"number"`
> - `"string"` → use `"text"`
> - `"bool"` → use `"boolean"`
> - `"select"` → use `"multiselect"` (with a `choices` list)
> - Missing `"id"`, `"label"`, or `"fields"` keys at the top level

### `api.py` → `backend/app/api/<name>.py`

REST endpoints for reading/writing plugin data. Key rules:

- Use `Depends(get_guild_db)` on **every** endpoint that has `{guild_id}` in the path (enforces Row-Level Security)
- Write an `AuditLog` entry in every POST / PUT / PATCH / DELETE handler
- `router = APIRouter()` must be defined at the top

```python
router = APIRouter()

@router.get("/{guild_id}/event-logging/settings")
async def get_settings(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),           # RLS enforced
    current_user: User = Depends(require_permission(PermissionLevel.AUTHORIZED)),
):
    ...

@router.post("/{guild_id}/event-logging/settings")
async def update_settings(
    guild_id: int,
    payload: EventLoggingSettings,
    db: AsyncSession = Depends(get_guild_db),
    current_user: User = Depends(require_permission(PermissionLevel.AUTHORIZED)),
):
    # ... persist ...
    db.add(AuditLog(guild_id=guild_id, user_id=current_user.id,
                    action="event_logging.settings.update", details=payload.model_dump()))
    await db.commit()
```

### `page.tsx` → `frontend/app/dashboard/[guildId]/<name>/page.tsx`

The dashboard page. Key rules:

- Export as `withPermission(PageComponent, PermissionLevel.X)` — bare `export default` is forbidden
- Use `useTranslation()` for all user-visible strings — no hardcoded English text
- Use Tailwind semantic tokens for all colors (`bg-card`, `text-foreground`, `border-border`, etc.) — no hex or rgb values

```tsx
function EventLoggingPage({ params }: Props) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <h1 className="text-foreground">{t('eventLogging.title')}</h1>
    </div>
  );
}

export default withPermission(EventLoggingPage, PermissionLevel.AUTHORIZED);
```

### `translations/en.ts` and `translations/es.ts`

These files contain **only the namespace block** — not a full file. The installer merges them into the project translation files before the closing `} as const;`.

```typescript
// translations/en.ts
eventLogging: {
  title: 'Event Logging',
  description: 'Monitor and configure guild event logging.',
},
```

```typescript
// translations/es.ts  — must mirror en.ts exactly
eventLogging: {
  title: 'Registro de Eventos',
  description: 'Monitorea y configura el registro de eventos del servidor.',
},
```

---

## Step 2 — Validate and Install

```bash
# Preview what will happen (no files written)
./install_plugin.sh event_logging --dry-run

# Install for real (validator runs first, aborts on any error)
./install_plugin.sh event_logging
```

The validator checks all framework contracts before any file is touched. If there are errors, fix them in the staging folder and re-run.

**Example validator output (clean):**

```
Validating plugin: event_logging
==================================================

[plugin.json]
  [OK]    Folder name matches plugin name: 'event_logging'
  [OK]    Version: 1.0.0
  [OK]    plugin.json is valid

[cog.py]
  [OK]    Cog class(es): EventLoggingCog
  [OK]    SETTINGS_SCHEMA declared
  [OK]    setup() entrypoint present

[api.py]
  [OK]    APIRouter instance defined
  [OK]    2 guild-scoped route(s) use get_guild_db
  [OK]    Mutation endpoint 'update_settings' writes AuditLog

[page.tsx]
  [OK]    withPermission export present
  [OK]    useTranslation() used
  [OK]    No hardcoded colors detected

[translations/]
  [OK]    Namespace 'eventLogging' in en.ts
  [OK]    Namespace 'eventLogging' in es.ts
  [OK]    en.ts and es.ts keys match

==================================================
Results: 0 error(s), 0 warning(s)

Validation PASSED — plugin is ready to install
```

Pass `--strict` to promote warnings to errors (useful in CI):

```bash
./install_plugin.sh event_logging --strict
```

---

## Step 3 — What the Installer Does

**What the installer does automatically:**

| Action | Result |
|---|---|
| Copies `cog.py` | `bot/cogs/event_logging.py` |
| Copies `api.py` | `backend/app/api/event_logging.py` |
| Updates `backend/installed_plugins.json` | Registers the plugin name, router prefix, and tag — auto-discovered by `plugin_loader.py` at startup |
| Appends `models.py` | Appends model classes to `backend/app/models.py` |
| Copies `migration.py` | `backend/alembic/versions/<timestamp>_event_logging.py` |
| Writes `migration_inventory.json` | Registers plugin name, version, and revision ID — no manual edits needed |
| Copies `page.tsx` | `frontend/app/dashboard/[guildId]/event_logging/page.tsx` (dir created) |
| Inserts nav card | Patches `frontend/app/page.tsx` with the card object + icon import |
| Merges `translations/en.ts` | Injects `eventLogging: { ... }` into `frontend/lib/i18n/translations/en.ts` |
| Merges `translations/es.ts` | Same for Spanish |

> The nav card is auto-inserted using an anchor comment in `page.tsx`. If the anchor is missing the installer prints the card object to paste manually.

---

## Step 4 — Restart Services

```bash
docker compose restart backend bot frontend
```

`backend` must restart to reload `migration_inventory.json` (loaded once at startup by `version.py`). The bot will pick up the new cog, introspect its `SETTINGS_SCHEMA`, and sync the settings form to the database. The frontend will show the new dashboard page.

If your plugin defines slash commands, they will appear automatically in the **Command Reference** page after restart. Click **Refresh from Cogs** on that page to update the cached list — the data comes from the bot's live introspection report, not from Discord's API.

---

## Step 5 — Apply the Database Migration (if plugin has tables)

Open the **DB Management** page. The plugin migration will appear in the plugin section. Click **Apply** — same as you would for a framework migration.

The installer already handled everything else:
- Copied the migration file to `backend/alembic/versions/`
- Wrote the plugin entry to `backend/migration_inventory.json`

> **Never edit `version.py`** — it is pure logic and contains no hardcoded data.
> All version data lives in `backend/migration_inventory.json`.
> For framework releases (not plugin work), a developer bumps `framework_version` and appends to `framework_migrations` in that JSON file.

---

## Prompting an LLM to Build a Plugin

When asking Claude (or any LLM) to generate a plugin, provide this context:

1. **`CLAUDE.md`** — the five golden rules, file locations, and the authoritative `SETTINGS_SCHEMA` reference (Golden Rule 4)
2. **This file** (`docs/integration/08-plugin-workflow.md`) — the step-by-step guide for each component
3. **`plugins/_template/`** — the blank template as a structural reference
4. **The staging target path** — `plugins/<plugin_name>/`
5. **The functional requirements** — what the plugin should do

> **Do not** include `docs/PLUGIN_SYSTEM_SPECS.md` in the LLM context as a substitute for the above — it is an architectural overview document, not a build guide, and overlaps with `CLAUDE.md` in ways that can cause contradictions.

Example prompt pattern:

```
Using the Baseline framework (see CLAUDE.md and docs/integration/08-plugin-workflow.md),
build a complete plugin in plugins/welcome_message/ that:
- Sends a configurable welcome DM when a member joins the server
- Has a settings form for the message text and an enable/disable toggle
- Has a dashboard page showing recent welcome events

Follow all five golden rules. Produce plugin.json, cog.py, api.py, page.tsx,
and translations/en.ts + es.ts.
```

After generation, always run `plugin_validate.py` before installing.

---

## Multi-Page Plugins

A plugin can expose multiple dashboard pages at different permission levels — for example, a user-facing view at **AUTHORIZED (3)** and an admin management view at **ADMINISTRATOR (4)** — by replacing the single `navigation` object with a `pages` array in `plugin.json`.

### `plugin.json` — `pages` array format

```json
{
  "name": "tickets",
  "display_name": "Tickets",
  "version": "1.0.0",
  "description": "Support ticket system.",
  "permission_level": 3,
  "components": {
    "cog": true,
    "api": true,
    "frontend": true,
    "translations": true
  },
  "router": { "prefix": "/guilds", "tag": "tickets" },
  "pages": [
    {
      "id": "tickets",
      "source": "page.tsx",
      "path": "tickets",
      "permission_level": 3,
      "navigation": {
        "enabled": true,
        "icon": "Ticket",
        "color": "text-blue-500",
        "bg_color": "bg-blue-500/10",
        "border_color": "group-hover:border-blue-500/50"
      }
    },
    {
      "id": "tickets_admin",
      "source": "page_admin.tsx",
      "path": "tickets/admin",
      "permission_level": 4,
      "navigation": {
        "enabled": true,
        "icon": "ShieldCheck",
        "color": "text-purple-500",
        "bg_color": "bg-purple-500/10",
        "border_color": "group-hover:border-purple-500/50"
      }
    }
  ]
}
```

Each entry in `pages` requires:

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Unique snake_case identifier — used as the nav card `id` and as the translation key base |
| `source` | Yes | Source file in the plugin staging folder (e.g. `page.tsx`, `page_admin.tsx`) |
| `path` | Yes | Install path relative to `dashboard/[guildId]/` — determines the URL |
| `permission_level` | No | Overrides the plugin-level `permission_level` for this page; defaults to the plugin level if omitted |
| `navigation.enabled` | No | Set to `false` to install the page without a nav card (e.g. a detail page linked from another page) |
| `navigation.icon` | No | Lucide icon name; defaults to `"Settings"` |
| `navigation.color` etc. | No | Same styling fields as the single-page `navigation` object |

### Staging folder layout

```
plugins/tickets/
  plugin.json
  cog.py
  api.py
  page.tsx          ← AUTHORIZED view (level 3) — id: "tickets"
  page_admin.tsx    ← ADMINISTRATOR view (level 4) — id: "tickets_admin"
  translations/
    en.ts
    es.ts
```

### Translation keys

Each page's nav card uses `t('{camelCaseId}.title')` and `t('{camelCaseId}.description')` where `camelCaseId` is the camelCase version of the page's `id`. Include keys for every page in `translations/en.ts` and `es.ts`:

```typescript
// translations/en.ts
tickets: {
  title: 'Tickets',
  description: 'Browse and manage your support tickets.',
  // ... other tickets page strings
},
ticketsAdmin: {
  title: 'Ticket Admin',
  description: 'Manage ticket categories and assignments.',
  // ... other admin page strings
},
```

### What the installer does

For each entry in `pages`, the installer:
1. Copies `source` → `frontend/app/dashboard/[guildId]/{path}/page.tsx`
2. Inserts a nav card into `frontend/app/page.tsx` at the correct permission level
3. Adds the page's icon to the lucide-react import (if not already present)

Both pages appear as separate cards on the dashboard home, grouped under their respective permission-level sections. A user with AUTHORIZED access sees the `tickets` card; only those with ADMINISTRATOR access also see `tickets_admin`.

### Backward compatibility

The single-page `navigation` format still works — if your `plugin.json` has no `pages` array, the installer uses `navigation` as before. You only need `pages` when you want more than one page.

---

## Common Validation Errors and Fixes

| Error | Fix |
|---|---|
| `@app_commands.command 'foo' missing description=` | Add `description="..."` to the decorator |
| `Direct openai.OpenAI()` | Replace with `self.bot.services.llm` |
| `Direct aiohttp.ClientSession()` | Replace with `async with self.bot.session.get(...)` |
| `guild-scoped route(s) but get_guild_db not used` | Add `db: AsyncSession = Depends(get_guild_db)` to the route |
| `Mutation endpoint 'X' has no AuditLog` | Add `db.add(AuditLog(...))` before `db.commit()` |
| `Page not wrapped with withPermission()` | Change `export default function Page` to `export default withPermission(Page, PermissionLevel.X)` |
| `Hardcoded hex color in className` | Replace `#3b82f6` with `text-primary` or other semantic token |
| `translations/es.ts missing` | Create the file mirroring `en.ts` with translated values |
| `Non-idempotent CREATE TYPE detected` | Wrap enum creation in a `DO $$ BEGIN IF NOT EXISTS ... END $$;` guard (see below) |
| `SETTINGS_SCHEMA field type 'integer'` | Use `"number"` — valid types: `boolean`, `text`, `number`, `channel_select`, `role_select`, `multiselect` |
| `SETTINGS_SCHEMA field type 'string'` | Use `"text"` — `"string"` is not a valid field type |
| `SETTINGS_SCHEMA missing required key 'id'` | Top-level schema must have `"id"`, `"label"`, and `"fields"` keys |
| `apiClient path starts with /api/` | Remove the prefix — `apiClient` base URL already includes `/api/v1`. Use `/guilds/${guildId}/...` |

### Safe CREATE TYPE pattern

`CREATE TYPE ... AS ENUM` fails on retry if the type already exists (e.g. after a partial migration). Always guard it:

```python
def upgrade():
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ticketstatus') THEN
                CREATE TYPE ticketstatus AS ENUM ('OPEN', 'CLOSED');
            END IF;
        END $$;
    """)
    op.create_table('tickets', ...)

def downgrade():
    op.drop_table('tickets')
    op.execute("DROP TYPE IF EXISTS ticketstatus")
```

The validator rejects any `CREATE TYPE ... AS ENUM` not wrapped in a `DO $$` or `IF NOT EXISTS` guard.

---

## Related Documentation

- `docs/PLUGIN_SYSTEM_SPECS.md` — specs for all three plugin layers
- `docs/SECURITY.md` — full permission level reference
- `docs/integration/01-adding-cogs.md` — cog patterns in depth
- `docs/integration/04-backend-endpoints.md` — API router patterns
- `docs/integration/05-frontend-pages.md` — frontend page patterns
- `plugins/event_logging/` — complete worked example (all files pass the validator)
- `plugins/_template/` — blank template to copy for new plugins
