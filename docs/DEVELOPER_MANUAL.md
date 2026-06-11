# Baseline Framework: Developer & Agent Manual

## 1. Introduction
This documentation is the **authoritative source** for developers and AI Agents working on the Baseline Framework. It consolidates architecture, security, and plugin workflows.

> **This is a framework, not a finished bot.**
> The Baseline Framework provides the infrastructure that all bots built on it share: authentication, database access, encrypted secret management, permission enforcement, LLM integration, and the admin dashboard. You build your bot by **extending** the framework — adding cogs, API routes, frontend pages, and database migrations — without ever modifying the core.

### Core Philosophy
- **Core Framework** — The underlying "Operating System" (Auth, Database, Navigation, Layouts). **DO NOT MODIFY** unless fixing a confirmed framework bug. This code is shared by every bot built on this platform.
- **Sample/User Code** — The specific bot implementation. The current codebase contains **Sample Code** (e.g., `status.py`, `test-l1` pages) to demonstrate functionality. Replace or extend these with your own features.

### What "Extending the Framework" Means

| You extend by... | You never... |
| :--- | :--- |
| Adding new bot cogs in `bot/cogs/` | Modify `bot/core/bot.py` |
| Adding new API routers in `backend/app/api/` | Modify `backend/app/api/auth.py` or `deps.py` |
| Adding new pages in `frontend/app/dashboard/[guildId]/` | Modify `frontend/lib/auth-context.tsx` |
| Adding new Alembic migrations | Edit existing migration files |
| Appending entries to `framework_migrations` in `migration_inventory.json` | Edit `version.py` — it is read-only logic |
| Bumping `framework_version` in `migration_inventory.json` for schema changes | Hardcode anything in `version.py` |

---

## 2. Project Structure

| Component | Path | Description | Access |
| :--- | :--- | :--- | :--- |
| **Backend** | `backend/app/*` | FastAPI service, DB models, Auth. | **Core** |
| **Bot (Core)** | `bot/main.py`, `bot/cogs/guild_sync.py` | Discord.py startup, sharding, syncing. | **Core** |
| **Bot (Features)** | `bot/cogs/*.py` | Feature logic (e.g., Moderation, Music). | **User/Sample** |
| **Frontend (Core)** | `frontend/app/layout.tsx`, `frontend/lib/*` | Layouts, Auth Context, UI Components. | **Core** |
| **Frontend (Pages)** | `frontend/app/dashboard/*` | Dashboard pages. | **User/Sample** |

### Starting a New Bot from this Framework

After cloning the repository, run the initialiser script **once**:

```bash
chmod +x init.sh
./init.sh
```

This does two things:
1. **Removes all demo plugin folders** from `plugins/` — leaving only `_template/` and `README.md`
2. **Write-protects core framework files** (`chmod 444`) so accidental edits produce a permission error

After `init.sh` the project is blank. Build your own plugins from `plugins/_template/`.

> **`frontend/app/dashboard/[guildId]/settings/`** is a **core framework page** — it renders dynamically based on `SETTINGS_SCHEMA` declarations from loaded cogs. You do not need to modify it when adding new settings.

---

## 2.5 Secrets and Configuration (First-Time Setup)

> **No `.env` file.** The only secret that lives outside Docker is the encryption key, stored in `secrets/encryption_key` (never committed to git). Everything else — DB credentials, Discord token, API keys — is entered once through the browser Setup Wizard and stored encrypted on a Docker volume.

### How It Works

```
secrets/encryption_key   ←  created by ./setup_secrets.sh
        │
        └─► Docker secret (tmpfs, never on disk inside container)
                │
                └─► AES-256-GCM encryption key
                        │
                        └─► encrypts /data/settings.enc  (Docker named volume)
                                │
                                └─► DB host/user/password, Discord token, API keys
```

1. Run `./setup_secrets.sh` — generates a 256-bit encryption key in `secrets/encryption_key`.
2. Run `./setup_database.sh --user <name>` — creates the Postgres user and schema.
3. Run `docker compose up` — app starts in **wizard mode** (no DB connected yet).
4. Open the app in a browser — you are redirected to `/setup`.
5. Enter credentials in the wizard — they are encrypted with AES-256-GCM and saved to `/data/settings.enc`.
6. All subsequent starts decrypt the file automatically — wizard never runs again unless the file is deleted.

### Rules for Bot Developers

- **Never add secrets to `.env.example`** or any committed file.
- **Never read secrets with `os.getenv("DB_PASSWORD")` directly** — use `Depends(get_db)` for DB access and `settings.*` (the Pydantic `Settings` object populated from the encrypted file) for config values.
- **Never call `save_encrypted_settings()` from feature code** — only setup/wizard endpoints write to the encrypted file.
- If you need a new configurable secret (e.g., a third-party API key for your feature), add it to the wizard form, save it via the existing wizard endpoint, and read it from `settings.*` in your code.

