# Discord Bot Platform - Baseline

A production-ready, reusable Discord bot platform supporting multi-server deployments, AI/LLM integration, and horizontal scalability.

## 🎯 What is This?

This is a **baseline platform** for building Discord bots. It provides all the infrastructure, architecture, and common functionality needed for production Discord bots, allowing you to focus on bot-specific features.

**One baseline → Unlimited bots**

## ✨ Key Features

### 🏗️ **Architecture**
- Multi-server support (one bot instance serves multiple Discord servers)
- Horizontal scalability (backend API + Discord bot sharding)
- Network isolation (internet/intranet/dbnet)
- Microservices-ready (frontend, backend, bot, database, Redis)

### 🔐 **Authentication & Authorization**
- Discord OAuth 2.0 authentication
- Per-guild permission management
- Role-based access control
- Developer team elevated access

### 🤖 **AI/LLM Integration**
- **4 LLM Providers**: OpenAI, Google/Gemini, xAI/Grok, Anthropic/Claude
- Function calling & structured output (all providers)
- Image generation & audio support (where available)
- **Comprehensive cost tracking** (prompt tokens, completion tokens, cache tokens)
- Per-guild, per-user, per-cog analytics

### 🔌 **Modularity**
- **Cogs**: Bot-specific commands/events as plug-in modules
- **UI Plugins**: Bot-specific pages dynamically loaded in frontend
- **Dependency Injection**: Clean service access for cogs
- Minimal coupling between baseline and bot-specific code

### 📊 **Observability**
- Structured JSON logging with correlation IDs
- Shard monitoring via Redis
- Health check endpoints (Docker healthchecks)
- LLM usage analytics and cost reporting

### 🧪 **Production-Ready**
- Comprehensive testing suite (unit, integration, E2E, regression)
- Database migrations with Alembic
- API versioning (/v1/)
- Rate limiting
- Security hardening

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Discord Bot Application (get token from Discord Developer Portal)
- Discord OAuth Application (client ID & secret)
- LLM API Keys (OpenAI, Google, Anthropic, xAI - optional)

### 1. Clone the Repository

```bash
git clone <your-baseline-repo-url> my-discord-bot
cd my-discord-bot
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required environment variables:
- `DISCORD_BOT_TOKEN` - Your Discord bot token
- `DISCORD_CLIENT_ID` - OAuth client ID
- `DISCORD_CLIENT_SECRET` - OAuth client secret
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `MAIN_GUILD_ID` - Your developer/company Discord server ID
- LLM API keys (optional)

### 3. Start Services

```bash
docker-compose up -d
```

This starts:
- PostgreSQL (port 5432)
- Redis (port 6379)
- Backend API (port 8000)
- Frontend UI (port 3000)
- Discord Bot

### 4. Run Database Migrations

```bash
docker-compose exec backend alembic upgrade head
```

### 5. Access the UI

Navigate to `http://localhost:3000` and log in with Discord!

---

## 📁 Project Structure

