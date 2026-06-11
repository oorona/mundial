# API Routing Reference

All backend API endpoints are prefixed with `/api/v1`.

## Rate Limiting

| Category | Limit |
|----------|-------|
| Authentication | 5–10 req/min |
| LLM generation | 10–20 req/min |
| General API | 20 req/min |

---

## Authentication — `/api/v1/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/auth/discord/login` | — | Initiate Discord OAuth2 flow |
| `GET` | `/auth/discord/callback` | — | OAuth2 callback (sets session cookie) |
| `GET` | `/auth/me` | Session | Get current authenticated user |
| `POST` | `/auth/logout` | Session | Invalidate current session |
| `POST` | `/auth/logout-all` | Session | Invalidate all sessions for this user |
| `GET` | `/auth/discord-config` | — | Public Discord OAuth config (client ID, scopes) |

---

## Users — `/api/v1/users`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/users/me/settings` | Session | Get current user's preferences (language, etc.) |
| `PUT` | `/users/me/settings` | Session | Update current user's preferences |

---

## Guilds — `/api/v1/guilds`

### Guild Management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/guilds` | Session | List all guilds the current user has access to. Each item includes `bot_not_added: bool` — `true` for servers where the user is an admin but the bot has not been invited yet. The frontend uses this to display an "Add Bot" prompt. |
| `POST` | `/guilds` | Bot internal | Register or update a guild (called by bot on join) |
| `GET` | `/guilds/{guild_id}` | Session | Get guild details |
| `GET` | `/guilds/{guild_id}/public` | — | Public guild info (name, member count — no PII) |

### Settings

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/guilds/{guild_id}/settings` | Session | Get guild settings |
| `PUT` | `/guilds/{guild_id}/settings` | Session (owner/admin) | Update guild settings |

Body for PUT: `{ "settings": { "key": "value", ... } }`

### Permissions — Authorized Users

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/guilds/{guild_id}/authorized-users` | Session | List users authorized for this guild |
| `POST` | `/guilds/{guild_id}/authorized-users` | Session (owner) | Add an authorized user |
| `DELETE` | `/guilds/{guild_id}/authorized-users/{user_id}` | Session (owner) | Remove an authorized user |

Body for POST: `{ "user_id": 123456789 }`

### Permissions — Authorized Roles

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/guilds/{guild_id}/authorized-roles` | Session | List authorized Discord roles |
| `POST` | `/guilds/{guild_id}/authorized-roles` | Session (owner) | Add an authorized role |
| `DELETE` | `/guilds/{guild_id}/authorized-roles/{role_id}` | Session (owner) | Remove an authorized role |

### Audit Logs

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/guilds/{guild_id}/audit-logs` | Session (admin) | List audit log entries for this guild |
| `DELETE` | `/guilds/{guild_id}/audit-logs` | Session (owner or admin) | Purge audit log entries |

Query params for `GET`: `limit`, `offset`, `action` (filter by action type)

Query params for `DELETE` (all optional, at least one must be supplied to limit scope):

| Param | Type | Description |
|-------|------|-------------|
| `older_than_days` | integer ≥ 1 | Delete entries older than N days |
| `before` | ISO date string | Delete entries before this date (e.g. `2025-01-01`) |
| `after` | ISO date string | Delete entries after this date |

Omitting all params deletes **all** logs for the guild. Returns `{"deleted": <count>}`.

### Discord Data (Live from Discord API)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/guilds/{guild_id}/channels` | Session | List guild channels (from Discord API) |
| `GET` | `/guilds/{guild_id}/roles` | Session | List guild roles (from Discord API) |
| `GET` | `/guilds/{guild_id}/members/search` | Session | Search guild members (from Discord API) |

---

## Shards — `/api/v1/shards`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/shards` | Session (admin) | List all shards with status and latency |
| `GET` | `/shards/{shard_id}` | Session (admin) | Get specific shard details |

---

## Bot Info — `/api/v1/bot-info`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/bot-info/public` | — | Public bot info (name, avatar, invite URL) |
| `POST` | `/bot-info/report` | Bot internal | Bot posts its runtime info (used by dashboard) |
| `GET` | `/bot-info/report` | Session (admin) | Get latest bot runtime report |
| `GET` | `/bot-info/settings-schema` | Session | Get the `SETTINGS_SCHEMA` from all loaded cogs |

---

## Commands — `/api/v1/commands`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/commands/` | Session | Get cached slash command list (Command Reference page) |
| `POST` | `/commands/refresh` | Session (admin) | Re-fetch commands from Discord API and update cache. Returns 503 only if `DISCORD_BOT_TOKEN` or `DISCORD_CLIENT_ID` are missing. An empty command list (no cogs registered yet) is treated as success. |