---

## 2.6 LLM & AI Capabilities

The framework includes a multi-provider LLM service accessible to all bot cogs via `bot.services.llm`.

### Supported Providers

| Provider | Models |
|----------|--------|
| **Google Gemini** | Gemini 2.5 Pro/Flash, Gemini 2.0 Flash |
| **OpenAI** | GPT-4o, GPT-4 |
| **Anthropic** | Claude 3 Opus/Sonnet/Haiku |
| **xAI** | Grok |

### Quick Start with LLM

```python
# In your cog
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.llm = bot.services.llm

    @app_commands.command()
    async def ask(self, interaction, question: str):
        await interaction.response.defer()
        response = await self.llm.chat(message=question)
        await interaction.followup.send(response)
```

### Usage Tracking

All LLM calls are automatically recorded in the `llm_usage` table:
- Provider, model, capability type
- Token counts (prompt, completion, thinking, cached)
- Cost estimation
- Latency metrics
- Guild and user attribution

This data feeds the **AI Analytics** dashboard page (Level 4 — always present, not a demo).

See [LLM_USAGE_GUIDE.md](LLM_USAGE_GUIDE.md) for the full usage guide.

---

## 3. Security Architecture (Permission Levels)

The framework enforces a strict 7-tier security model. **All new pages and API endpoints MUST adhere to this.**

| Level | Name | Description | Example Usage |
| :--- | :--- | :--- | :--- |
| **0** | **Public** | Accessible by anyone, no login required. | Landing Page, Login, Docs. |
| **1** | **Public Data** | Read-only public API data. No login required. | Leaderboards, Server Stats. |
| **2** | **User (Login Required)** | Requires login. Access determined by Guild Settings (Default: Everyone allowed). | Basic Dashboard, Leaderboards. |
| **3** | **Authorized** | **Strictly Controlled**. Requires specific Authorization (Role or User). | Bot Settings, Moderation Tools. |
| **4** | **Administrator** | Guild administrators (Discord admin permission). | Add/Remove Authorized Users and Roles. |
| **5** | **Owner** | Guild Owner only. | Permission Management, Destructive Config, Billing. |
| **6** | **Developer** | Platform Administrators. Full cross-guild access. | Platform Debug, LLM Analytics, Config. |

### Security Best Practices
- **Default to Strict**: If unsure, use **Level 3 (Authorized)**.
- **Level 2 (User)**: Ideal for **Read-Only** dashboards (stats, logs).
- **Level 3 (Authorized)**: Required for **Write** actions (settings, moderation).

### Implementing Security
*   **Frontend**: Wrap pages with `withPermission(Component, PermissionLevel.LEVEL)`.
*   **Backend**: Use dependencies `Depends(get_current_user)` and check privileges.
*   **Navigation**: Set the `level` property in `frontend/app/page.tsx` card definitions to auto-hide them.

> **Full security reference with code examples for all 7 levels:** [docs/SECURITY.md](SECURITY.md)

### Rate Limiting
Be aware that the API implements rate limiting. If your bot or frontend receives `429 Too Many Requests`, back off and retry.
- Auth: 5-10 req/min
- LLM: 10-20 req/min
- General: 20 req/min

---


## 3.5 Internationalisation (i18n) — Required for All Frontend Code

Every user-visible string in the dashboard must go through the i18n system. **Never hardcode text in JSX.** The framework defaults to English; both `en.ts` and `es.ts` must always be kept in sync.

### Adding Strings for a New Feature

**Step 1** — Add keys to `frontend/lib/i18n/translations/en.ts` (source of truth):

```typescript
// frontend/lib/i18n/translations/en.ts
export const en = {
  // ... existing keys ...

  // Add your feature namespace at the end
  polls: {
    title: 'Polls',
    createPoll: 'Create Poll',
    noPollsFound: 'No polls found.',
    question: 'Question',
    createdBy: 'Created by {username}',   // {variable} interpolation
  },
};
```

**Step 2** — Mirror the structure in `frontend/lib/i18n/translations/es.ts`:

```typescript
// frontend/lib/i18n/translations/es.ts
polls: {
  title: 'Encuestas',
  createPoll: 'Crear Encuesta',
  noPollsFound: 'No se encontraron encuestas.',
  question: 'Pregunta',
  createdBy: 'Creado por {username}',
},
```

> TypeScript will fail to compile if `es.ts` is missing a key that exists in `en.ts` — this is intentional.

**Step 3** — Use in your component:

