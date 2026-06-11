# Baseline Framework Architecture

**For Developers**: This document explains the architecture and design principles of the Baseline Discord Bot Framework.

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Component Deep Dive](#component-deep-dive)
4. [Plugin System](#plugin-system)
5. [Extension Points](#extension-points)
6. [Data Flow](#data-flow)
7. [Best Practices](#best-practices)

## Overview

Baseline is a modular framework for building Discord bots with web dashboards. It provides:

- **Authentication & Authorization**: Discord OAuth2, role-based permissions
- **Settings Management**: Per-guild configuration via web dashboard
- **Audit Logging**: Track all configuration changes
- **LLM Integration**: Multi-provider AI support (OpenAI, Anthropic, Google, xAI)
- **Shard Monitoring**: Real-time bot health tracking
- **Extensibility**: Plugin system for adding custom features

### Design Principles

1. **Modularity**: Components are loosely coupled and independently deployable
2. **Extensibility**: Easy to add new features without modifying core code
3. **Configuration over Code**: Behavior controlled via settings, not hardcoded
4. **Security First**: Authentication, authorization, and audit logging built-in
5. **Production Ready**: Docker-based deployment, health checks, logging

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Frontend (Next.js)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Dashboard   │  │   Settings   │  │  Audit Logs  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP/REST
┌───────────────────────────┴─────────────────────────────────┐
│                      Backend (FastAPI)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Auth Router  │  │ Guilds Router│  │ Shards Router│      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │  PostgreSQL  │  │    Redis     │                        │
│  │  (Guilds,    │  │  (Sessions,  │                        │
│  │   Users,     │  │   Cache)     │                        │
│  │   Settings)  │  │              │                        │
│  └──────────────┘  └──────────────┘                        │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP (internal)
┌───────────────────────────┴─────────────────────────────────┐
│                       Bot (discord.py)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Chat Cog    │  │  Guild Sync  │  │  Custom Cogs │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ LLM Service  │  │Shard Monitor │  │   Logging    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└──────────────────────────────────────────────────────────────┘
```

### Communication Flow

1. **User → Frontend**: User interacts with web dashboard
2. **Frontend → Backend**: REST API calls with Bearer token auth
3. **Backend → Database**: Store/retrieve guild settings, users, audit logs
4. **Backend → Redis**: Session storage, caching
5. **Bot → Backend**: Fetch guild settings, report shard status
6. **Bot → Discord**: Commands, events, messages

### Network Topology & Security

To ensure maximum security, the backend API is **completely isolated from the public internet**.

```
┌────────────────────────────────────────────────────────────────┐
│                      INTERNET (Public)                          │
└────────────────────────────┬───────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Gateway (nginx)│ ← Rate limiting, Security headers
                    │    Port 8000    │   X-Gateway-Request header
                    └────────┬────────┘
                             │
┌────────────────────────────┼───────────────────────────────────┐
│                     INTRANET (Private)                          │
│                            │                                    │
│    ┌─────────────┬─────────┴─────────┬───────────────┐         │
│    │             │                   │               │         │
│    ▼             ▼                   ▼               ▼         │
│ ┌──────┐    ┌──────────┐       ┌─────────┐     ┌─────────┐    │
│ │ Bot  │    │ Frontend │       │ Backend │     │  Redis  │    │
│ │      │    │ (Next.js)│       │(FastAPI)│     │ (Cache) │    │
│ └──────┘    └──────────┘       └────┬────┘     └─────────┘    │
│                                      │                         │
└──────────────────────────────────────┼─────────────────────────┘
                                       │
┌──────────────────────────────────────┼─────────────────────────┐
│                      DBNET (Database)                           │
│                             ▼                                   │
│                       ┌──────────┐                              │
│                       │ Postgres │                              │
│                       │   (DB)   │                              │
│                       └──────────┘                              │
└────────────────────────────────────────────────────────────────┘
```

**Security Layers (Defense in Depth):**

| Layer | Component | Protection |
|-------|-----------|------------|
| 1. Network | Docker Networks | Backend NOT on internet network |
| 2. Gateway | Nginx | Rate limiting, security headers, CSP |
| 3. Middleware | SecurityMiddleware | Validates `X-Gateway-Request` header |
| 4. Auth | `get_current_user` | Requires session/JWT for all endpoints |
| 5. Rate Limit | slowapi | Per-endpoint rate limiting |
| 6. Database | dbnet (internal) | Only backend can access |

**Traffic Flow:**
1.  **User → Gateway**: External requests hit nginx on port 8000
2.  **Gateway → Backend**: Nginx adds `X-Gateway-Request: true` header
3.  **Backend validates**: SecurityMiddleware checks header for sensitive endpoints
4.  **Backend authenticates**: `get_current_user` verifies session/JWT
5.  **Backend processes**: Rate limiting, business logic, database access

**Sensitive Endpoints (Extra Protection):**
- `/api/v1/gemini/*` - Gemini AI features (cost-sensitive)
- `/api/v1/llm/*` - LLM provider access (cost-sensitive)

These endpoints require:
- Valid `X-Gateway-Request` header (from nginx) OR internal Docker IP
- Authenticated session (user logged in)
- Stricter rate limits (5 req/sec vs 10 req/sec)

**Security Module Location:** `backend/app/core/security.py`

```python
# Example: Checking if request is trusted
from app.core.security import is_trusted_request, require_internal_network

# In middleware - automatic for /api/v1/gemini/* and /api/v1/llm/*
if not is_trusted_request(request):
    return 403 Forbidden

# Decorator for custom endpoints
@router.post("/admin/dangerous-operation")
@require_internal_network
async def dangerous_operation(request: Request):
    ...
```


### Authentication Architecture

The system uses a custom persistent session mechanism backed by Discord OAuth2.

**Key Components:**
-   **UserToken (DB)**: A long-lived, hashed token stored in the `user_tokens` table. Support multiple tokens per user (Multi-Device).
-   **Redis Session**: Ephemeral session cache (Key: `session:{api_token}`) for fast access.
-   **API Token**: UUIDv4 token sent to the frontend and stored in `localStorage`.

**Session Logic:**
1.  **Login**: User logs in with Discord -> Backend generates `api_token` -> Hashes and stores in DB -> Stores raw in Redis -> Returns raw to Client.
2.  **Validation**: Middleware checks Redis. If missing (expired/evicted), checks DB for valid hash. If valid, restores Redis session (Self-Healing).
3.  **Logout**: Removes specific token from DB & Redis (Single Device).
4.  **Logout All**: Removes all tokens for user from DB (Global Revocation).

## Component Deep Dive

### Frontend (Next.js 16 + TypeScript)

**Location**: `frontend/`

**Responsibilities**:
- User authentication (Discord OAuth2)
- Server management interface
- Settings configuration
- Audit log viewing
- System status monitoring

**Key Files**:
- `app/dashboard/layout.tsx`: Main dashboard layout with sidebar
- `app/dashboard/[guildId]/settings/page.tsx`: Guild settings page
- `app/api-client.ts`: API client for backend communication
- `lib/auth-context.tsx`: Authentication state management

**Extension Points**:
- Add new pages in `app/dashboard/[guildId]/`
- Add new components in `app/components/`
- Extend API client with new methods in `app/api-client.ts`
- Add translation strings to `lib/i18n/translations/en.ts` and `es.ts`

### Backend (FastAPI + PostgreSQL + Redis)

**Location**: `backend/`

**Responsibilities**:
- REST API for frontend
- Discord OAuth2 flow
- User session management
- Guild settings storage
- Audit logging
- Permission checks

**Key Files**:
- `main.py`: FastAPI application setup
- `app/api/auth.py`: OAuth2 and session management
- `app/api/guilds.py`: Guild settings and permissions
- `app/models.py`: SQLAlchemy database models
- `app/schemas.py`: Pydantic validation models

**Extension Points**:
- Add new routers in `app/api/`
- Add new models to `app/models.py`
- Add new schemas to `app/schemas.py`

### Bot (discord.py)

**Location**: `bot/`

**Responsibilities**:
- Discord command handling
- Event processing
- Guild synchronization
- LLM integration
- Shard monitoring

**Key Files**:
- `core/bot.py`: Main bot class with auto-sharding
- `cogs/guild_sync.py`: Synchronize guilds with backend (core — do not modify)
- `cogs/introspection.py`: Sends `SETTINGS_SCHEMA` from all cogs to backend on startup (core)
- `services/llm.py`: Multi-provider LLM service abstraction
- `services/shard_monitor.py`: Shard health monitoring

**Extension Points**:
- Add new cogs in `cogs/`
- Add new services in `services/`

## Plugin System

### How Plugins Work

The framework uses a **convention-over-configuration** approach:

1. **Bot Cogs**: Any Python file in `bot/cogs/` with a `setup()` function is automatically loaded
2. **Backend Routers**: Import and include routers in `backend/main.py`
3. **Frontend Pages**: Create page components in `frontend/app/`

### Adding a Complete Feature

Example: Adding a "Warnings" feature

#### 1. Database Model

```python
# backend/app/models.py
class Warning(Base):
    __tablename__ = "warnings"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id"))
    user_id = Column(BigInteger)
    reason = Column(String)
    issued_by = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

#### 2. Backend API

```python
# backend/app/api/warnings.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.guild_session import get_guild_db  # NOT get_db — RLS must be active for guild data

router = APIRouter()

@router.get("/{guild_id}/warnings")
async def list_warnings(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),  # RLS active — only this guild's rows visible
):
    # No WHERE clause needed — RLS enforces isolation automatically
    pass

@router.post("/{guild_id}/warnings")
async def create_warning(
    guild_id: int,
    warning: WarningCreate,
    db: AsyncSession = Depends(get_guild_db),  # RLS active
):
    # Implementation
    pass
```

#### 3. Bot Cog

```python
# bot/cogs/moderation.py
class Moderation(commands.Cog):
    @app_commands.command()
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        # Call backend API to store warning
        # Send notification
        pass

async def setup(bot):
    await bot.add_cog(Moderation(bot))
```

#### 4. Frontend Page

```typescript
// frontend/app/dashboard/[guildId]/warnings/page.tsx
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';

function WarningsPage() {
    // Fetch warnings from API
    // Display in table
    // Allow filtering/search
}

export default withPermission(WarningsPage, PermissionLevel.AUTHORIZED);
```

## Extension Points

### Bot Extensions

| Extension Point | Location | Purpose |
|----------------|----------|---------|
| **Cogs** | `bot/cogs/*.py` | Add commands and event listeners |
| **Services** | `bot/services/*.py` | Add shared functionality |
| **Config** | `bot/config.py` | Add configuration options |

### Backend Extensions

| Extension Point | Location | Purpose |
|----------------|----------|---------|
| **Routers** | `backend/app/api/*.py` | Add API endpoints (then register in `main.py`) |
| **Models** | `backend/app/models.py` | Add database models |
| **Schemas** | `backend/app/schemas.py` | Add Pydantic validation schemas |
| **Migrations** | `backend/alembic/versions/` | Add DB migrations (auto-generate with alembic) |
| **Migration inventory** | `backend/migration_inventory.json` | Single source of truth for all version data; written by `install_plugin.sh` (plugins) and developers (framework releases) |

### Frontend Extensions

| Extension Point | Location | Purpose |
|----------------|----------|---------|
| **Pages** | `frontend/app/dashboard/[guildId]/*.tsx` | Add dashboard UI pages |
| **Components** | `frontend/app/components/*.tsx` | Add reusable components |
| **API Client** | `frontend/app/api-client.ts` | Add API methods |
| **i18n strings** | `frontend/lib/i18n/translations/en.ts` + `es.ts` | Add translated strings |

## Data Flow

### User Configures Settings

```
User (Browser)
  → Frontend /dashboard/[guildId]/settings
    → API Client PUT /guilds/{id}/settings
      → Backend guilds.update_guild_settings()
        → PostgreSQL: Update guild_settings table
        → PostgreSQL: Create audit_log entry
      ← Return updated settings
    ← Update UI
  ← Show success message
```

### Bot Executes Command

```
User (Discord)
  → /chat command
    → Bot chat.py cog
      → HTTP GET /guilds/{id}/settings (from backend)
        ← Guild settings (allowed_channels, system_prompt, model)
      → Check if channel is allowed
      → Call LLM service
        → LLM provider (OpenAI/Anthropic/etc)
        ← AI response
      → Send message to channel
    ← User sees response
```

### Guild Joins

```
Bot receives guild_join event
  → guild_sync.py on_guild_join()
    → HTTP POST /guilds/ (to backend)
      → PostgreSQL: Insert/update guilds table
      → PostgreSQL: Create default guild_settings
      ← Confirm creation
    ← Log success
```

## Best Practices

### For Bot Development

1. **Use Cogs**: Organize commands into logical cogs
2. **Defer Long Operations**: Use `interaction.response.defer()` for operations > 3s
3. **Handle Errors Gracefully**: Catch exceptions and respond to user
4. **Log Important Events**: Use structlog for structured logging
5. **Respect Rate Limits**: Discord has strict rate limits
6. **Use Guild Settings**: Fetch per-guild config from backend

### For Backend Development

1. **Validate Input**: Use Pydantic schemas
2. **Check Permissions**: Verify user access before operations
3. **Use Transactions**: Wrap related DB operations in transactions
4. **Return Proper Status Codes**: 200, 201, 400, 403, 404, 500
5. **Log Audit Events**: Record configuration changes
6. **Use Async**: All I/O should be async

### For Frontend Development

1. **Handle Loading States**: Show loading indicators
2. **Handle Errors**: Display error messages to users
3. **Use TypeScript**: Define interfaces for data
4. **Follow Design System**: Use consistent styling (Tailwind classes)
5. **Optimize Performance**: Use React hooks efficiently
6. **Protect Routes**: Check authentication state

## Security Considerations

1. **Authentication**: All API endpoints require valid session
2. **Authorization**: Permission checks before sensitive operations
3. **Input Validation**: Pydantic schemas validate all input
4. **SQL Injection Prevention**: SQLAlchemy ORM parameterized queries
5. **XSS Prevention**: React automatically escapes content
6. **CORS**: Configured to only allow frontend origin
7. **Secrets Management**: Docker secrets for sensitive data
8. **Audit Logging**: All changes tracked with user attribution
9. **Rate Limiting**: `slowapi` and Nginx limit request rates to prevent abuse


## Performance Considerations

1. **Database Indexes**: Add indexes on frequently queried columns
2. **Redis Caching**: Cache guild settings and Discord API responses (e.g., user guilds) to prevent rate limits and reduce DB load
3. **Connection Pooling**: SQLAlchemy connection pool
4. **Async I/O**: All I/O operations are async
5. **Pagination**: Implement for large result sets
6. **CDN**: Serve static assets via CDN (production)

## Deployment Architecture

```
Production Environment:
├── Load Balancer
│   ├── Frontend (Next.js) - Port 3000
│   └── Backend  (FastAPI)  - Port 8000
├── Database
│   └── PostgreSQL (managed service)
├── Cache
│   └── Redis (managed service)
└── Bot
    └── Discord.py (auto-sharded)
```

## Directory Structure

```
baseline/
├── backend/              # FastAPI application
│   ├── alembic/         # Database migrations
│   ├── app/
│   │   ├── api/         # API routers
│   │   │   ├── auth.py
│   │   │   ├── guilds.py
│   │   │   └── shards.py
│   │   ├── core/        # Core configuration
│   │   ├── db/          # Database setup
│   │   ├── models.py    # SQLAlchemy models
│   │   └── schemas.py   # Pydantic schemas
│   └── main.py          # FastAPI app
├── bot/                  # Discord bot
│   ├── cogs/            # Command modules (add your cogs here)
│   │   ├── guild_sync.py      # core — syncs guilds with backend
│   │   └── introspection.py   # core — sends SETTINGS_SCHEMA to backend
│   ├── core/            # Bot core (do not modify)
│   │   └── bot.py
│   ├── services/        # Shared services
│   │   ├── llm.py
│   │   └── shard_monitor.py
│   └── main.py          # Bot entry point
├── frontend/             # Next.js app
│   ├── app/             # App router pages
│   │   ├── dashboard/
│   │   │   ├── [guildId]/
│   │   │   │   ├── settings/
│   │   │   │   └── audit-logs/
│   │   │   └── layout.tsx
│   │   └── login/
│   ├── lib/             # Utilities
│   └── public/          # Static assets
├── docs/                 # Documentation
│   ├── integration/     # Integration guides
│   └── ARCHITECTURE.md  # This file
├── secrets/              # Secret files
└── docker-compose.yml    # Docker setup
```

## Next Steps for Developers

1. Review `walkthrough.md` for feature overview
2. Read integration guides in `docs/integration/`
3. Study existing code in each component
4. Set up development environment following `README.md`
5. Build a simple plugin to understand the flow

## Support

- **Issues**: Check existing GitHub issues or create new ones
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: All docs in `docs/` directory
