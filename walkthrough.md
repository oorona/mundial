# Baseline Framework — Walkthrough

This document gives a high-level tour of what the framework includes and where to find things. For task-specific guides, see `docs/integration/`.

---

## Architecture

Three Docker services behind an nginx gateway:

| Service | Stack | Port |
|---------|-------|------|
| **backend** | FastAPI + PostgreSQL + Redis | 8000 |
| **bot** | discord.py (auto-sharded) | 8080 (health) |
| **frontend** | Next.js 16 + TypeScript | 3000 |

Traffic flows: `Internet → nginx → Backend ← Bot / Frontend (intranet)`

---

## What is Included

### Bot
- Auto-sharded discord.py bot with Cog autoloading from `bot/cogs/`
- LLM service (`bot.services.llm`) supporting OpenAI, Anthropic, Google Gemini, and xAI Grok
- Shared `aiohttp.ClientSession` (`bot.session`) for all backend HTTP calls
- Shard health monitoring
- Per-guild settings fetched from backend at command time

### Backend
- Discord OAuth2 login + session management (Redis, HTTP-only cookies)
- PostgreSQL with **Row-Level Security** — guild data is strictly isolated
- Guild sync: bot registers guilds in the database on join/leave
- Audit log for every settings mutation
- 7-tier permission model (L0 Public → L6 Developer)
- Full Gemini AI API surface (text, images, TTS, embeddings, RAG, function calling, caching)
- LLM usage tracking per guild and per user

### Frontend
- Next.js 16 dashboard with per-guild settings, audit logs, permissions, shard monitor
- `withPermission` HOC enforces permission levels on every page
- Custom i18n system (English + Spanish) — all strings via `t('key')`
- API client in `frontend/app/api-client.ts` — never call backend URLs directly

---

## Running the Platform

```bash
docker compose up -d              # Start all services
docker compose logs -f            # Tail all logs
docker compose restart bot        # Restart a single service
```

Visit:
- **Frontend**: http://localhost:3000
- **Backend API docs**: http://localhost:8000/docs
- **Bot health**: http://localhost:8080/health

---

## Extending the Framework

The framework is designed to be extended by adding Cogs, backend routers, and frontend pages. An LLM coding assistant can generate correct, framework-compliant code by reading the docs in this order:

1. `CLAUDE.md` — mandatory rules every AI assistant must follow
2. `docs/integration/01-adding-cogs.md` — add Discord slash commands
3. `docs/integration/02-llm-integration.md` — use AI features in cogs
4. `docs/integration/04-backend-endpoints.md` — add REST API endpoints
5. `docs/integration/05-frontend-pages.md` — add dashboard pages
6. `docs/integration/06-bot-configuration.md` — per-guild settings schema
7. `docs/API_ROUTES.md` — full API reference

---

## Key Files

| Purpose | Location |
|---------|----------|
| Bot entry + services | `bot/core/bot.py`, `bot/services/` |
| Cog examples | `bot/cogs/status.py`, `bot/cogs/gemini_capabilities_demo.py` |
| API routers | `backend/app/api/` |
| Auth & security | `backend/app/core/security.py` |
| Frontend API client | `frontend/app/api-client.ts` |
| Permission HOC | `frontend/lib/components/with-permission.tsx` |
| i18n translations | `frontend/lib/i18n/translations/` |