```
baseline/
├── docs/
│   ├── SPECIFICATIONS.md       # Complete technical specifications
│   ├── IMPLEMENTATION_PLAN.md  # 6-phase development plan
│   ├── GETTING_STARTED.md      # Setup guide
│   └── COG_DEVELOPMENT.md      # Cog developer guide
├── backend/
│   ├── api/                    # FastAPI application
│   ├── services/               # Service container, DB, Redis, LLM
│   ├── models/                 # SQLAlchemy models
│   ├── migrations/             # Alembic migrations
│   └── tests/                  # Test suite
├── bot/
│   ├── bot.py                  # Discord bot core
│   ├── cogs/                   # Bot-specific cogs
│   ├── services/               # Injected services
│   └── tests/                  # Bot tests
├── frontend/
│   ├── src/
│   │   ├── app/                # Next.js app router
│   │   ├── components/         # React components
│   │   ├── lib/                # API client, utilities
│   │   └── plugins/            # Bot-specific pages
│   └── tests/                  # Frontend tests
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 🎓 Creating Your First Bot

### Option 1: Fork This Repository

1. Fork this baseline repo
2. Add your bot-specific cogs to `bot/cogs/`
3. Add your bot-specific UI pages to `frontend/src/plugins/`
4. Define bot-specific database tables in `backend/models/`
5. Deploy!

### Option 2: Use as Template

1. Click "Use this template" on GitHub
2. Follow the same steps as Option 1

---

## 📚 Documentation

- **[SPECIFICATIONS.md](docs/SPECIFICATIONS.md)** - Complete technical specs (~1100 lines)
- **[IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)** - 6-phase development plan (12-16 weeks, 89 deliverables)
- **[GETTING_STARTED.md](docs/GETTING_STARTED.md)** - Detailed setup guide
- **[COG_DEVELOPMENT.md](docs/COG_DEVELOPMENT.md)** - How to build cogs (Section 13.0 from specs)

---

## 🏛️ Architecture Overview

### Services

**Frontend (Next.js)**
- Public-facing web UI
- Discord OAuth integration
- Dynamic page loading for bot-specific features
- Guild selector and navigation

**Backend API (FastAPI)**
- RESTful API with versioning
- Authentication & authorization
- Guild settings management
- LLM analytics endpoints

**Discord Bot (discord.py + AutoShardedBot)**
- Multi-server support with sharding
- Dynamic cog loading
- LLM service integration
- Shard status monitoring

**PostgreSQL**
- Multi-tenant data with guild_id scoping
- Alembic migrations
- Connection pooling

**Redis**
- Session storage
- Shard status tracking
- LLM request caching

### Networks

- **internet**: Frontend only (publicly accessible)
- **intranet**: Backend + Bot + Redis
- **dbnet**: Backend + Database

---

## 🧩 Building Cogs

Cogs are self-contained modules that add bot functionality. Here's a minimal example:

```python
from discord.ext import commands
from baseline.services import BotServices

class MyCog(commands.Cog):
    def __init__(self, bot, services: BotServices):
        self.bot = bot
        self.services = services
    
    @commands.slash_command(name="hello")
    async def hello(self, ctx):
        # Use LLM service
        response = await self.services.llm.complete(
            provider="openai",
            model="gpt-4",
            messages=[{"role": "user", "content": "Say hello!"}],
            guild_id=ctx.guild.id,
            cog_name=self.__class__.__name__
        )
        await ctx.respond(response.content, ephemeral=True)

async def setup(bot):
    await bot.add_cog(MyCog(bot, bot.services))
```

See **[COG_DEVELOPMENT.md](docs/COG_DEVELOPMENT.md)** for comprehensive guide.

---

## 🤝 Contributing

This is a baseline platform meant to be forked/cloned for individual bot projects. Improvements to the baseline should be made in your fork and can be selectively merged back.

---

## 📊 Implementation Status

**Phase 1: Core Infrastructure** ⬜ Not Started  
**Phase 2: Authentication & Authorization** ⬜ Not Started  
**Phase 3: Discord Bot Foundation** ⬜ Not Started  
**Phase 4: LLM Integration Module** ⬜ Not Started  
**Phase 5: UI & Settings Management** ⬜ Not Started  
**Phase 6: Testing & Documentation** ⬜ Not Started  

See **[IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)** for detailed roadmap.

---

## 📜 License

[Your License Here - MIT recommended for baseline platforms]

---

## 🙏 Acknowledgments

Built with:
- [discord.py](https://github.com/Rapptz/discord.py)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Next.js](https://nextjs.org/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [TailwindCSS](https://tailwindcss.com/) + [shadcn/ui](https://ui.shadcn.com/)

---

## 📞 Support

For issues with the baseline platform, create an issue in this repository.

For bot-specific questions, refer to the cog development documentation.

---

**Happy Bot Building! 🤖✨**
