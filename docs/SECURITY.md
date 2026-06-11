# Baseline Framework: Security Reference

**Read this before forking or deploying.** This document is the definitive security reference for the Baseline framework. Every developer working on a bot built on this framework must understand the security model before adding new pages, endpoints, commands, or settings.

---

## Table of Contents

1. [Security Levels (L0–L6)](#1-security-levels-l0l6)
2. [Implementing Security on Every Layer](#2-implementing-security-on-every-layer)
3. [Authentication Architecture](#3-authentication-architecture)
4. [Defense-in-Depth Layers](#4-defense-in-depth-layers)
5. [Endpoint Security Matrix](#5-endpoint-security-matrix)
6. [Framework Conventions](#6-framework-conventions)
7. [Security Anti-Patterns](#7-security-anti-patterns)
8. [Security Checklist Before Going Live](#8-security-checklist-before-going-live)
9. [Known Production Hardening Requirements](#9-known-production-hardening-requirements)
10. [Security Rules for New Features](#10-security-rules-for-new-features)

---

## 1. Security Levels (L0–L6)

The framework enforces a **7-tier permission model**. Every page, endpoint, and bot command **must be explicitly assigned a level**. There is no implicit security — default to L3 when unsure.

| Level | Name | Who Can Access | Typical Use |
|-------|------|---------------|-------------|
| **L0** | **Public** | Anyone, no auth | Landing page, login, public docs |
| **L1** | **Public Data** | Anyone, no auth | Read-only stats, command list (no PII) |
| **L2** | **User** | Any logged-in user (configurable via guild roles) | Dashboard home, read-only guild stats |
| **L3** | **Authorized** | Explicitly authorized users/roles per guild | Read-only view of bot settings, moderation commands |
| **L4** | **Administrator** | Guild administrators (Discord admin permission) | Bot settings (edit), add/remove authorized users and roles |
| **L5** | **Owner** | Guild owner only | Permission management, billing, destructive config |
| **L6** | **Developer** | Platform administrators only | Platform debug, LLM analytics, all-guild access |

> **When in doubt, use L3.** It is always easier to relax security than to tighten it after data has been exposed.

### Level Definitions

#### L0 — Public
No authentication required. Safe for static content with no sensitive data.

```typescript
// Frontend: no wrapper needed, but be explicit
export default function LandingPage() {
    return <div>Anyone can see this</div>;
}
```

```python
# Backend: no auth dependency
# Security: L0 — Public
@router.get("/status")
async def public_status():
    return {"status": "ok"}
```

---

#### L1 — Public Data
No authentication required. Read-only, non-sensitive aggregated data only. Never expose user IDs, tokens, or PII at this level.

```typescript
// Frontend: no wrapper — but document it clearly in a comment
// Security: L1 — Public read-only data, no auth required
export default function CommandsPage() { ... }
```

```python
# Backend: no auth dependency, return only public/aggregated data
# Security: L1 — Public Data
@router.get("/guilds/{guild_id}/public")
async def public_guild_info(guild_id: int, db: AsyncSession = Depends(get_db)):
    return {"name": guild.name, "member_count": guild.member_count}
```

---

#### L2 — User (Login Required)
Requires a valid session. Access can be further restricted by guild settings (specific roles). Used for any page that displays guild-specific data.

```typescript
// Frontend: wrap with withPermission at USER level
'use client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';

function GuildDashboard() {
    return <div>Member-only content</div>;
}

export default withPermission(GuildDashboard, PermissionLevel.USER);
```

```python
# Backend: require authentication
# Security: L2 — Login required
from app.api.deps import get_current_user

@router.get("/guilds/{guild_id}/stats")
async def guild_stats(
    guild_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Always verify the user has access to this specific guild
    await _require_guild_access(guild_id, current_user, db)
    ...
```

---

#### L3 — Authorized (Strictly Controlled)
Requires explicit authorization: the user must be in the `authorized_users` table for that guild, or have an `authorized_role`. **Default for read-only access to guild data (audit logs, settings view, etc.).**

```typescript
// Frontend
export default withPermission(AuditLogsPage, PermissionLevel.AUTHORIZED);
```

```python
# Backend: check authorization level explicitly
# Security: L3 — Authorized users only
from app.api.deps import get_current_user
from sqlalchemy import select
from app.models import AuthorizedUser, PermissionLevel as DBPermLevel

@router.put("/guilds/{guild_id}/settings")
async def update_settings(
    guild_id: int,
    settings: SettingsUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    user_id = int(current_user["user_id"])

    # L3: check explicit authorization — ADMIN or OWNER only
    auth = await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == user_id,
            AuthorizedUser.permission_level.in_([
                DBPermLevel.ADMIN, DBPermLevel.OWNER
            ])
        )
    )
    if not auth.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not authorized")
    ...
```

---

#### L4 — Administrator
Guild administrators (users with Discord's Administrator permission in the guild, but not the guild owner). Used for managing who can access the bot — adding/removing authorized users and roles.

```typescript
// Frontend
export default withPermission(PermissionsPage, PermissionLevel.ADMINISTRATOR);
```

```python
# Backend: check guild admin status
# Security: L4 — Guild administrator only
@router.post("/guilds/{guild_id}/authorized-users")
async def add_authorized_user(
    guild_id: int,
    data: AuthorizedUserCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_guild_db)
):
    user_id = int(current_user["user_id"])
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404)
    # L4: guild admin or owner required
    if guild.owner_id != user_id and not await _is_guild_admin(guild_id, user_id, db):
        raise HTTPException(status_code=403, detail="Guild administrator only")
    ...
```

---

#### L5 — Owner
Guild owner only. For destructive or irreversible actions: deleting the bot from a guild, managing who has admin access, sensitive configuration.

```typescript
// Frontend
export default withPermission(PermissionsPage, PermissionLevel.OWNER);
```

```python
# Backend: check guild owner
# Security: L5 — Guild owner only
@router.delete("/guilds/{guild_id}/authorized-users/{user_id}")
async def remove_authorized_user(
    guild_id: int, user_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_guild_db)
):
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404)
    if guild.owner_id != int(current_user["user_id"]):
        raise HTTPException(status_code=403, detail="Guild owner only")
    ...
```

---

#### L6 — Developer (Platform Admin)
Platform administrators only. Full access across all guilds. Determined by Discord guild membership in the developer guild (`DISCORD_GUILD_ID`) with the developer role (`DEVELOPER_ROLE_ID`), or by bot token auth.

> **Implementation note:** Developer access is already a separate check path on both layers — `user.is_admin` on the frontend and `verify_platform_admin()` on the backend. The numeric level (6) exists only to satisfy the `hasAccess()` comparison in the permission hook; guild users can never reach it through normal guild-membership checks.

```typescript
// Frontend
export default withPermission(PlatformPage, PermissionLevel.DEVELOPER);
```

```python
# Backend: use verify_platform_admin dependency — never implement this check manually
# Security: L6 — Platform admin only
from app.api.deps import verify_platform_admin

@router.get("/platform/settings")
async def platform_settings(
    current_user: dict = Depends(verify_platform_admin)
):
    ...
```

---

#### Internal — Docker Network Trust
Some endpoints are called **only by the bot** or other internal services. They have no user authentication but are protected by Docker network isolation — they are unreachable from the internet. Never expose these ports publicly.

```python
# Backend: no auth dependency — secured by Docker network only
# Security: Internal — Docker network trust (bot→backend calls)
# Never expose this endpoint via public nginx routes.
@router.post("/bot-info/report")
async def report_bot_info(report: BotReport, redis: Redis = Depends(get_redis)):
    ...
```

Document every internal endpoint clearly. If an endpoint uses Docker network trust, the router that registers it must NOT have a public nginx upstream.

---

## 1.5 Database Session Selection (Critical for Guild Data)

Before implementing any backend endpoint, choose the correct session dependency. This is a **security decision**, not just an API choice.

| Use | When |
|---|---|
| `Depends(get_guild_db)` | **Any endpoint under `/{guild_id}/`** — enables RLS; only that guild's rows are visible |
| `Depends(get_admin_db)` | L6 cross-guild endpoints — RLS bypassed, platform admin auth enforced |
| `Depends(get_db)` | Global tables only (`users`, `shards`, `app_config`) — never for guild data |

> **The code examples in the sections below use `get_db` for brevity to focus on the permission pattern.** In real endpoints that access guild-scoped tables (`guilds`, `guild_settings`, `authorized_users`, `audit_logs`, `llm_usage`, etc.), you must use `get_guild_db` instead. See [DEVELOPER_MANUAL.md §6.3](DEVELOPER_MANUAL.md#63-guild-isolation--row-level-security-rls) for the complete reference.

---

## 2. Implementing Security on Every Layer

Security is enforced at **three independent layers** for every feature. All three must be implemented — backend enforcement is mandatory, frontend is defense-in-depth for UX.

```
Request → [Frontend route guard] → [Nginx rate limit] → [Backend auth dependency] → [Authorization check]
```

### Frontend Layer (UX Guard)

Every dashboard page **must** use `withPermission`:

```typescript
// CORRECT — always explicit
export default withPermission(MyPage, PermissionLevel.AUTHORIZED);

// WRONG — never export a page without a permission wrapper
export default MyPage;
```

The `withPermission` HOC:
- Redirects to `/login` if the user is not authenticated (for L2+)
- Redirects to `/access-denied` if the permission level is insufficient
- Shows a loading state during the auth check
- Renders `null` immediately to prevent flash of protected content

### Backend Layer (Enforcement — Mandatory)

Frontend checks can be bypassed by direct API calls. **The backend is the only real enforcement point.**

```python
# Every guild-scoped endpoint needs BOTH:
# 1. Authentication  →  get_current_user
# 2. Authorization   →  verify the user's level for THIS guild

@router.post("/guilds/{guild_id}/features")
async def create_feature(
    guild_id: int,
    data: FeatureCreate,
    current_user: dict = Depends(get_current_user),  # Step 1: authenticated
    db: AsyncSession = Depends(get_db)
):
    # Step 2: authorized for this guild
    user_id = int(current_user["user_id"])
    auth = await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == user_id,
        )
    )
    if not auth.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not authorized for this guild")
    ...
```

### Navigation Layer (Visibility)

Set the `level` property on navigation cards so they are hidden from users who cannot access them. This does NOT replace backend checks — it is for UX only.

```typescript
const navItems = [
    { label: "Stats",       href: "/stats",       level: PermissionLevel.USER },
    { label: "Settings",    href: "/settings",    level: PermissionLevel.AUTHORIZED },
    { label: "Permissions", href: "/permissions", level: PermissionLevel.ADMINISTRATOR },
    { label: "Owner Panel", href: "/owner",       level: PermissionLevel.OWNER },
    { label: "Platform",    href: "/platform",    level: PermissionLevel.DEVELOPER },
];
```

---

## 3. Authentication Architecture

### Token Flow

```
User → Discord OAuth2 → GET /auth/discord/login
                              ↓
              Discord callback → /auth/discord/callback
                              ↓
              Generate UUID api_token
              Hash (SHA-256) → UserToken row (DB, persistent)
              Store raw token → Redis session:{token} (30-day TTL)
              Return raw token to frontend (localStorage)
                              ↓
Every request: Authorization: Bearer {token}
              → Check Redis (fast path, ~1ms)
              → Redis miss: check DB, restore Redis (self-healing)
              → Check revocation marker (user:revoked_at:{user_id})
              → Auto-refresh Discord OAuth token if expiring within 5 min
              → Return user_data dict to endpoint handler
```

### Session Data Structure (Redis)

```json
{
    "user_id": "123456789",
    "username": "username",
    "access_token": "discord_access_token",
    "refresh_token": "discord_refresh_token",
    "expires_at": 1234567890.0,
    "token_db_id": 42,
    "token_created_at": 1234567890.0
}
```

`token_created_at` is used for immediate revocation via `logout-all`.

### Immediate Revocation (logout-all)

When `POST /auth/logout-all` is called:
1. All `UserToken` records for the user are deleted from DB
2. `user:revoked_at:{user_id}` is set in Redis with the current timestamp (TTL: 30 days)
3. On every subsequent request, `get_current_user` checks `token_created_at < revoked_at` → 401

This provides **immediate** invalidation of all active sessions, even those still present in Redis.

### Bot Token Authentication

The bot can authenticate to the backend using `Authorization: Bot {DISCORD_BOT_TOKEN}`. This returns a synthetic admin user and grants L5 access. Used for bot→backend calls on the internal network.

---

## 4. Defense-in-Depth Layers

The framework enforces security at 6 independent layers. An attacker must bypass all of them.

```
Internet
    │
    ▼
[Layer 1: Network Isolation]
    Docker networks: backend is NOT on the internet network.
    Only nginx gateway is public-facing on port 8000.
    Bot, Postgres, Redis are on internal networks only.
    │
    ▼
[Layer 2: Nginx Gateway]
    Rate limiting zones (auth: 3/s, gemini: 5/s, api: 10/s)
    Security headers (X-Frame-Options, HSTS, CSP, etc.)
    Sets X-Gateway-Request: true header on all proxied requests
    │
    ▼
[Layer 3: SecurityMiddleware]
    Validates X-Gateway-Request header OR internal Docker IP.
    Blocks all external access to /api/v1/gemini/* and /api/v1/llm/*
    Logs all blocked attempts with client info.
    In SETUP_MODE: blocks all endpoints except /setup/* and /health.
    │
    ▼
[Layer 4: Authentication]
    get_current_user() — validates Bearer token or Bot token
    Checks Redis → DB fallback (self-healing sessions)
    Checks immediate revocation marker (logout-all)
    Refreshes Discord OAuth tokens automatically
    │
    ▼
[Layer 5: Rate Limiting (slowapi)]
    Per-endpoint rate limits enforced at backend level.
    Applies even if nginx is bypassed (internal calls).
    │
    ▼
[Layer 6: Authorization]
    Per-endpoint permission checks (guild owner, authorized user/role).
    verify_platform_admin() for L5 endpoints.
    Audit log written for all mutating operations.
```

---

## 5. Endpoint Security Matrix

All registered endpoints and their security level. Use this as a reference when adding new endpoints to ensure nothing is accidentally over- or under-exposed.

### Auth (`/api/v1/auth/`)

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| `/discord/login` | GET | L0 | Initiates OAuth2 flow |
| `/discord/callback` | GET | L0 | Receives Discord callback, issues token |
| `/discord-config` | GET | L0 | Returns public OAuth client_id |
| `/me` | GET | L2 | Returns current user's profile |
| `/logout` | POST | L2 | Revokes current device session |
| `/logout-all` | POST | L2 | Revokes all sessions immediately |

### Guilds (`/api/v1/guilds/`)

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| `/{guild_id}/public` | GET | L1 | Name, icon — no PII |
| `/` | GET | L2 | Lists user's guilds |
| `/{guild_id}` | GET | L2 | Guild info + user's permission level |
| `/{guild_id}/channels` | GET | L2 | Fetches from Discord API |
| `/{guild_id}/roles` | GET | L2 | Fetches from Discord API |
| `/{guild_id}/members/search` | GET | L2 | Member autocomplete |
| `/{guild_id}/settings` | GET | L3 | Guild bot settings (read-only for L3) |
| `/{guild_id}/settings` | PUT | L4 | Update guild settings; some keys restricted to L6 |
| `/{guild_id}/authorized-users` | GET | L3 | List authorized users |
| `/{guild_id}/authorized-roles` | GET | L3 | List authorized roles |
| `/{guild_id}/audit-logs` | GET | L3 | View audit log |
| `/{guild_id}/authorized-users` | POST | L4 | Add authorized user (guild admin+) |
| `/{guild_id}/authorized-users/{id}` | DELETE | L5 | Remove authorized user (owner only) |
| `/{guild_id}/authorized-roles` | POST | L4 | Add authorized role (guild admin+) |
| `/{guild_id}/authorized-roles/{id}` | DELETE | L5 | Remove authorized role (owner only) |
| `/` | POST | Internal | Create guild — bot-only, no user auth |

### Bot Info (`/api/v1/bot-info/`)

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| `/public` | GET | L0 | Bot name, tagline, logo, invite URL |
| `/settings-schema` | GET | L1 | Form schema declarations from cogs — no values |
| `/report` | POST | Internal | Bot pushes introspection data; Docker network trust |
| `/report` | GET | L6 | Platform admin reads introspection data |

### Commands (`/api/v1/commands/`)

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| `/` | GET | L1 | Public command list |
| `/refresh` | POST | L6 | Re-fetch from Discord API |

### Instrumentation (`/api/v1/instrumentation/`)

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| `/card-click` | POST | L2 | Authenticated analytics event |
| `/bot-command` | POST | Internal | Bot records command metrics; Docker network trust |
| `/guild-event` | POST | Internal | Bot records guild join/leave; Docker network trust |
| `/stats` | GET | L6 | Aggregated analytics for platform admin |
| `/metrics` | GET | Internal | Prometheus text-format scrape; IP-restricted |

### LLM (`/api/v1/llm/`) — Network-isolated (SecurityMiddleware)

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| `/generate` | POST | L2 | Text generation |
| `/chat` | POST | L2 | Multi-turn chat |
| `/structured` | POST | L2 | Structured JSON output |
| `/tools` | POST | L2 | Function calling |
| `/stats` | GET | L6 | LLM usage cost analytics |

### Platform, Config, Database (`/api/v1/platform/`, `/api/v1/config/`, `/api/v1/database/`)

All endpoints in these routers are **L6 — Platform Admin only**, except:

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| `/platform/heartbeat` | POST | Internal | Bot sends heartbeat; Docker network trust |

### Setup (`/api/v1/setup/`)

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| All `/setup/*` | GET/POST | L0 (wizard mode) | Only reachable when SETUP_MODE=true; all other endpoints return 503 |

### Users (`/api/v1/users/`)

| Endpoint | Method | Level | Notes |
|----------|--------|-------|-------|
| `/me/settings` | GET | L2 | User preferences |
| `/me/settings` | PUT | L2 | Update user preferences |

---

## 6. Framework Conventions

These conventions must be followed by all developers adding new functionality to the framework. They ensure correct security, discoverability, and deployment behaviour.

### 6.1 Creating a New Cog

Every cog file must follow this structure:

```python
# bot/cogs/my_feature.py

import discord
from discord import app_commands
from discord.ext import commands
import structlog

logger = structlog.get_logger()


class MyFeatureCog(commands.Cog):
    """
    Brief description of what this cog does.
    """

    # ── Declare settings this cog reads from guild settings JSON ─────────────
    # SETTINGS_SCHEMA = {
    #     "id": "my_feature",
    #     "label": "My Feature",
    #     "description": "Configure My Feature.",
    #     "fields": [
    #         {"key": "my_enabled", "type": "boolean", "label": "Enable", "default": False},
    #         {"key": "my_channel_id", "type": "channel_select", "label": "Channel", "default": None},
    #     ],
    # }

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="my-command",
        description="Human-readable description shown to Discord users"  # REQUIRED — always explicit
    )
    @app_commands.describe(option="What this option does")
    async def my_command(self, interaction: discord.Interaction, option: str):
        logger.info("my_command_invoked",
            command="my-command",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
        )
        await interaction.response.defer()
        # ... implementation
        await interaction.followup.send("Done!")


async def setup(bot):
    await bot.add_cog(MyFeatureCog(bot))
```

**Required for every cog:**
- `description=` in every `@app_commands.command()` — never omit this. Discord.py falls back to the docstring's first line, which will expose internal `*** DEMO ***` markers if present.
- Structured log at the start of every command handler with `command`, `user_id`, `guild_id`.
- `async def setup(bot)` at the bottom.

**When the cog reads guild settings:**
- Declare `SETTINGS_SCHEMA` as a class attribute. The introspection cog sends it to the backend on startup. The Bot Settings page renders it dynamically — no frontend code changes needed.

### 6.2 SETTINGS_SCHEMA Field Types

| `type` | UI rendered | Value stored in settings JSON |
|--------|-------------|-------------------------------|
| `boolean` | Toggle checkbox | `true` / `false` |
| `channel_select` | Dropdown of text channels | Discord channel ID (string) |
| `multiselect` | Checkbox list with `choices` | Array of selected `value` strings |
| `text` | Text input | String |
| `number` | Number input | Number |

Example (full schema):

```python
SETTINGS_SCHEMA = {
    "id": "my_feature",          # unique identifier — used as namespace
    "label": "My Feature",       # card heading in Bot Settings page
    "description": "What this feature does.",
    "fields": [
        {
            "key": "my_feature_enabled",   # key in guild settings JSON
            "type": "boolean",
            "label": "Enable My Feature",
            "default": False,
        },
        {
            "key": "my_feature_channel_id",
            "type": "channel_select",
            "label": "Output Channel",
            "description": "Where messages are sent.",
            "default": None,
        },
        {
            "key": "my_feature_mode",
            "type": "multiselect",
            "label": "Active Modes",
            "choices": [
                {"label": "Mode A", "value": "mode_a"},
                {"label": "Mode B", "value": "mode_b"},
            ],
            "default": [],
        },
    ],
}
```

**Reading settings in a cog** — fetch from the backend at command time:

```python
async def _get_settings(self, guild_id: int) -> dict:
    headers = {"Authorization": f"Bot {self.bot.services.config.DISCORD_BOT_TOKEN}"}
    async with self.bot.session.get(
        f"http://backend:8000/api/v1/guilds/{guild_id}/settings",
        headers=headers
    ) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get("settings", {})
    return {}

# In your command:
settings = await self._get_settings(interaction.guild_id)
if not settings.get("my_feature_enabled"):
    await interaction.followup.send("This feature is not enabled.", ephemeral=True)
    return
```

### 6.3 Creating a New Dashboard Card (page.tsx)

Every new page in `frontend/app/dashboard/[guildId]/` must follow this template:

```typescript
'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';

// Security: L3 — Authorized users only
// Change to PermissionLevel.USER for read-only pages,
//           PermissionLevel.OWNER for owner-only pages.
function MyFeaturePage() {
    const params = useParams();
    const guildId = params.guildId as string;

    // ... state and fetch logic

    return (
        <div className="max-w-4xl mx-auto space-y-8">
            <h1 className="text-3xl font-bold">My Feature</h1>
            {/* content */}
        </div>
    );
}

export default withPermission(MyFeaturePage, PermissionLevel.AUTHORIZED);
```

**Required:**
- Always `'use client';` at the top for dashboard pages.
- Always `withPermission(Component, Level)` — never export the component directly.
- The permission level on the frontend must match the backend endpoint's requirement.

**Adding the card to the dashboard** (`frontend/app/page.tsx`):

```typescript
{
    id: "my-feature",
    title: "My Feature",
    description: "What it does.",
    href: `/dashboard/${guildId}/my-feature`,
    icon: MyIcon,
    level: PermissionLevel.AUTHORIZED,   // must match withPermission level
},
```

### 6.4 Reading and Writing Guild Settings (Backend)

Always use `get_guild_db` (not `get_db`) for guild-scoped data to ensure Row-Level Security applies. Use `AsyncSession` (never sync `Session`). Access the user ID as `current_user["user_id"]` (not `current_user["id"]`).

```python
# CORRECT
from app.db.session import get_guild_db   # RLS-aware session

@router.put("/guilds/{guild_id}/my-feature")
async def update_my_feature(
    guild_id: int,
    data: MyFeatureUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_guild_db),    # guild-scoped
):
    user_id = int(current_user["user_id"])       # always "user_id", not "id"
    ...

    # Re-query after commit — never use db.refresh() after await db.commit()
    await db.commit()
    result = await db.execute(select(MyModel).where(MyModel.guild_id == guild_id))
    return result.scalar_one()
```

### 6.5 Writing Audit Logs

Every endpoint that mutates state must write an audit log:

```python
from app.models import AuditLog

audit = AuditLog(
    guild_id=guild_id,
    user_id=int(current_user["user_id"]),
    action="UPDATE_MY_FEATURE_SETTINGS",
    details={"before": old_value, "after": data.model_dump()}
)
db.add(audit)
await db.commit()
```

Use `SCREAMING_SNAKE_CASE` for action names. Include `before` and `after` in details for all update operations.

---

## 7. Security Anti-Patterns

These are real mistakes that have appeared in this codebase. Do not repeat them.

### ❌ Wrong user ID key

```python
# WRONG — current_user has no key "id"
auth_check = db.execute(select(AuthorizedUser).where(
    AuthorizedUser.user_id == current_user["id"]   # KeyError at runtime
))

# CORRECT
user_id = int(current_user["user_id"])
```

### ❌ Sync session in async handler

```python
# WRONG — get_db returns AsyncSession; using it as Session causes runtime errors
from sqlalchemy.orm import Session

@router.get("/something")
async def handler(db: Session = Depends(get_db)):
    result = db.execute(...)      # AttributeError: Session has no method execute

# CORRECT
from sqlalchemy.ext.asyncio import AsyncSession

@router.get("/something")
async def handler(db: AsyncSession = Depends(get_db)):
    result = await db.execute(...)
```

### ❌ db.refresh() after await db.commit()

```python
# WRONG — raises InvalidRequestError on newly-inserted instances
await db.commit()
await db.refresh(settings)   # ERROR: instance is expired after commit

# CORRECT — re-query instead
await db.commit()
result = await db.execute(select(GuildSettings).where(GuildSettings.guild_id == guild_id))
settings = result.scalar_one()
```

### ❌ Trusting guild_id without membership check

```python
# WRONG — any logged-in user can read any guild's data
@router.get("/guilds/{guild_id}/data")
async def get_data(guild_id: int, current_user: dict = Depends(get_current_user)):
    return await db.get(Data, guild_id)  # no membership verification!

# CORRECT
@router.get("/guilds/{guild_id}/data")
async def get_data(guild_id: int, current_user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    user_id = int(current_user["user_id"])
    auth = await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == user_id,
        )
    )
    if not auth.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not authorized for this guild")
```

### ❌ Missing description= on subcommands

```python
# WRONG — discord.py uses the docstring first line as the description.
# If the docstring starts with "*** DEMO ***", that text appears in Discord.
@gemini_demo.command(name="thinking")
async def thinking(self, interaction, prompt: str):
    """*** DEMO *** Generate text with thinking."""
    ...

# CORRECT — always provide description= explicitly
@gemini_demo.command(name="thinking", description="Generate text with adjustable reasoning depth")
async def thinking(self, interaction, prompt: str):
    ...
```

### ❌ Skipping withPermission on frontend pages

```typescript
// WRONG — page has no permission check
function AdminPage() { ... }
export default AdminPage;

// CORRECT
export default withPermission(AdminPage, PermissionLevel.AUTHORIZED);
```

### ❌ Unregistered router with security bugs

Creating a router file in `app/api/` does not register it — it must be added to `main.py`. However, an unregistered router is dead code with no protection. If it gets registered later (e.g., during a merge), the security issues become live immediately. **Delete unreferenced router files rather than leaving them as dead code.**

---

## 8. Security Checklist Before Going Live

Run through this checklist before deploying a new bot or after adding new features.

### Secrets & Configuration

- [ ] Setup Wizard completed — all secrets entered via the browser UI and encrypted in the Docker volume
- [ ] `secrets/encryption_key` exists and is **not** committed to git (check `.gitignore`)
- [ ] No secrets in `.env`, `docker-compose.yml`, or any committed file
- [ ] `FRONTEND_URL` is set to the production domain (OAuth redirect and postMessage origin)
- [ ] `DISCORD_GUILD_ID` and `DEVELOPER_ROLE_ID` are set for L5 admin access

### Every New Frontend Page

- [ ] Page is wrapped with `withPermission(Component, PermissionLevel.LEVEL)`
- [ ] Permission level matches the sensitivity of the data shown
- [ ] Write actions use L3 (AUTHORIZED) or higher
- [ ] Navigation card has the correct `level` set to hide from unauthorized users
- [ ] Demo pages live in `plugins/` — not installed in the live project

### Every New Backend Endpoint

- [ ] `Depends(get_current_user)` is present on all non-public, non-internal endpoints
- [ ] Guild membership is validated after authentication
- [ ] `user_id = int(current_user["user_id"])` — not `current_user["id"]`
- [ ] `AsyncSession` from `Depends(get_guild_db)` for guild endpoints, `Depends(get_db)` for global tables only — not sync `Session`
- [ ] No `db.refresh()` after `await db.commit()` — re-query instead
- [ ] Pydantic input schema validates and constrains all fields
- [ ] Audit log entry written for all mutating operations
- [ ] Endpoint is registered in `main.py`
- [ ] Security level is documented in the endpoint docstring

### Every New Bot Command

- [ ] `description=` is explicit in every `@app_commands.command()` decorator
- [ ] Command checks `interaction.guild` before accessing guild data
- [ ] Guild settings are fetched from backend, not hardcoded
- [ ] Errors are caught and user-friendly messages returned
- [ ] Demo commands live in `plugins/` — not installed in the live project

### Every New Cog with Settings

- [ ] `SETTINGS_SCHEMA` is declared as a class attribute
- [ ] Each field key matches the key used to read from settings JSON
- [ ] Demo cogs live in `plugins/` — not installed in the live project

### Network & Infrastructure

- [ ] HTTPS/TLS is configured in production (nginx with SSL certificates)
- [ ] `secure=True` is set on cookies in production (`auth.py`)
- [ ] CSP `unsafe-inline`/`unsafe-eval` removed for production nginx config
- [ ] PostgreSQL port `5432` is NOT exposed to the host
- [ ] Redis port `6379` is NOT exposed to the host
- [ ] Prometheus, Loki, Grafana ports are NOT publicly exposed

---

## 9. Known Production Hardening Requirements

These are acceptable in development but **must** be addressed before production.

| Issue | Location | Action Required |
|-------|----------|----------------|
| Cookie `secure=False` | `backend/app/api/auth.py` | Set `secure=True` when HTTPS is enabled |
| CSP `unsafe-inline`/`unsafe-eval` | `gateway/nginx.conf` | Remove for production; use nonces |
| No HTTPS termination | `docker-compose.yml` | Add SSL certificates + nginx HTTPS block |
| Admin check hits Discord API live | `backend/app/api/deps.py:check_is_admin` | Cache result in Redis for 5 minutes |
| Expired `UserToken` rows not cleaned up | `backend/app/models.py` | Add scheduled cleanup (cron/celery) |
| No HMAC signing on bot→backend calls | `bot/cogs/guild_sync.py` | Add `X-Bot-Signature` header |
| Refresh token stored in plaintext | `backend/app/models.py:User.refresh_token` | Encrypt with a data encryption key |

---

## 10. Security Rules for New Features

When developing a new feature (cog + endpoint + page), enforce these rules without exception.

### Rule 1: Backend is the source of truth
The frontend permission check is for UX only. Always validate at the backend. A user who calls the API directly bypasses the frontend entirely.

### Rule 2: Default to L3 (Authorized)
If you are unsure what level a page or endpoint should be, use `PermissionLevel.AUTHORIZED` / `Depends(get_current_user)` + guild auth check. Relax after confirming it is safe to do so.

### Rule 3: Read = L2, Write = L3
- Displaying guild data to authenticated users → L2 (User)
- Modifying any configuration or data → L3 (Authorized) minimum
- Destructive actions → L5 (Owner)
- Admin-level guild management → L4 (Administrator)
- Destructive guild actions → L5 (Owner)
- Cross-guild or platform operations → L6 (Developer)

### Rule 4: Always validate guild membership
When an endpoint takes a `guild_id` parameter, always verify the requesting user has access to that guild. Never trust the `guild_id` in the URL alone — any logged-in user could enumerate guild IDs.

### Rule 5: Audit log all mutations
Any endpoint that changes state must write an `AuditLog` entry. This is non-negotiable. It is how the guild owner sees what changed and who changed it.

### Rule 6: Validate and sanitize all input
Use strict Pydantic schemas. Avoid `Dict[str, Any]` for sensitive data. Set `max_length` on string fields. Use `pattern=` for structured inputs like role IDs and snowflake IDs.

```python
# WRONG
class Settings(BaseModel):
    config: Dict[str, Any]  # accepts anything

# CORRECT
class FeatureSettings(BaseModel):
    enabled: bool
    channel_id: Optional[int] = None
    prefix: str = Field(default="!", max_length=5, pattern=r"^[!?./]{1,5}$")
```

### Rule 7: Keep demo code out of the permanent codebase

Demo plugins live in `plugins/` and are installed on demand with `./install_plugin.sh`. Never commit demo code to the live project (`bot/cogs/`, `backend/app/api/`, `frontend/app/`). There is nothing to strip at clone time.

### Rule 8: No dead router files
Every file in `backend/app/api/` that defines a `router` must be registered in `main.py`, or deleted. Unregistered routers with security bugs become live vulnerabilities the moment someone adds an `include_router` call.
