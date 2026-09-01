# Baseline Discord Bot Platform

A production-ready Discord bot framework with authentication, settings management, audit logging, granular permissions, multi-provider LLM integration, and a full admin dashboard.

## Documentation

- **[Developer Manual](docs/DEVELOPER_MANUAL.md)**: The authoritative guide for AI Agents and Developers.
- **[Security Reference](docs/SECURITY.md)**: **Read before deploying.** All 6 permission levels with code examples, security checklist, and production hardening guide.
- **[Architecture](docs/ARCHITECTURE.md)**: High-level system design.
- **[LLM Guide](docs/LLM_USAGE_GUIDE.md)**: How to use the shared LLM service.
- **[Integration Guides](docs/integration/README.md)**: Step-by-step feature development guides.

## Using as a Framework

Clone this repo to start a new bot, then run the initialiser **once** to remove demo/example code:

```bash
chmod +x init.sh
./init.sh
```

This strips all demo pages, cogs, and API routes while leaving the core framework intact. See the [Developer Manual](docs/DEVELOPER_MANUAL.md) for what gets removed and how to build on top of the framework.

## Architecture

- **Backend**: FastAPI with PostgreSQL and Redis
- **Frontend**: Next.js 16 with TypeScript
- **Bot**: discord.py with auto-sharding support

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Discord application (for bot token and OAuth credentials)
  - *Need to create one? Follow the [Discord App Setup Guide](docs/DISCORD_APP_SETUP.md).*

### Setup

See **[SETUP.md](SETUP.md)** for the full step-by-step guide. In brief:

```bash
./setup_secrets.sh                                                        # encryption key + postgres password
docker compose up -d postgres                                             # start DB container
./setup_database.sh --container postgres --user <yourbot> --db <yourbot> # create app user
chmod +x init.sh && ./init.sh                                             # strip demo code
docker compose up                                                         # start everything
```

Then open `http://localhost:3000` — you will be redirected to the Setup Wizard to enter your Discord token and database credentials.

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs

## Common Commands

```bash
docker compose up -d                                                        # Start dev environment
docker compose down                                                         # Stop all services
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d      # Production
docker compose logs -f                                                      # View all logs
docker compose logs -f backend                                              # View backend logs
docker compose exec backend alembic upgrade head                            # Run DB migrations
docker compose restart backend                                              # Restart backend
docker compose restart bot                                                  # Restart bot
docker compose restart frontend                                             # Restart frontend
docker compose down -v                                                      # Stop + remove volumes
```

## Production Deployment

### Using the deployment script

```bash
./scripts/deploy.sh
```

This will:
1. Pull latest changes from git
2. Build and start services with production config
3. Run database migrations
4. Show service status

### Manual deployment

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose exec backend alembic upgrade head
```

## Testing

The framework includes a live integration test suite that runs against the real Docker stack. Tests validate health, security headers, authentication, all 6 permission levels, rate limiting, database isolation, and LLM usage tracking.

```bash
# 1. Start the stack
docker compose up -d

# 2. Run all tests using the interactive test runner
./test.sh

# 3. Or run directly via Docker Compose (one-shot, all suites)
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test-runner

# 4. Run with authenticated tests (requires TEST_API_TOKEN — see below)
TEST_API_TOKEN=your_token docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test-runner

# 5. Run specific suites only
TEST_SUITES=01,03,07 docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test-runner
```

**Output**: Each test shows `[PASS/FAIL/SKIP]  test name  response_time_ms` in real time, followed by a summary table with per-suite stats (pass counts, avg/max response times).

**Test suites:**
- `01 Health` — all services reachable, response times within limits
- `02 Security Headers` — all required headers present (CSP, HSTS, X-Frame-Options, etc.)
- `03 Authentication` — OAuth endpoints, token validation, rejection of invalid auth
- `04 Security Levels` — L0–L5 access control enforced on every endpoint
- `05 Rate Limiting` — nginx burst protection verified
- `06 Backwards Compatibility` — API response shape contract tests
- `07 Database` — RLS isolation, schema separation, migration state
- `08 LLM` — usage tracking, provider routing, cost attribution

**Authenticated tests (`TEST_API_TOKEN`)**: Suites 03, 06, and 08 include tests that require a valid user JWT. Without the token these tests are **skipped** (not failed). To obtain a token:
1. Log in to the frontend dashboard in your browser
2. Open DevTools → Application → Local Storage → select your site's origin
3. Copy the value of the `access_token` key
4. Pass it as `TEST_API_TOKEN=<value>` when running tests

Tokens expire after 7 days. If you see `401 Session expired or invalid`, get a fresh token by logging in again.

Use `./test.sh` for an interactive menu to run individual suites or groups. See [`tests/runner/`](tests/runner/) for source and [`docker-compose.test.yml`](docker-compose.test.yml) for configuration.

## Development

### Project Structure

```
baseline/
├── backend/          # FastAPI application
│   ├── app/
│   │   ├── api/      # API endpoints
│   │   ├── core/     # Core configuration
│   │   ├── db/       # Database setup
│   │   └── models.py # SQLAlchemy models
│   └── alembic/      # Database migrations
├── bot/              # Discord bot
│   ├── cogs/         # Bot commands
│   ├── core/         # Bot core logic
│   └── services/     # LLM & background services
├── frontend/         # Next.js application
│   └── app/          # App router pages
├── docs/             # Documentation
│   └── integration/  # Feature development guides
├── secrets/          # Secret files (not in git)
├── init.sh           # New-bot initialiser (run once after clone)
└── docker-compose.yml
```

### LLM / AI Integration

The framework includes a multi-provider LLM service available to all bot cogs via `bot.services.llm`:

| Provider | Models |
|----------|--------|
| **Google Gemini** | Gemini 2.5 Pro/Flash, Gemini 2.0 Flash |
| **OpenAI** | GPT-4o, GPT-4 |
| **Anthropic** | Claude 3 Opus/Sonnet/Haiku |
| **xAI** | Grok |

**Quick usage in a cog:**
```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.llm = bot.services.llm

    @app_commands.command()
    async def ask(self, interaction, question: str):
        await interaction.response.defer()
        response = await self.llm.chat(message=question)
        await interaction.followup.send(response)
```

All LLM calls are automatically tracked in the `llm_usage` table (tokens, cost, latency, guild/user attribution) and visible in the AI Analytics dashboard. See [docs/LLM_USAGE_GUIDE.md](docs/LLM_USAGE_GUIDE.md) for full usage.

### Adding a Database Migration

```bash
# Auto-generate migration
docker compose exec backend alembic revision --autogenerate -m "description"

# Apply migration
docker compose exec backend alembic upgrade head
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
```

## Configuration

There is no `.env` file. Secrets are managed through two mechanisms:

1. **`secrets/encryption_key`** — generated by `./setup_secrets.sh`, delivered to containers as a Docker secret (never on disk inside the container).
2. **Setup Wizard** — all other secrets (Discord token, DB password, API keys) are entered once through the browser and stored AES-256-GCM encrypted in a Docker volume.

See `.env.example` for the small number of non-secret environment variables that can be set (e.g. `NEXT_PUBLIC_APP_NAME`, port overrides).

## License

MIT
