# Baseline Discord Bot Framework - AI Agent Instructions

## Architecture Overview

This is a **Discord bot framework** with three components running in Docker:
- **Backend** (FastAPI + PostgreSQL + Redis): API, auth, database @ `backend/`
- **Bot** (discord.py, auto-sharded): Discord commands via Cogs @ `bot/`
- **Frontend** (Next.js 16 + TypeScript): Web dashboard @ `frontend/`

Traffic flows: `Internet → nginx Gateway → Backend ← Bot/Frontend (intranet)`

> **Read `CLAUDE.md` at the project root first** — it has the mandatory rules checklist every AI assistant must follow before writing any code.

## Critical Patterns

### Bot Cogs (Adding Discord Commands)
Cogs auto-load from `bot/cogs/`. Every cog needs the `setup` function:

```python
# bot/cogs/my_feature.py
import discord
from discord import app_commands
from discord.ext import commands
import structlog

logger = structlog.get_logger()

class MyFeature(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm  # always bot.services.llm, never bot.llm_service

    @app_commands.command(name="mycommand", description="Description is required")
    @app_commands.describe(param="Parameter description")
    async def my_command(self, interaction: discord.Interaction, param: str):
        await interaction.response.defer()
        # Always pass guild_id and user_id for usage attribution
        response = await self.llm.chat(
            message=param,
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )
        await interaction.followup.send(response)

async def setup(bot):
    await bot.add_cog(MyFeature(bot))
```

**Key rules:**
- `description=` is required on every `@app_commands.command()`
- Use `self.bot.session` (shared `aiohttp.ClientSession`) for backend HTTP calls — never create a new one per request
- Use `@app_commands.checks.cooldown(...)` for rate limiting slash commands — `@commands.cooldown` is for prefix commands only

### Frontend Pages (Adding Dashboard Pages)
Pages use a **7-tier permission system**. Wrap with `withPermission` and use `t()` for all strings:

```tsx
// frontend/app/dashboard/[guildId]/my-page/page.tsx
'use client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

function MyPage() {
    const { t } = useTranslation();
    return <h1>{t('myPage.title')}</h1>;  // never hardcode text
}
export default withPermission(MyPage, PermissionLevel.AUTHORIZED);
```

Add strings to **both** `frontend/lib/i18n/translations/en.ts` and `es.ts`.

**Permission Levels:** 0=Public, 1=PublicData, 2=User(login), 3=Authorized, 4=Owner, 5=Developer

### Backend API Routes
For guild-scoped data use `get_guild_db` (enables Row-Level Security). `get_db` is for global tables only:

```python
# backend/app/api/my_router.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.db.guild_session import get_guild_db  # RLS active — for /{guild_id}/ endpoints
from app.db.session import get_db              # No RLS — for global tables only

router = APIRouter()

@router.get("/{guild_id}/my-data")
async def get_data(
    guild_id: int,
    user = Depends(get_current_user),
    db: AsyncSession = Depends(get_guild_db),  # RLS enforces guild isolation
):
    return {"data": "value"}
```

Register in `backend/main.py`:
```python
from app.api.my_router import router as my_router
app.include_router(my_router, prefix=f"{settings.API_V1_STR}/guilds", tags=["my-feature"])
```

## Styling Conventions (Frontend)

**Always use semantic tokens, never hardcoded colors:**
- Background: `bg-background`, `bg-card`
- Text: `text-foreground`, `text-muted-foreground`
- Borders: `border-border`
- Actions: `bg-primary`, `bg-destructive`

Icons: `lucide-react` at `w-5 h-5`

## Development Commands

```bash
docker compose up -d                                         # Start dev environment
docker compose logs -f                                       # View all service logs
docker compose exec backend alembic upgrade head             # Run Alembic migrations
docker compose restart bot                                   # Restart specific service (backend/bot/frontend)
docker compose down -v                                       # Remove containers and volumes
```

**Testing:**
```bash
./test.sh                                                    # Interactive integration test runner
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test-runner
```

## LLM Integration

Access via `bot.services.llm`. Always pass `guild_id` and `user_id` — usage is auto-tracked in the `llm_usage` table:

```python
response = await self.bot.services.llm.chat(
    message="Hello",
    guild_id=interaction.guild_id,   # required for AI Analytics attribution
    user_id=interaction.user.id,     # required for AI Analytics attribution
    # model defaults to guild settings; override with provider name if needed
)
```

Available models: OpenAI GPT-4o, Anthropic Claude 3, Google `gemini-2.5-pro` / `gemini-2.5-flash`, xAI Grok.

See [docs/GEMINI_CAPABILITIES.md](../docs/GEMINI_CAPABILITIES.md) for Gemini advanced features (image gen, TTS, RAG, caching).

## Key Files

| Purpose | Location |
|---------|----------|
| Bot entry & services | [bot/core/bot.py](../bot/core/bot.py), [bot/services/](../bot/services/) |
| Cog examples | [bot/cogs/status.py](../bot/cogs/status.py) (sample), [bot/cogs/gemini_capabilities_demo.py](../bot/cogs/gemini_capabilities_demo.py) (demo) |
| API routing | [backend/app/api/](../backend/app/api/) |
| Auth & security | [backend/app/core/security.py](../backend/app/core/security.py) |
| Frontend API client | [frontend/app/api-client.ts](../frontend/app/api-client.ts) |
| Permission HOC | [frontend/lib/components/with-permission.tsx](../frontend/lib/components/with-permission.tsx) |
| i18n translations | [frontend/lib/i18n/translations/](../frontend/lib/i18n/translations/) |

## Do NOT Modify (Core Framework)

- `backend/app/core/` - Auth, config, security
- `backend/app/api/auth.py`, `backend/app/api/deps.py`
- `bot/core/` - Bot initialization, loader
- `bot/cogs/guild_sync.py`, `bot/cogs/introspection.py` - Core cogs
- `frontend/app/layout.tsx`, `frontend/lib/auth-context.tsx`
- Existing Alembic migration files in `backend/alembic/versions/`

## Sample/Demo Code (Safe to Replace)

Files marked `*** DEMO CODE ***` or with `__is_demo__ = True` are examples removed by `./init.sh`:
- `bot/cogs/status.py`, `bot/cogs/gemini_capabilities_demo.py`
- `frontend/app/dashboard/[guildId]/test-*`, `gemini-demo/`, `logging/`
