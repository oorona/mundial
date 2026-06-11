# Integration Guides

**For AI Assistants and Developers**: These guides explain how to extend the Baseline framework with custom functionality.

---

## Building a Plugin? Start Here

If you are writing new functionality for this framework — a cog, API route, frontend page, or any combination — the **plugin staging workflow is the correct path**:

1. Read **`CLAUDE.md`** (project root) — five golden rules and key file locations. This is the authoritative reference for all framework contracts.
2. Read **[Plugin Staging Workflow](08-plugin-workflow.md)** — the complete, step-by-step guide: template setup, all five component files, `SETTINGS_SCHEMA` reference, validation, and install.
3. Copy `plugins/_template/` to start your plugin.

**Do not** read `docs/PLUGIN_SYSTEM_SPECS.md` or `docs/integration/06-bot-configuration.md` as a substitute — those documents are supplementary references, not the plugin guide, and overlap with `08-plugin-workflow.md`.

---

## All Guides

1. [Adding Bot Cogs](01-adding-cogs.md) — Cog structure, command descriptions, logging
2. [LLM Integration](02-llm-integration.md) — Using `bot.services.llm`
3. [Logging & Environment](03-logging-environment.md) — Structured logging, environment variables
4. [Backend Endpoints](04-backend-endpoints.md) — FastAPI routers, RLS, audit log, security rules
5. [Frontend Pages](05-frontend-pages.md) — Next.js pages, `withPermission`, `apiClient`, design tokens
6. [Bot Configuration](06-bot-configuration.md) — Guild settings, secrets, caching (core framework reference; for plugins use `08`)
7. [Observability](07-observability.md) — Prometheus, Grafana & Loki
8. **[Plugin Staging Workflow](08-plugin-workflow.md)** — **Primary guide for all plugin development**

## Architecture

For a complete understanding of the system design, see:
- [Architecture Documentation](../ARCHITECTURE.md) - System design and plugin architecture

## Common Tasks

### I want to build a complete plugin (LLM-assisted)

→ See [Plugin Staging Workflow](08-plugin-workflow.md)

### I want to add a new Discord command

→ See [Adding Bot Cogs](01-adding-cogs.md)

### I want to use AI/LLM features

→ See [LLM Integration](02-llm-integration.md)

### I want to add a new API endpoint

→ See [Backend Endpoints](04-backend-endpoints.md)

### I want to add a new settings page

→ See [Frontend Pages](05-frontend-pages.md)

### I want to configure my bot

→ See [Bot Configuration](06-bot-configuration.md)

### I want to add logging

→ See [Logging & Environment](03-logging-environment.md)

### I want to set up Prometheus / Grafana / Loki

→ See [Observability](07-observability.md)

## Extension Points Summary

| Component | Extension Point | Guide |
|-----------|----------------|-------|
| **Plugin** | Full workflow (stage → validate → install) | [08-plugin-workflow.md](08-plugin-workflow.md) |
| **Bot** | Add commands | [01-adding-cogs.md](01-adding-cogs.md) |
| **Bot** | Use LLM | [02-llm-integration.md](02-llm-integration.md) |
| **Bot** | **Gemini 3 AI** | [GEMINI_CAPABILITIES.md](../GEMINI_CAPABILITIES.md) |
| **Bot** | Configuration | [06-bot-configuration.md](06-bot-configuration.md) |
| **Backend** | Add API endpoints | [04-backend-endpoints.md](04-backend-endpoints.md) |
| **Frontend** | Add pages | [05-frontend-pages.md](05-frontend-pages.md) |
| **All** | Logging | [03-logging-environment.md](03-logging-environment.md) |
| **Ops** | Observability | [07-observability.md](07-observability.md) |

---

## Gemini 3 AI Capabilities

The framework includes **full Gemini 3 API support** with 13 capabilities:

| Capability | What It Does |
|------------|--------------|
| **Text + Thinking** | Generate text with configurable reasoning depth |
| **Image Generation** | Create images from text prompts |
| **Image Understanding** | Analyze and describe images |
| **Text-to-Speech** | Convert text to natural speech |
| **Embeddings** | Generate vector embeddings |
| **Structured Output** | Get typed JSON responses |
| **Function Calling** | Let AI call your functions |
| **And more...** | URL context, file search, caching, token counting |

### Quick Example

```python
from bot.services.gemini import ThinkingLevel

@app_commands.command()
async def smart_ask(self, interaction, question: str):
    await interaction.response.defer()
    
    result = await self.bot.services.llm.generate_with_thinking(
        prompt=question,
        thinking_level=ThinkingLevel.HIGH,
        guild_id=interaction.guild_id
    )
    
    await interaction.followup.send(result["content"])
```

→ **Full Guide**: [GEMINI_CAPABILITIES.md](../GEMINI_CAPABILITIES.md)

---

## Example: Adding a Complete Feature

Let's say you want to add a "Polls" feature:

### 1. Database Model + Migration (if you need persistence)

