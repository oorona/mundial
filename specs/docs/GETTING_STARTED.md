# Getting Started with Discord Bot Platform Baseline

This guide walks you through setting up the baseline bot platform from scratch.

## Prerequisites

Before you begin, ensure you have:

- **Docker Desktop** (or Docker + Docker Compose)
- **Git**
- **Node.js 18+** (for local frontend development)
- **Python 3.10+** (for local backend development)
- **Discord Developer Account**

---

## Step 1: Create Discord Application

### 1.1 Create Bot Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Name your application (e.g., "My Bot Platform")
4. Go to "Bot" section
5. Click "Add Bot"
6. **Save the bot token** (you'll need this for `DISCORD_BOT_TOKEN`)
7. Enable these **Privileged Gateway Intents**:
   - Server Members Intent
   - Message Content Intent
8. Under "OAuth2 → General":
   - Add redirect URL: `http://localhost:3000/auth/callback` (for local dev)
   - **Save client ID and client secret**

### 1.2 Invite Bot to Your Server

1. Go to "OAuth2 → URL Generator"
2. Select scopes:
   - `bot`
   - `applications.commands`
3. Select bot permissions (Administrator recommended for development)
4. Copy the generated URL
5. Open URL in browser and invite bot to your test server
6. **Save your server ID** (enable Developer Mode in Discord, right-click server, Copy ID)

---

## Step 2: Get LLM API Keys (Optional)

If you want to use LLM features, get API keys from:

- **OpenAI**: https://platform.openai.com/api-keys
- **Google/Gemini**: https://makersuite.google.com/app/apikey
- **Anthropic/Claude**: https://console.anthropic.com/
- **xAI/Grok**: (when available)

---

## Step 3: Clone and Configure

### 3.1 Clone Repository

```bash
# Clone the baseline
git clone <your-baseline-repo-url> my-discord-bot
cd my-discord-bot

# Or if starting from scratch, create new repo
git init my-discord-bot
cd my-discord-bot
```

### 3.2 Create Environment File

```bash
cp .env.example .env
```

### 3.3 Edit `.env` File

```bash
# Discord Bot
DISCORD_BOT_TOKEN=your_bot_token_here

# Discord OAuth
DISCORD_CLIENT_ID=your_oauth_client_id
DISCORD_CLIENT_SECRET=your_oauth_client_secret
DISCORD_REDIRECT_URI=http://localhost:3000/auth/callback

# Main/Developer Server (your test server)
MAIN_GUILD_ID=your_server_id_here

# Database
DATABASE_URL=postgresql://botuser:botpassword@postgres:5432/botdb

# Redis
REDIS_URL=redis://redis:6379/0

# Backend API
API_SECRET_KEY=generate_a_random_secret_key_here
API_CORS_ORIGINS=http://localhost:3000

# Health Check
HEALTH_HOST=0.0.0.0
HEALTH_PORT=8080

# LLM Provider API Keys (optional)
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
XAI_API_KEY=...

# LLM Configuration
LLM_DEFAULT_PROVIDER=openai
LLM_MAX_RETRIES=3
LLM_TIMEOUT_SECONDS=60
```

**Generate secret key:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Step 4: Start Docker Services

### 4.1 Build and Start Services

```bash
docker-compose up -d
```

This starts:
- **PostgreSQL** (postgres:5432)
- **Redis** (redis:6379)
- **Backend API** (backend:8000)
- **Frontend** (frontend:3000)
- **Discord Bot** (bot)

### 4.2 Verify Services

```bash
# Check all services are running
docker-compose ps

# Check backend logs
docker-compose logs backend

# Check bot logs
docker-compose logs bot

# Check frontend logs
docker-compose logs frontend
```

### 4.3 Health Checks

```bash
# Backend API health
curl http://localhost:8000/api/v1/health

# Bot health
curl http://localhost:8080/health
```

---

## Step 5: Initialize Database

### 5.1 Run Migrations

```bash
docker-compose exec backend alembic upgrade head
```

This creates all baseline tables:
- `guilds`
- `authorized_users`
- `guild_settings`
- `llm_usage`
- `llm_model_pricing`

### 5.2 Seed Model Pricing (Optional)

```bash
docker-compose exec backend python scripts/seed_llm_pricing.py
```

---

## Step 6: Test the Bot

### 6.1 Verify Bot is Online

In your Discord server, you should see the bot online.

### 6.2 Test Status Command

In Discord, type:
```
/status
```

You should see an ephemeral message with bot status, uptime (human-readable), shard info, etc.

---

## Step 7: Access the Web UI

### 7.1 Open Frontend

Navigate to: http://localhost:3000

### 7.2 Log In with Discord

1. Click "Login with Discord"
2. Authorize the application
3. You'll be redirected back to the UI
4. You should see your accessible guilds (servers where you added the bot)

### 7.3 Explore Settings

1. Select a guild from the dropdown
2. Navigate to "Settings"
3. Try changing some settings
4. Click "Save"

---

## Step 8: Create Your First Cog

### 8.1 Create Cog File

```bash
# Create a new cog
touch bot/cogs/my_first_cog.py
```

### 8.2 Write Cog Code

```python
# bot/cogs/my_first_cog.py
from discord.ext import commands

class MyFirstCog(commands.Cog):
    """My first bot cog!"""
    
    def __init__(self, bot, services):
        self.bot = bot
        self.services = services
    
    @commands.slash_command(name="ping", description="Ping the bot")
    async def ping(self, ctx):
        """Simple ping command"""
        await ctx.respond(f"Pong! Latency: {round(self.bot.latency * 1000)}ms", ephemeral=True)
    
    @commands.slash_command(name="ai", description="Ask AI a question")
    async def ask_ai(self, ctx, question: str):
        """Use LLM to answer a question"""
        await ctx.defer(ephemeral=True)
        
        try:
            response = await self.services.llm.complete(
                provider="openai",
                model="gpt-4",
                messages=[{"role": "user", "content": question}],
                guild_id=ctx.guild.id,
                user_id=ctx.author.id,
                cog_name=self.__class__.__name__
            )
            
            await ctx.followup.send(
                f"**Question:** {question}\n\n**Answer:** {response.content}",
                ephemeral=True
            )
        except Exception as e:
            await ctx.followup.send(f"Error: {str(e)}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MyFirstCog(bot, bot.services))
```

### 8.3 Reload Bot

```bash
docker-compose restart bot
```

### 8.4 Test Your Cog

In Discord:
```
/ping
/ai question: What is the capital of France?
```

---

## Step 9: View LLM Usage

### 9.1 Check Database

```bash
docker-compose exec postgres psql -U botuser -d botdb -c "SELECT * FROM llm_usage ORDER BY created_at DESC LIMIT 5;"
```

You should see your LLM requests with cost tracking!

### 9.2 View in UI (Future)

Once shard monitor is built, you'll see LLM usage analytics in the UI.

---

## Step 10: Development Workflow

### 10.1 Local Development

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Bot:**
```bash
cd bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py
```

### 10.2 Running Tests

```bash
# Backend tests
docker-compose exec backend pytest

# Frontend tests
docker-compose exec frontend npm test

# Bot tests
docker-compose exec bot pytest
```

### 10.3 Database Migrations

**Create migration:**
```bash
docker-compose exec backend alembic revision --autogenerate -m "Add my new table"
```

**Apply migration:**
```bash
docker-compose exec backend alembic upgrade head
```

**Rollback:**
```bash
docker-compose exec backend alembic downgrade -1
```

---

## Step 11: Adding Bot-Specific Features

### 11.1 Add Database Tables

Create migration for your bot-specific tables:

```python
# In Alembic migration
def upgrade():
    op.create_table(
        'my_bot_data',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('guild_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('data', sa.String(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'))
    )
```

### 11.2 Add UI Pages

Create frontend plugin:

```typescript
// frontend/src/plugins/mybot/routes.ts
export const myBotRoutes = [
  {
    path: '/guilds/:guildId/my-feature',
    component: lazy(() => import('./MyFeaturePage'))
  }
]

export const myBotNavItems = [
  {
    label: 'My Feature',
    icon: Star,
    path: '/my-feature'
  }
]
```

### 11.3 Add API Endpoints

```python
# backend/api/routes/mybot.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/mybot", tags=["MyBot"])

@router.get("/guilds/{guild_id}/data")
async def get_my_data(guild_id: int):
    # Your logic here
    return {"data": "example"}
```

---

## Troubleshooting

### Bot Not Connecting

1. Check `DISCORD_BOT_TOKEN` is correct
2. Verify bot has proper intents enabled
3. Check bot logs: `docker-compose logs bot`

### Database Connection Error

1. Verify PostgreSQL is running: `docker-compose ps postgres`
2. Check `DATABASE_URL` format
3. Test connection: `docker-compose exec postgres psql -U botuser -d botdb`

### Frontend OAuth Error

1. Verify `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET`
2. Check redirect URI matches in Discord Developer Portal
3. Ensure `DISCORD_REDIRECT_URI` matches

### LLM Calls Failing

1. Verify API keys are set
2. Check API key validity
3. Review LLM service logs
4. Ensure internet connectivity from backend

---

## Next Steps

1. ✅ Complete Phase 1 tasks from Implementation Plan
2. 📖 Read [COG_DEVELOPMENT.md](COG_DEVELOPMENT.md) for advanced patterns
3. 🧪 Write tests for your cogs
4. 🎨 Customize frontend theme
5. 🚀 Deploy to production (see deployment guide)

---

## Resources

- **Discord.py Documentation**: https://discordpy.readthedocs.io/
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Next.js Documentation**: https://nextjs.org/docs
- **SQLAlchemy Documentation**: https://docs.sqlalchemy.org/

---

**Need Help?** Create an issue in the repository or check the troubleshooting section.

**Happy Coding! 🎉**