---

## LLM — `/api/v1/llm`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/llm/generate` | Session | Generate text with the configured LLM |
| `POST` | `/llm/chat` | Session | Send a chat message and get a response |
| `POST` | `/llm/structured` | Session | Get a structured JSON response |
| `POST` | `/llm/tools` | Session | Function/tool calling |
| `GET` | `/llm/stats` | Session (admin) | LLM usage analytics (tokens, cost, per-guild breakdown) |
| `DELETE` | `/llm/usage` | Session (developer) | Purge LLM usage logs and aggregated summaries |

Query params for `DELETE` (all optional):

| Param | Type | Description |
|-------|------|-------------|
| `older_than_days` | integer ≥ 1 | Delete records older than N days |
| `before` | ISO date string | Delete records before this date |
| `after` | ISO date string | Delete records after this date |

Returns `{"deleted": <usage_count>, "summaries_deleted": <summary_count>}`.

---

## Config — `/api/v1/config`

Platform-level configuration. **L6 Developer access required** for write operations.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/config/settings` | Session (admin) | Get all platform config settings |
| `GET` | `/config/settings/database` | Session (admin) | Get database-related settings |
| `GET` | `/config/settings/{key}` | Session (admin) | Get a specific config key |
| `PUT` | `/config/settings` | Session (developer) | Update config settings |
| `POST` | `/config/settings/refresh` | Session (developer) | Reload config from database |
| `DELETE` | `/config/settings/{key}` | Session (developer) | Delete a config key |
| `GET` | `/config/api-keys` | Session (developer) | List configured API key names (never values) |
| `PUT` | `/config/api-keys` | Session (developer) | Update API keys (via Setup Wizard) |

---

## Database Management — `/api/v1/database`

**L6 Developer access required** for all write operations.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/database/info` | Session (developer) | Database info (version, size, table counts) |
| `GET` | `/database/migrations` | Session (developer) | List Alembic migration history |
| `POST` | `/database/migrations/upgrade` | Session (developer) | Run `alembic upgrade head` |
| `POST` | `/database/migrations/upgrade-to` | Session (developer) | Run `alembic upgrade <revision>` |
| `POST` | `/database/test-connection` | Session (developer) | Test database connectivity |
| `GET` | `/database/validate` | Session (developer) | Validate schema against models |
| `GET` | `/database/migration-history` | Session (developer) | Full Alembic migration history |

---

## Platform — `/api/v1/platform`

Internal service health and cross-service status.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/platform/settings` | Session (developer) | Platform-level settings |
| `PUT` | `/platform/settings` | Session (developer) | Update platform settings |
| `GET` | `/platform/db-status` | Session (admin) | Database health status |
| `POST` | `/platform/heartbeat` | Bot internal | Bot posts heartbeat (used for health tracking) |
| `GET` | `/platform/frontend-status` | — | Frontend service health |
| `GET` | `/platform/backend-status` | — | Backend service health |

---

## Setup — `/api/v1/setup`

Setup Wizard endpoints. Used during initial configuration to store secrets encrypted.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| (varies) | `/setup/...` | Developer only | Initial setup wizard steps |

---

## Instrumentation — `/api/v1/instrumentation`

Internal Prometheus metrics collection and purge. **L6 Developer access required** for stats and purge.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/instrumentation/card-click` | Session | Record a dashboard card click |
| `POST` | `/instrumentation/bot-command` | Internal | Record a bot command invocation |
| `POST` | `/instrumentation/guild-event` | Internal | Record a guild join/leave event |
| `GET` | `/instrumentation/stats` | Session (developer) | Aggregated stats (guild growth, card usage, commands, API perf) |
| `GET` | `/instrumentation/metrics` | Internal network only | Prometheus text-format scrape endpoint |
| `DELETE` | `/instrumentation/data` | Session (developer) | Purge metric records |

Query params for `DELETE`:

| Param | Type | Description |
|-------|------|-------------|
| `older_than_days` | integer ≥ 1 | Delete records older than N days |
| `before` | ISO date string | Delete records before this date |
| `after` | ISO date string | Delete records after this date |
| `tables` | string | Comma-separated table keys or `all` (default). Valid keys: `guild_events`, `card_usage`, `bot_commands`, `request_metrics` |

Returns `{"deleted": {"guild_events": N, "card_usage": N, "bot_commands": N, "request_metrics": N}}`.

---

## Health Check

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Returns `{"status": "ok"}` |

---

## Gemini AI Endpoints — `/api/v1/gemini`

### Text Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gemini/generate` | Generate text with configurable thinking depth |
| `POST` | `/gemini/count-tokens` | Count tokens before sending |