```tsx
'use client';
import { useTranslation } from '@/lib/i18n';

function PollsPage() {
    const { t } = useTranslation();

    return (
        <div>
            <h1>{t('polls.title')}</h1>
            <p>{t('polls.createdBy', { username: poll.author })}</p>
        </div>
    );
}
```

### Rules

| Rule | Detail |
|---|---|
| **No hardcoded text** | All user-visible strings use `t('key')` |
| **Both files always** | Add to `en.ts` AND `es.ts` in the same commit |
| **Namespace by feature** | Top-level key = feature name (`polls`, `music`, `moderation`) |
| **Interpolation** | Use `{variableName}` placeholders, never string concatenation |
| **Navigation cards** | `title` and `description` on cards in `page.tsx` should also use `t()` |

---

## 4. Frontend Style Guide (Design System)

To ensure a cohesive look, all plugins **MUST** use the following semantic tokens. **NEVER** use hardcoded colors (e.g., `bg-white`).

| Element | Use This Token (Tailwind) | Do NOT Use |
| :--- | :--- | :--- |
| **Page Background** | `bg-background` | `bg-white`, `bg-gray-900` |
| **Card/Panel** | `bg-card` | `bg-white`, `bg-zinc-800` |
| **Main Text** | `text-foreground` | `text-black`, `text-white` |
| **Secondary Text** | `text-muted-foreground` | `text-gray-500` |
| **Borders** | `border-border` | `border-gray-200` |
| **Primary Action** | `bg-primary`, `text-primary-foreground` | `bg-blue-600` |
| **Destructive** | `bg-destructive`, `text-destructive-foreground` | `bg-red-600` |
| **Input Fields** | `bg-background`, `border-input`, `ring-ring` | `bg-gray-50` |

### Standard Components
- **Page Container**: `p-8 max-w-7xl mx-auto`
- **Section Headers**: `text-2xl font-bold mb-4`
- **Cards**: `bg-card rounded-xl border border-border p-6`
- **Icons**: Use `lucide-react`. Size `w-5 h-5` (20px).

---

## 5. Plugin Workflow (How to Add Features)

> **For AI coding assistants and developers alike — read this before writing a single line.**
>
> Every new feature must be built as a **plugin** in the `plugins/<name>/` staging folder, then installed with `./install_plugin.sh`. **Never modify core framework files directly.** Core files are write-protected (`chmod 444`) after `init.sh` runs — any attempt to edit them is an immediate signal that you are off the correct path.
>
> The correct workflow is always:
> ```
> plugins/<name>/   ← write all new code here
>       ↓
> ./install_plugin.sh <name>   ← validates then installs into the live project
> ```
>
> If you find yourself editing `bot/core/`, `backend/app/api/auth.py`, `backend/app/api/deps.py`, `frontend/lib/auth-context.tsx`, or any existing Alembic migration file — **stop**. The feature you need can always be built within the extension points. See `docs/integration/08-plugin-workflow.md` for the full staging guide.

To add a new feature (e.g., "Music Bot"), follow this strict workflow:

### Step 1: Create the Bot Cog

Create `bot/cogs/music.py`. Every cog must:

- Provide an explicit `description=` on every `@app_commands.command()` — never omit it.
- Declare a `SETTINGS_SCHEMA` class attribute if the cog reads from guild settings — the Bot Settings page renders from this automatically.
- Do not build demo/example code directly into the live project — use the plugin staging system.

```python
# bot/cogs/music.py
import discord
from discord import app_commands
from discord.ext import commands
import structlog

logger = structlog.get_logger()

class MusicCog(commands.Cog):
    """Music playback for your server."""

    # Declare the settings fields this cog reads so the Bot Settings page
    # renders them automatically — no frontend code change needed.
    SETTINGS_SCHEMA = {
        "id": "music",
        "label": "Music",
        "description": "Configure music playback settings.",
        "fields": [
            {"key": "music_enabled",    "type": "boolean",        "label": "Enable Music",         "default": False},
            {"key": "music_channel_id", "type": "channel_select", "label": "Allowed Voice Channel", "default": None},
        ],
    }
```

#### SETTINGS_SCHEMA Field Types Reference

| `type` | Rendered as | `default` |
|---|---|---|
| `"boolean"` | Toggle switch | `False` |
| `"text"` | Single-line text input | `""` or `None` |
| `"number"` | Number input | `0` or `None` |
| `"channel_select"` | Discord channel dropdown (populated from API) | `None` |
| `"role_select"` | Discord role dropdown (populated from API) | `None` |
| `"multiselect"` | Multi-checkbox from fixed options — add `"choices": [{"value": "x", "label": "X"}]` | `[]` or `None` |