```python
# backend/app/models.py — add your model
from app.db.mixins import GuildScopedMixin
from app.db.base import Base

class Poll(GuildScopedMixin, Base):  # GuildScopedMixin adds guild_id + RLS marker
    __tablename__ = "polls"
    id        = Column(BigInteger, primary_key=True, autoincrement=True)
    question  = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

Then generate and apply the migration:
```bash
docker compose exec backend alembic revision --autogenerate -m "add_polls_table"
# Edit the generated file to add RLS (see DEVELOPER_MANUAL.md §6.4)
docker compose exec backend alembic upgrade head
```

`install_plugin.sh` writes the plugin migration entry to `backend/migration_inventory.json` automatically. Only manual step: `docker compose exec backend alembic upgrade head`.

→ Full guide: [DEVELOPER_MANUAL.md §6](../DEVELOPER_MANUAL.md#6-database-architecture-and-extension-guide)

### 2. Bot Cog (Discord Commands)

```python
# bot/cogs/polls.py
@app_commands.command(name="create-poll", description="Create a new poll")
@app_commands.describe(question="Poll question", options="Comma-separated options")
async def create_poll(self, interaction: discord.Interaction, question: str, options: str):
    await interaction.response.defer()
    # Call backend to store poll
    pass
```

→ Full guide: [01-adding-cogs.md](01-adding-cogs.md)

### 3. Backend API (Store Poll Data)

```python
# backend/app/api/polls.py
from app.db.guild_session import get_guild_db  # RLS required for guild data

@router.post("/{guild_id}/polls")
async def create_poll(
    guild_id: int,
    poll: PollCreate,
    db: AsyncSession = Depends(get_guild_db),
):
    # Store in database — RLS ensures this only affects the correct guild
    pass
```

Register the router in `backend/main.py`:
```python
from app.api.polls import router as polls_router
app.include_router(polls_router, prefix=f"{settings.API_V1_STR}/guilds", tags=["polls"])
```

→ Full guide: [04-backend-endpoints.md](04-backend-endpoints.md)

### 4. Frontend Page (View Results)

```typescript
// frontend/app/dashboard/[guildId]/polls/page.tsx
'use client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';
import { useTranslation } from '@/lib/i18n';

function PollsPage() {
    const { t } = useTranslation();
    // Display poll results — use t() for all user-visible strings
    return <h1>{t('polls.title')}</h1>;
}

export default withPermission(PollsPage, PermissionLevel.AUTHORIZED);
```

Add translation strings to **both** `frontend/lib/i18n/translations/en.ts` and `es.ts`:
```typescript
polls: { title: 'Polls' }  // en.ts
polls: { title: 'Encuestas' }  // es.ts
```

→ Full guide: [05-frontend-pages.md](05-frontend-pages.md)

## Best Practices

1. **Read the Architecture Guide First**: Understand the system design
2. **Follow Existing Patterns**: Study existing code before creating new features
3. **Test Locally**: Use `docker compose up -d` to run the full stack
4. **Use TypeScript/Type Hints**: Maintain type safety
5. **Log Important Events**: Use structured logging
6. **Handle Errors**: Always provide user-friendly error messages
7. **Document Your Code**: Add docstrings and comments

## Getting Help

- **Check Examples**: All guides include working code examples
- **Review Existing Code**: Study similar features already implemented
- **Architecture Doc**: See [ARCHITECTURE.md](../ARCHITECTURE.md) for system design
- **README**: See [README.md](../../README.md) for setup instructions

## Quick Reference

### Bot Development

```python
# Import necessary modules
import discord
from discord import app_commands
from discord.ext import commands
import structlog

logger = structlog.get_logger()

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.command()
    async def mycommand(self, interaction: discord.Interaction):
        await interaction.response.send_message("Hello!")

async def setup(bot):
    await bot.add_cog(MyCog(bot))
```

### Backend Development

```python
# Import FastAPI dependencies
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
# Use get_guild_db for any endpoint under /{guild_id}/ — enables Row-Level Security
from app.db.guild_session import get_guild_db
# Use get_db only for global tables (users, shards, app_config — no guild isolation needed)
from app.db.session import get_db

router = APIRouter()

@router.get("/{guild_id}/myendpoint")
async def my_guild_endpoint(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),  # RLS active
):
    return {"message": "Hello from this guild"}
```

### Frontend Development

```typescript
'use client';

import { useState, useEffect } from 'react';
import { apiClient } from '@/app/api-client';
import { withPermission } from '@/lib/components/with-permission';
import { PermissionLevel } from '@/lib/permissions';

function MyPage() {
    const [data, setData] = useState(null);

    useEffect(() => {
        apiClient.getMyData().then(setData).catch(console.error);
    }, []);

    return <div>{/* Your UI */}</div>;
}

export default withPermission(MyPage, PermissionLevel.AUTHORIZED);
```

## Contributing

When adding features to the baseline framework:

1. Follow the established patterns
2. Add tests for new functionality
3. Update documentation
4. Create a migration if modifying database
5. Test with `docker compose up -d` and `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

---

**Need more help?** Check the architecture guide or existing code examples.