### Image

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gemini/image-generate` | Generate images from a text prompt |
| `POST` | `/gemini/image-edit` | Edit an existing image |
| `POST` | `/gemini/image-compose` | Combine multiple images |

### Audio

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gemini/tts` | Text-to-speech (single speaker) |
| `POST` | `/gemini/tts-multi` | Text-to-speech (multi-speaker) |
| `POST` | `/gemini/audio-transcribe` | Speech-to-text |

### Embeddings and Structured Output

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gemini/embeddings` | Generate vector embeddings |
| `POST` | `/gemini/structured-output` | Get a typed JSON response |

### Function Calling

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gemini/function-calling` | Execute function calling with tools |
| `GET` | `/gemini/function-calling/scenarios` | Predefined demo scenarios |

Key params: `mode` (AUTO/ANY/NONE/VALIDATED), `allowed_functions`, `parallel_tool_calls`, `auto_execute`

### Grounding

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gemini/google-search` | Generate with Google Search grounding |
| `POST` | `/gemini/url-context` | Include web content as context |

### Context Caching (up to 75% cost savings)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/gemini/cache-info` | Cache types, model requirements, pricing |
| `POST` | `/gemini/cache-create` | Create a cache (text content or file URI) |
| `POST` | `/gemini/cache-query` | Query using a cached context |
| `GET` | `/gemini/cache-list` | List all active caches with TTL remaining |
| `GET` | `/gemini/cache-get/{name}` | Get details for a specific cache |
| `POST` | `/gemini/cache-update` | Update cache TTL or expiry |
| `DELETE` | `/gemini/cache-delete/{name}` | Delete a cache |

Minimum tokens: Flash = 1,024 / Pro = 4,096

### File Search (RAG)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gemini/file-search-store` | Create a file search store |
| `GET` | `/gemini/file-search-stores` | List all stores |
| `GET` | `/gemini/file-search-stores/{name}` | Get store details |
| `DELETE` | `/gemini/file-search-stores/{name}` | Delete store (`?force=true` to confirm) |
| `POST` | `/gemini/file-search-upload` | Upload document with chunking config |
| `POST` | `/gemini/file-search-query` | Semantic search with optional metadata filter |
| `GET` | `/gemini/file-search-documents/{store}` | List documents in a store |
| `DELETE` | `/gemini/file-search-documents/{name}` | Delete a specific document |

---

## Frontend Routes

All frontend routes are served by Next.js from `/dashboard/`:

### Global Dashboard

| Route | Permission | Description |
|-------|-----------|-------------|
| `/` | Public | Home / landing page |
| `/dashboard` | L2 User | Dashboard home (guild picker) |
| `/dashboard/account` | L2 User | User account and preferences |
| `/dashboard/status` | L5 Owner | Shard monitor |
| `/dashboard/platform` | L6 Developer | Platform management |
| `/dashboard/config` | L6 Developer | Platform config editor |
| `/dashboard/database` | L6 Developer | Database management |
| `/dashboard/developer` | L6 Developer | Developer tools |
| `/dashboard/instrumentation` | L6 Developer | Metrics and observability |
| `/dashboard/ai-analytics` | L5 Owner | LLM usage analytics |
| `/dashboard/llm-configs` | L6 Developer | LLM provider configuration |
| `/dashboard/bot-health` | L5 Owner | Bot health dashboard |

### Per-Guild Dashboard

| Route | Permission | Description |
|-------|-----------|-------------|
| `/dashboard/[guildId]/settings` | L3 Authorized | Guild settings |
| `/dashboard/[guildId]/permissions` | L4 Administrator | Authorized users and roles |
| `/dashboard/[guildId]/audit-logs` | L3 Authorized | Audit log viewer |
| `/dashboard/[guildId]/plugins` | L3 Authorized | Plugin / cog management |
| `/dashboard/[guildId]/card-visibility` | L3 Authorized | Dashboard card visibility settings |

---

## Important Notes

1. **Frontend API calls**: Always use `apiClient` from `frontend/app/api-client.ts`. Never call backend URLs directly from browser code.

2. **CORS**: Backend accepts requests from `http://localhost:3000` in development and the configured frontend URL in production.

3. **Authentication**: All endpoints except login, callback, public, and health require a valid session cookie.

4. **Guild data**: Any endpoint under `/{guild_id}/` uses `get_guild_db`, which activates PostgreSQL Row-Level Security. A query bug cannot leak data between guilds.

5. **Development URLs**:
   - Frontend: `http://localhost:3000`
   - Backend API + Swagger UI: `http://localhost:8000/docs`
   - Bot health: `http://localhost:8080/health`