```python
    SETTINGS_SCHEMA = {

    @app_commands.command(
        name="play",
        description="Play a song in the current voice channel"  # REQUIRED — always explicit
    )
    @app_commands.describe(query="Song name or URL")
    async def play(self, interaction: discord.Interaction, query: str):
        logger.info("play_invoked", command="play",
                    user_id=interaction.user.id, guild_id=interaction.guild_id)
        await interaction.response.defer()
        # fetch settings
        settings = await self._get_settings(interaction.guild_id)
        if not settings.get("music_enabled"):
            await interaction.followup.send("Music is not enabled.", ephemeral=True)
            return
        # ... implementation

    async def _get_settings(self, guild_id: int) -> dict:
        headers = {"Authorization": f"Bot {self.bot.services.config.DISCORD_BOT_TOKEN}"}
        async with self.bot.session.get(
            f"http://backend:8000/api/v1/guilds/{guild_id}/settings",
            headers=headers
        ) as resp:
            if resp.status == 200:
                return (await resp.json()).get("settings", {})
        return {}

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
```

> **`bot.session`** is a shared `aiohttp.ClientSession` created once in `setup_hook` and available on every cog via `self.bot.session`. Always use this shared session for HTTP calls to the backend — never create a new `aiohttp.ClientSession()` per request, as that leaks connections.

> **Bot Settings page is automatic.** Once `SETTINGS_SCHEMA` is declared and the bot restarts, the settings form appears in the dashboard with no frontend changes needed. The introspection cog sends schemas to the backend on `on_ready`; the backend stores them; the settings page fetches and renders them.

### Step 2: Add a Navigation Card (Optional)

If the feature needs its own dedicated dashboard page (beyond the generic Bot Settings card), add a card to `frontend/app/page.tsx`:

```typescript
{
    id: "music",
    title: "Music",
    description: "Control music playback.",
    href: `/dashboard/${guildId}/music`,
    icon: MusicIcon,
    level: PermissionLevel.AUTHORIZED,  // must match withPermission level on the page
},
```

And create `frontend/app/dashboard/[guildId]/music/page.tsx`:

```tsx
'use client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';

// Security: L3 — Authorized users only
function MusicPage() {
    return <div>Music Settings</div>;
}

export default withPermission(MusicPage, PermissionLevel.AUTHORIZED);
```

> **REQUIRED — `withPermission` on every dashboard page.** This HOC injects the `← Dashboard` breadcrumb, enforces the permission check, and redirects unauthenticated users. A page exported as plain `export default function` will have no navigation link and no permission guard.

### Step 3: Register a Backend API (If Needed)

If the feature needs its own endpoints beyond guild settings, create `backend/app/api/music.py`:

```python
# backend/app/api/music.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.guild_session import get_guild_db

router = APIRouter()

@router.get("/{guild_id}/music/queue")
async def get_queue(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),  # RLS active
):
    # Implementation
    return {"queue": []}
```

Then register it in `backend/main.py` — add these two lines at the end of the router registration block:

```python
# backend/main.py
from app.api.music import router as music_router
app.include_router(music_router, prefix=f"{settings.API_V1_STR}/guilds", tags=["music"])
```

Follow the security rules in [docs/SECURITY.md](SECURITY.md) — every endpoint must declare its security level.

### Baseline Expectations

**Every Bot** built on this framework is expected to have **at least:**

1. One **Cog** with explicit `description=` on every command and `SETTINGS_SCHEMA` for any configurable settings.
2. Settings exposed via the generic Bot Settings page (automatic from `SETTINGS_SCHEMA`) — a dedicated page is only needed for complex UIs.
3. Every frontend page exported via `withPermission` — never as a bare `export default function`.
4. All mutations write an `AuditLog` entry at the backend.

---

## 5.5 Initialising a New Bot

Run `./init.sh` once after cloning. It:
1. Deletes all demo plugin folders from `plugins/` — only `_template/` and `README.md` remain
2. Write-protects core framework files (`chmod 444`)

The project is now blank. Build your features from `plugins/_template/`, then install them with `./install_plugin.sh`.

## 6. Database: Architecture and Extension Guide

> **CRITICAL — READ BEFORE TOUCHING ANYTHING DATABASE-RELATED**
>
> The database layer is **core framework infrastructure**. Never modify existing migrations, never change the schema isolation rules, and never add tables directly to existing Alembic revision files. New features extend the framework by adding NEW migrations alongside the existing ones — they never replace or alter what is already there.

---

### 6.1 How the Database Layer Works

The framework enforces a single, strict contract for every database interaction:

| Rule | Enforced By |
| :--- | :--- |
| One DB user per bot deployment | `setup_database.sh --user <name>` (required, no default) |
| Schema name always equals username | `setup_database.sh`, `alembic/env.py`, `session.py` |
| All objects land in the app schema, never `public` | `ALTER ROLE ... SET search_path`, `REVOKE CREATE ON SCHEMA public` |
| Every connection uses `search_path = <schema>` | `session.py` → asyncpg `server_settings`, `alembic/env.py` → `SET search_path` |
| `alembic_version` tracked inside the app schema | `version_table_schema=db_schema` in `alembic/env.py` |

**Multiple bots can safely share the same Postgres cluster** because each bot runs under its own user/schema combination (`bot_a` schema `bot_a`, `bot_b` schema `bot_b`). Their objects never touch.

---

### 6.2 First-Time Setup

```bash
# 1. Generate the encryption key (once per deployment)
./setup_secrets.sh

# 2. Start Postgres
docker compose up -d postgres

# 3. Create the DB user and schema (once per deployment, choose any username)
./setup_database.sh --user mybot

# 4. Start the full stack — the Setup Wizard runs automatically
docker compose up

# 5. Open the app in your browser and complete the wizard
```

The wizard (browser UI) collects DB credentials, Discord tokens, and API keys, then encrypts and stores them. From that point on the app starts fully automatically — no `.env` files, no plaintext secrets on disk.

---

### 6.3 Guild Isolation — Row-Level Security (RLS)

> **This is the most critical section for anyone adding new features.**

A bot serves many Discord servers simultaneously. Without isolation, a bug — a missing `WHERE` clause, a wrong variable — can leak one server's data to another. The framework prevents this at the **database engine level** using PostgreSQL Row-Level Security (RLS). Application code cannot bypass it by accident.

#### The Three Session Dependencies

Choose the session dependency based on what your endpoint accesses:

| Dependency | Import | When to use |
| :--- | :--- | :--- |
| `get_guild_db` | `app.db.guild_session` | Any endpoint under `/{guild_id}/`. RLS **active** — only that guild's rows are visible or writable. |
| `get_admin_db` | `app.db.guild_session` | L6 admin endpoints needing cross-guild or global data. RLS bypassed. Requires platform admin automatically. |
| `get_db` | `app.db.session` | Endpoints that only touch non-guild tables (`users`, `shards`, `app_config`, etc.). RLS bypassed. |

#### Guild-Scoped Endpoints — always use `get_guild_db`

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.guild_session import get_guild_db
from app.models import Ticket

@router.get("/{guild_id}/tickets")
async def list_tickets(
    guild_id: int,                              # FastAPI resolves from path
    db: AsyncSession = Depends(get_guild_db),   # sets RLS context automatically
):
    # No WHERE needed — the database enforces the filter.
    # Even if you forget, wrong-server data is invisible.
    result = await db.execute(select(Ticket))
    return result.scalars().all()
```

FastAPI extracts `guild_id` from the path and passes it to `get_guild_db`, which executes `SET LOCAL app.current_guild_id = '{guild_id}'` inside the transaction. The RLS policy then applies to every query in that session.

#### What Happens Without a Context (Fail-Safe)

If a query runs on a guild-scoped table with no context set, the policy evaluates:

```
NULL = guild_id  →  NULL  →  false
```

**Zero rows are returned.** A forgotten `WHERE` clause produces an obviously empty result, not a data leak.

#### Automatic Audit Logging — `GuildAuditMiddleware`

Every successful POST, PUT, PATCH, or DELETE on a `/{guild_id}/` route is automatically recorded in the `audit_logs` table by `GuildAuditMiddleware` in `backend/main.py`. The action field is `METHOD:/api/v1/guilds/:id/<sub-path>`.

**Plugin developers must NOT add `db.add(AuditLog(...))` to their endpoints.** Doing so:
1. Creates duplicate audit log entries for every request
2. Requires knowing the correct guild_id (gets it wrong for cross-guild/bot operations — FK violation)
3. Adds error-prone boilerplate that belongs in the framework

```python
# ✓ Correct — middleware handles the audit log automatically
@router.post("/{guild_id}/my-plugin/tickets")
async def create_ticket(
    guild_id: int,
    payload: TicketPayload,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    db.add(Ticket(guild_id=guild_id, ...))
    await db.commit()           # audit log written automatically after 201 response
    return {"id": ticket.id}

# ✗ Wrong — never do this
@router.post("/{guild_id}/my-plugin/tickets")
async def create_ticket(...):
    db.add(Ticket(...))
    db.add(AuditLog(guild_id=guild_id, ...))  # ← duplicate; FK risk; not your job
    await db.commit()
```

Bot-internal requests (no session cookie or Bearer token) are excluded from auditing automatically — the middleware only audits authenticated user actions.

#### Platform-Admin Cross-Guild Endpoints — use `get_admin_db`

```python
from app.db.guild_session import get_admin_db

@router.get("/admin/all-tickets")
async def admin_list_all_tickets(
    db: AsyncSession = Depends(get_admin_db),  # bypass + L6 auth built in
):
    result = await db.execute(select(Ticket))  # sees ALL guilds
    return result.scalars().all()
```

#### Tables That Are Guild-Scoped (RLS active — migration 1.1.0)

| Table | RLS column | Notes |
| :--- | :--- | :--- |
| `guilds` | `id` | `id` IS the Discord guild ID |
| `authorized_users` | `guild_id` | |
| `authorized_roles` | `guild_id` | |
| `guild_settings` | `guild_id` | |
| `audit_logs` | `guild_id` | |
| `llm_usage` | `guild_id` | Nullable — `NULL` = system/global usage |
| `llm_usage_summary` | `guild_id` | Nullable — `NULL` = system/global usage |

#### Tables That Are Global (no RLS)

`users`, `user_tokens`, `shards`, `llm_model_pricing`, `app_config`, `alembic_version`

#### `search_path` and Schema Isolation

The session also has `search_path = <app_schema>` set at connection time. Every unqualified table name (`SELECT * FROM tickets`) automatically resolves to `<schema>.tickets`. Never qualify table names with the schema in application code.

**In bot services:** Cogs call the backend API over HTTP — the backend owns all DB sessions. The bot never connects to Postgres directly.

#### Services That Write to Guild-Scoped Tables Without an HTTP Context

Some backend services (e.g. `LLMService._track_usage`) receive a `db` session from a caller and must write to a guild-scoped table. Because the caller's session comes from `get_db` (bypass=true), the service must set the RLS context itself when a `guild_id` is known:

```python
from sqlalchemy import text

async def _write_guild_record(db, guild_id, ...):
    if guild_id is not None:
        # Disable bypass and activate per-guild policy before the INSERT.
        await db.execute(text("SET LOCAL app.bypass_guild_rls = 'false'"))
        await db.execute(text(f"SET LOCAL app.current_guild_id = '{int(guild_id)}'"))
    # Now safe to INSERT — RLS policy is satisfied.
    db.add(MyGuildModel(guild_id=guild_id, ...))
    await db.commit()
```

`SET LOCAL` is transaction-scoped and is cleared automatically on commit/rollback, so no cleanup is needed.

#### Platform-Admin Access to Guild-Scoped Tables

Endpoints that need to read or write guild-scoped tables across all guilds (e.g. platform settings stored in a designated guild's row) must use `get_admin_db`, **not** `get_db`. `get_admin_db` sets `bypass_guild_rls = 'true'` and automatically enforces platform-admin authentication:

```python
from app.db.guild_session import get_admin_db

@router.get("/settings")
async def get_platform_settings(
    db: AsyncSession = Depends(get_admin_db),  # cross-guild RLS bypass + L6 auth
    admin: dict = Depends(verify_platform_admin),
):
    ...
```

`get_db` must **never** be used for endpoints that touch guild-scoped tables, even for admin operations — it provides no auth guard and leaves RLS silently bypassed.

---

### 6.4 Adding New Tables (Framework Extension)

When your bot needs new database tables, follow this exact process. **Do not modify any existing migration files.**

#### Step 1 — Define the SQLAlchemy model

Add your model to `backend/app/models.py` (or a new file imported by `models.py`).

**For guild-scoped tables** (stores per-server data) — use `GuildScopedMixin`:

```python
from sqlalchemy import Column, String, BigInteger, DateTime
from sqlalchemy.sql import func
from app.db.base import Base          # shared Base — never create a new one
from app.db.mixins import GuildScopedMixin

class Ticket(GuildScopedMixin, Base):  # GuildScopedMixin FIRST
    __tablename__ = "tickets"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    # guild_id is inherited from GuildScopedMixin — do NOT redeclare it
    title      = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

`GuildScopedMixin` adds `guild_id` and the `__guild_scoped__ = True` marker. The RLS migration must be extended to cover new guild-scoped tables — see Step 2 note below.

**For global tables** (platform-wide data, no guild filter):

```python
from app.db.base import Base

class GlobalConfig(Base):
    __tablename__ = "global_config"
    id    = Column(BigInteger, primary_key=True, autoincrement=True)
    key   = Column(String(255), nullable=False, unique=True)
    value = Column(String, nullable=False)
```

> Use the framework's `Base` from `app.db.base`. Never create a separate `Base` — all models must share the same metadata for Alembic to detect them.

#### Step 2 — Generate the migration

```bash
cd backend
alembic revision --autogenerate -m "add_my_feature_table"
```

Alembic will create a new file under `backend/alembic/versions/`. Note the revision ID printed to stdout (e.g. `a1b2c3d4e5f6`).

The generated migration **does not need** `SET search_path` or schema qualifiers — `alembic/env.py` already sets `search_path` before running any migration, so your new table lands in the correct app schema automatically.

**If your new table is guild-scoped**, add RLS to the migration:

```python
def upgrade() -> None:
    op.create_table("tickets", ...)

    # Enable RLS on the new guild-scoped table
    op.execute('ALTER TABLE "tickets" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "tickets" FORCE ROW LEVEL SECURITY')
    op.execute("""
        CREATE POLICY guild_isolation ON "tickets"
        USING (
            guild_id = current_setting('app.current_guild_id', true)::bigint
            OR current_setting('app.bypass_guild_rls', true) = 'true'
        )
        WITH CHECK (
            guild_id = current_setting('app.current_guild_id', true)::bigint
            OR current_setting('app.bypass_guild_rls', true) = 'true'
        )
    """)

def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS guild_isolation ON "tickets"')
    op.execute('ALTER TABLE "tickets" NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "tickets" DISABLE ROW LEVEL SECURITY')
    op.drop_table("tickets")
```

#### Step 3 — Register the new version in `migration_inventory.json`

Open `backend/migration_inventory.json` — this is the single source of truth for all version data. `version.py` is read-only logic that loads from it; never edit `version.py` directly.

Make two changes:

```json
{
  "framework_version": "1.1.0",
  "framework_migrations": [
    {
      "version": "1.0.0",
      "description": "Initial schema — users, guilds, permissions, audit log, LLM tracking, app config",
      "revisions": ["c8d4e5f6a7b9"],
      "head_revision": "c8d4e5f6a7b9"
    },
    {
      "version": "1.1.0",
      "description": "Add my_feature table",
      "revisions": ["a1b2c3d4e5f6"],
      "head_revision": "a1b2c3d4e5f6"
    }
  ],
  "plugin_migrations": []
}
```

Once committed, the **Database Management** page will automatically detect that the live database is behind, display the upgrade path version-by-version, and allow the operator to apply the migration through the UI or via `alembic upgrade head`.

#### Step 4 — Use the model in your endpoint

```python
# backend/app/api/tickets.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.guild_session import get_guild_db  # NOT get_db
from app.models import Ticket

@router.get("/{guild_id}/tickets")
async def list_tickets(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),  # RLS active
):
    # No WHERE needed — RLS enforces guild isolation automatically.
    result = await db.execute(select(Ticket))
    return result.scalars().all()
```

---

### 6.5 Migration Rules (Mandatory)

| Rule | Reason |
| :--- | :--- |
| **Never edit an existing migration file** | Other deployments may already have applied it; changing it breaks their `alembic_version` checksum |
| **Never hardcode schema names** in migrations | `search_path` is set by `alembic/env.py`; unqualified names always resolve correctly |
| **Never create objects in `public`** | `REVOKE CREATE ON SCHEMA public` is enforced at the Postgres role level |
| **Always bump `FRAMEWORK_VERSION`** when adding framework migrations | Required for the DB Management UI to show the framework upgrade path correctly |
| **Always add to `MIGRATION_CHANGELOG`** for framework changes | Required for version-aware framework upgrades |
| **Never edit `version.py`** — it is read-only logic | All version data lives in `backend/migration_inventory.json`; plugins write it automatically, framework releases update it manually |

---

### 6.6 Database Access During Development

The PostgreSQL port `5432` is **not** exposed to the host machine.

**Option 1: Docker Exec (CLI)**
```bash
docker compose exec postgres psql -U <your_username> -d <your_dbname>
```

**Option 2: Temporary Port Mapping (GUI tools)**
```bash
docker run --rm -it --network=baseline_dbnet -p 5433:5432 alpine/socat TCP-LISTEN:5432,fork TCP:postgres:5432
```
Then connect to `localhost:5433` with your DB credentials.

---

## 7. Bot Permission Configuration

The framework includes a **Permission Validator** that ensures your bot has all required Discord intents and guild permissions at startup. This helps catch configuration errors early.

### The `required_permissions.yaml` File

Place a `required_permissions.yaml` file in the `bot/` directory to define your bot's permission requirements:

```yaml
# Required Discord Gateway Intents
# Privileged intents must also be enabled in the Discord Developer Portal
intents:
  - message_content  # For reading message content
  - members          # For member join/leave events
  - guilds           # For guild join/leave events

# Required Guild Permissions
# The bot role needs these permissions in each server
permissions:
  - send_messages
  - embed_links
  - read_message_history

# If true, bot refuses to start when permissions are missing
# If false (default), bot logs warnings but continues
strict_mode: false
```

### How It Works

1. **At Startup (`setup_hook`)**: The validator checks that all required **intents** are enabled in the bot code and Discord Developer Portal.
2. **On Connection (`on_ready`)**: The validator checks that the bot has all required **guild permissions** in each server it joins.

### Intent and Permission References

- **Intents**: [discord.py Intents Documentation](https://discordpy.readthedocs.io/en/stable/intents.html)
- **Permissions**: [discord.py Permissions Documentation](https://discordpy.readthedocs.io/en/stable/api.html#discord.Permissions)

### LLM Prompt for Permission Discovery

Use the following prompt with an LLM to automatically scan your bot project and generate the `required_permissions.yaml` file:

---

**Prompt:**

> Analyze the following Discord bot project files and identify all required Discord permissions.
>
> **For each file, identify:**
>
> 1. **Intents** - Based on event listeners used. Reference:
>    - `on_message`, `on_message_delete`, `on_message_edit` → `message_content`
>    - `on_member_join`, `on_member_remove`, `on_member_update` → `members`
>    - `on_guild_join`, `on_guild_remove` → `guilds`
>    - `on_presence_update` → `presences`
>    - `on_typing` → `typing`
>
> 2. **Guild Permissions** - Based on actions performed. Reference:
>    - `channel.send()`, `interaction.response.send_message()` → `send_messages`
>    - Sending `discord.Embed` objects → `embed_links`
>    - Accessing `message.content` on old messages → `read_message_history`
>    - `member.kick()` → `kick_members`
>    - `member.ban()` → `ban_members`
>    - `member.add_roles()`, `member.remove_roles()` → `manage_roles`
>
> **Output a YAML file in this exact format:**
>
> ```yaml
> # Required permissions for [Bot Name]
> intents:
>   - intent_name  # Source: filename.py (event_name)
>
> permissions:
>   - permission_name  # Source: filename.py (action)
>
> strict_mode: false
> ```
>
> **Files to analyze:**
>
> [Paste your bot/cogs/*.py and bot/core/*.py file contents here]

---

### Best Practices

1. **Keep permissions minimal**: Only request what your bot actually needs.
2. **Use `strict_mode: false` in development**: Allows testing with partial permissions.
3. **Use `strict_mode: true` in production**: Ensures the bot fails fast if misconfigured.
4. **Document each permission**: Add comments explaining why each permission is needed.

---

## 8. LLM Prompts for Code Generation

Use the following prompts with an AI assistant to generate correct framework-compliant code.

### Prompt: Generate a Complete Cog

> You are working inside the **Baseline Discord Bot Framework**. Read `CLAUDE.md` for the rules before writing any code.
>
> Generate a complete, production-ready Discord cog for the following feature:
>
> **Feature description:** [describe your feature here]
>
> **Requirements:**
> - Use `@app_commands.command()` with an explicit `description=` on every command
> - Use `@app_commands.describe()` for every parameter
> - Use `bot.services.llm` for any LLM calls, always passing `guild_id` and `user_id`
> - Use `self.bot.session` (shared `aiohttp.ClientSession`) for HTTP calls to the backend
> - Declare `SETTINGS_SCHEMA` if the cog has configurable settings
> - Use `structlog.get_logger()` for logging
> - Wrap all command bodies in try/except; send ephemeral error messages on failure
> - Build inside `plugins/<feature>/` and install with `./install_plugin.sh`
>
> Output: a single `bot/cogs/<feature>.py` file with the `async def setup(bot)` function at the bottom.

### Prompt: Generate a Complete Feature (Cog + API + Page)

> You are working inside the **Baseline Discord Bot Framework**. Read `CLAUDE.md` for the rules before writing any code. Also read `docs/DEVELOPER_MANUAL.md` Section 5.
>
> Generate all files for the following feature:
>
> **Feature:** [describe your feature here]
> **Permission level:** [L2 User / L3 Authorized / L4 Administrator / L5 Owner / L6 Developer]
> **Needs persistent storage:** [yes/no — if yes, describe the data]
>
> Output the following files, in order:
> 1. `bot/cogs/<feature>.py` — Discord cog
> 2. `backend/app/api/<feature>.py` — FastAPI router (use `get_guild_db`, not `get_db`)
> 3. The two lines to add to `backend/main.py` to register the router
> 4. `frontend/app/dashboard/[guildId]/<feature>/page.tsx` — dashboard page (use `withPermission`, use `t()` for all strings)
> 5. The translation keys to add to `en.ts` and `es.ts`
> 6. If adding DB tables: the model addition for `backend/app/models.py` and the RLS migration snippet

### Prompt: Generate Permission Discovery (existing prompt — see Section 7)

See Section 7 for the `required_permissions.yaml` generation prompt.
