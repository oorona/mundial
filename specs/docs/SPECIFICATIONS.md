# Baseline Discord Bot Platform Specification

## 1.0 Platform Overview

This document defines the common architecture, infrastructure, and core functionality for a reusable Discord bot platform. This baseline supports multiple bot implementations, each with bot-specific functionality added through modular cogs (backend) and dynamically loaded pages (frontend).

The platform is designed for multi-server deployments, horizontal scalability, and production-grade reliability.

***

## 2.0 Architectural Decisions

These fundamental decisions guide the baseline's design and deployment strategy:

* **AD-1: Multi-Repository Strategy**
    Each bot implementation is maintained in a separate Git repository. The baseline serves as a forkable/clonable template that bot projects are based on. Updates to the baseline can be merged into bot repositories as needed.

* **AD-2: Fork/Clone Deployment Model**
    New bot projects are created by forking or cloning the baseline repository. Each bot maintains its own copy of baseline code, allowing customization while benefiting from baseline improvements through selective merging.

* **AD-3: Shared Database Instance with Separate Users**
    All bots use the same PostgreSQL instance but with different database users and/or schemas for security isolation. This reduces operational overhead while maintaining data separation.

***

## 3.0 Core Architecture Principles

* **Modularity**: Bot-specific functionality implemented via dynamically loaded cogs and UI pages
* **Multi-Tenancy**: Support multiple Discord servers (guilds) with complete data isolation
* **Scalability**: Horizontal scaling for both backend API and Discord bot (sharding)
* **Security**: Network isolation, OAuth authentication, role-based access control
* **Observability**: Health checks, shard monitoring, status commands

***

## 4.0 Functional Requirements

### 4.1 Authentication & Authorization

* **FR-1: Discord OAuth 2.0 Authentication**
    The web UI shall be protected by Discord OAuth 2.0. Users authenticate with their Discord account. The frontend implements an OAuth callback endpoint to exchange codes with the backend for access tokens.

* **FR-2: Bot Installation Tracking**
    When the bot joins a new guild (via `on_guild_join` event), the system shall:
    - Record guild ID, guild name, and the user who added the bot (via audit logs if available)
    - Automatically grant that user initial UI access for that guild
    - Store this information in the database for permission management

* **FR-3: UI Access Control and Delegation**
    The system implements hierarchical UI access control (independent of Discord permissions):
    
    **Initial Authorized User:**
    - The user who adds the bot becomes the initial authorized user for that guild
    - Only this user can initially access the UI for their guild
    
    **Permission Delegation:**
    - Authorized users can grant UI access to other guild members through the web interface
    - Delegated users have the same UI access as the initial user for that guild
    - Users can only access UI features for guilds they're authorized for
    
    **Developer Team Access:**
    - Users who are members of a specific "main" Discord server (configured via environment) have elevated access to view the Shard Status Monitor across all guilds

* **FR-4: UI Access Permission Management**
    The UI provides an interface for authorized users to manage UI access:
    - Display current authorized users for the guild
    - Grant UI access to other guild members (via Discord API integration)
    - Revoke UI access from delegated users (cannot revoke the initial user)
    - Permission changes take effect immediately

### 3.2 Multi-Server Support

* **FR-5: Multi-Server Architecture**
    The bot supports multiple Discord servers simultaneously:
    - Bot can be added to unlimited Discord servers
    - All database tables storing guild-specific data include `guild_id` column
    - Complete data isolation between guilds
    - All queries scoped by `guild_id`

* **FR-6: Per-Guild Configuration**
    Bot configuration is per-guild rather than global:
    - Each guild has independent settings stored in the database
    - Settings configurable through the web UI
    - No hard-coded guild IDs in environment variables (except the main/developer server)

### 4.3 Network Architecture & Security

*   **FR-EXT-1: Hidden Backend Topology**
    To ensure maximum security, the backend API is **completely isolated** from the public internet.
    - **Intranet Only**: The backend container resides on a private `intranet` Docker network. It is NOT accessible directly from the browser.
    - **Frontend Proxy**: All client-side API requests MUST go through the Next.js Frontend (e.g., `/api/v1/...`). The Frontend proxies these requests to the backend container.
    - **Guest Mode**: The Frontend supports unauthenticated "Guest" access for specific public pages, rendering limited UI without requiring a user session.

### 4.4 Dependency Injection & Services

* **FR-7: Service Container for Cogs**
    The baseline shall provide a dependency injection system for cogs:
    - A `BotServices` class provides access to database, Redis, config, API client, and LLM service
    - Cogs receive the service container on initialization
    - Services are injected rather than imported directly, ensuring loose coupling
    - Example: `def __init__(self, bot, services: BotServices)`

### 4.4 Dynamic Module Loading

* **FR-8: Dynamic Cog Loading**
    The Discord bot shall dynamically load cogs from a designated directory:
    - Cogs implement bot-specific commands and event handlers
    - Cogs must be loosely coupled with minimal dependencies on baseline code
    - Cogs can be added/removed without modifying baseline bot code
    - Cog loading errors shall not crash the bot

* **FR-9: Dynamic UI Page Loading**
    The frontend shall support dynamic page loading for bot-specific features:
    - Bot-specific pages/routes can be added without modifying baseline frontend code
    - Page components are isolated and self-contained
    - Baseline provides routing framework and common components

* **FR-10: Frontend Plugin Registry**
    The frontend shall provide a plugin registration system:
    - Bot-specific pages register routes and navigation items
    - Components are lazy-loaded for performance
    - Navigation sidebar dynamically built from registered plugins
    - Example: `{ routes: [...], navItems: [...] }`

### 4.5 Common UI Pages

* **FR-11: Settings Management Page (Common)**
    All bots include a Settings page where authorized users can configure:
    - Dynamic list of settings specific to each bot implementation
    - Settings stored per-guild in database
    - Settings schema defined by bot-specific code
    - Common UI framework for rendering settings forms

* **FR-12: Settings Schema Validation**
    Settings shall be validated using Pydantic models:
    - Each bot defines a settings schema class inheriting from BaseSettings
    - API validates settings against schema before storage
    - Type safety and validation errors returned to UI
    - Settings stored as validated JSON in database

* **FR-13: Shard Status Monitor Page (Common)**
    All bots include a Shard Status Monitor page:
    - Displays real-time shard health and status
    - Shows which shard serves which guild
    - Restricted to developer team members (main server members)
    - Displays: shard ID, guild assignments, connection status, latency, uptime (human-readable), last heartbeat

### 4.6 LLM Integration Module

* **FR-14: Multi-Provider LLM Service**
    The baseline shall provide a unified LLM integration module supporting multiple providers:
    - **Supported Providers**: OpenAI, Google (Gemini), xAI (Grok), Anthropic (Claude)
    - **Access**: Available to **Bot**, **Backend**, and **Frontend** (via API)
    - **Provider-Specific APIs**: Each provider has provider-specific implementation respecting API differences
    - **Model Selection**: Cogs/Clients can specify which provider and model to use for each request
    - **Configurable Model List**: Support a configurable list of models per provider
    - **Cost Tracking**: Track all token usage (prompt/completion) and costs (USD) per request and aggregated to proper database tables.
    
    The service is accessible via dependency injection: `services.llm`

* **FR-15: LLM Text Capabilities (All Providers)**
    All providers must support text input/output:
    - Text prompt to text response
    - System prompts and user prompts
    - Multi-turn conversations with message history
    - Temperature and other generation parameters
    - Maximum token limits per provider/model

* **FR-16: LLM Function Calling (All Providers)**
    All providers must support function calling:
    - Define functions with JSON schema
    - Model selects and calls functions as needed
    - Parallel function calling where supported
    - Function result integration back to model
    - Type safety with Pydantic function definitions

* **FR-17: LLM Structured Output (All Providers)**
    All providers must support structured output:
    - Define output schema using Pydantic models
    - Force model to return JSON matching schema
    - Type-safe response parsing
    - Validation of structured responses

* **FR-18: LLM Image Generation (Provider-Specific)**
    Image generation support where provider offers it:
    - **OpenAI**: DALL-E 3 support
    - **Other Providers**: Support added as capabilities become available
    - Return image URLs or base64 data
    - Track image generation costs separately

* **FR-19: LLM Audio Capabilities (Provider-Specific)**
    Audio support where provider offers it:
    - Text-to-speech (TTS) where available
    - Speech-to-text (STT/Whisper) where available
    - Audio format handling
    - Track audio processing costs

* **FR-20: LLM Cost Tracking and Analytics**
    Comprehensive cost tracking for all LLM usage:
    - **Per-Request Tracking**:
        - Provider and model used
        - Prompt tokens
        - Completion tokens
        - Cache tokens (where supported, e.g., Claude prompt caching)
        - Total tokens
        - Estimated cost (based on provider pricing)
    - **Aggregated Analytics**:
        - Per-guild usage and costs
        - Per-user usage and costs (optional)
        - Per-cog usage tracking
        - Time-based analytics (daily, weekly, monthly)
    - **Database Storage**: All usage logged to database for reporting and billing

* **FR-21: LLM Provider Configuration**
    Per-provider configuration management:
    - API keys stored in environment variables
    - Model lists configurable per provider
    - Default models per provider
    - Rate limiting per provider
    - Timeout settings per provider
    - Retry logic with exponential backoff

* **FR-22: LLM Error Handling**
    Robust error handling for LLM operations:
    - Handle rate limit errors gracefully
    - Retry failed requests with backoff
    - Fallback to alternative models on error
    - Log all errors for debugging
    - Return meaningful error messages to cogs

### 4.7 Bot Status & Observability

* **FR-23: Ephemeral Status Command**
    The bot provides a `/status` slash command:
    - Returns bot information as ephemeral message (visible only to command user)
    - Displays: uptime (human-readable), guild count, shard info, database status, Redis status
    - Available to all users in guilds where bot is present
    - No startup/shutdown notifications to Discord channels (multi-server bot)

* **FR-12: Health Check Endpoints**
    Both backend and bot expose HTTP health endpoints:
    - **Backend API**: `/health` endpoint verifying DB connectivity, Redis connectivity, service status
    - **Discord Bot**: `/health` endpoint (port 8080) with bot status, shard info, DB/Redis connectivity
    - Used by Docker healthchecks and monitoring systems

* **FR-13: Shard Monitoring and Tracking**
    The bot tracks shard health in Redis:
    - Each shard periodically writes status to Redis (guild assignments, latency, heartbeat timestamp)
    - Backend API provides endpoints to retrieve shard status grouped by guild
    - Shard data includes: shard ID, guild IDs, connection status, latency, uptime (human-readable), last heartbeat

### 3.6 Scalability

* **FR-14: Backend Horizontal Scalability**
    The backend API supports horizontal scaling:
    - All backend instances are stateless
    - Session data, OAuth tokens, and cache stored in shared Redis instance
    - Any backend instance can handle any request
    - Architecture supports adding load balancer (future) without code changes

* **FR-15: Discord Bot Sharding**
    The bot supports horizontal scaling through Discord sharding:
    - Uses `AutoShardedBot` (discord.py) for automatic shard distribution
    - Discord automatically manages shard allocation and load distribution
    - Bot scales as it joins more servers

### 4.8 Settings Hierarchy

The platform implements a four-level hierarchy for configuration and settings management:

*   **Level 1: Plugin Settings (Guild-Specific)**
    *   **Scope**: Specific to a single guild and a single plugin/feature.
    *   **Access**: Authorized Users (Owner + Delegated Admins).
    *   **Storage**: Database (`guild_settings` table).
    *   **Example**: "Responder Plugin" settings, enabled channels for a specific feature.

*   **Level 2: User Settings (User-Specific)**
    *   **Scope**: Specific to a single user across the bot (or per guild).
    *   **Access**: The individual user.
    *   **Storage**: Database (`user_settings` table - *Future Implementation*).
    *   **Example**: Language preference, time zone, notification preferences.

*   **Level 3: Platform Settings (Developer Team)**
    *   **Scope**: Core behavioral settings that affect the bot's operation for a guild (or globally).
    *   **Access**: Framework Developers only (validated via `DISCORD_GUILD_ID` & `DEVELOPER_ROLE_ID`).
    *   **Storage**: Database (`guild_settings` table) but gated by strict permissions.
    *   **Example**: LLM Model selection, System Prompts, Token limits.
    *   **Management**: Accessible via the "Platform Settings" UI section.

*   **Level 4: Deployment Settings (Infrastructure)**
    *   **Scope**: Static infrastructure configuration.
    *   **Access**: DevOps / Deployment Engineer.
    *   **Storage**: Environment Variables (`.env`) or Docker Secrets.
    *   **Example**: `DISCORD_GUILD_ID` (Dev Server), Database URL, API Keys, Redis Host.
    *   **Management**: **Not accessible via Frontend**. Must be set at deployment time.

***

* **FR-23: AI Analytics Dashboard**
    The framework shall provide a dedicated dashboard for developers to monitor LLM usage:
    - **Access Control**: Restricted to Platform Admins (Level 3)
    - **Visualizations**: Total Tokens, Total Cost, Requests by Provider
    - **Logs**: Table detailed recent requests, latency, and costs
    - **Data Source**: Aggregated from `llm_usage` table

## 4.0 Non-Functional Requirements

* **NFR-1: Containerization**
    All components containerized using Docker with Docker Compose orchestration.

* **NFR-2: Network Segmentation**
    Multiple Docker networks for security isolation:
    - **internet**: Frontend/web UI (ONLY network exposed to public)
    - **intranet**: Backend API (private, receives frontend calls)
    - **dbnet**: Database access (private)
    
    Only `internet` network exposed to web; `intranet` and `dbnet` remain private. Backend has OAuth callback endpoint exposed for authentication.

* **NFR-3: Frontend-Backend Decoupling**
    Frontend and backend are completely independent services:
    - Communicate via well-defined REST API
    - Either can be replaced independently
    - Backend provides all necessary endpoints for frontend

* **NFR-4: Security**
    Sensitive information managed outside version control in `.env`:
    - Discord bot token
    - Discord OAuth client ID and secret
    - Database credentials
    - Session secrets
    - Main/developer server guild ID
    
    Guild IDs for bot servers NOT stored in `.env` (multi-server support).

* **NFR-5: Data Persistence**
    PostgreSQL data stored in persistent Docker volume (survives container restarts).

* **NFR-6: Code Modularity**
    Discord bot organized using cogs pattern for separation of concerns and maintainability.

* **NFR-7: Multi-Tenancy and Data Isolation**
    Complete data isolation between guilds:
    - All queries scoped by `guild_id`
    - Configuration for one guild doesn't affect others

* **NFR-8: Backend Scalability Architecture**
    - **Stateless Design**: No session state in memory; all in Redis
    - **Database Connection Pooling**: SQLAlchemy configured with pooling
    - **Load Balancer Ready**: Supports nginx/Traefik/HAProxy without code changes
    - **Redis for Shared State**: Session storage, caching, shared state

* **NFR-9: Discord Bot Sharding Support**
    Bot capable of using `AutoShardedBot` for automatic guild distribution across shards.

* **NFR-10: Structured Logging and Observability**
    Comprehensive logging system for debugging and monitoring:
    - **Structured JSON Logging**: All logs output in JSON format with consistent fields
    - **Correlation IDs**: Each request/operation has unique ID for tracing across services
    - **Log Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL properly used
    - **Contextual Information**: All logs include: timestamp, service name, component, guild_id (where applicable), user_id (where applicable)
    - **Log Aggregation**: Compatible with log aggregation tools (ELK, Datadog, CloudWatch)
    - **Sensitive Data Filtering**: Automatic redaction of tokens, passwords, API keys in logs
    - **Performance Logging**: Track operation duration for slow query detection
    - **LLM Request Logging**: Log all LLM requests with provider, model, tokens, cost, latency
    - **Error Context**: Stack traces and error context included in ERROR/CRITICAL logs
    - **Log Rotation**: Automatic log rotation to prevent disk fill

* **NFR-11: Database Migration Strategy**
    Systematic database schema evolution:
    - **Alembic Integration**: All schema changes through Alembic migrations
    - **Baseline Migrations**: Baseline migrations tracked separately from bot-specific
    - **Backward Compatibility**: Migrations support zero-downtime deployments
    - **Rollback Support**: All migrations must be reversible
    - **Migration Testing**: Migrations tested in staging before production
    - **Version Control**: Migration files in version control with descriptive names

* **NFR-12: API Rate Limiting**
    Protect API from abuse and ensure fair usage:
    - **Per-User Rate Limits**: Limit requests per user (e.g., 100/minute)
    - **Per-Guild Rate Limits**: Limit requests per guild
    - **Global Rate Limits**: Overall API rate limits
    - **Rate Limit Headers**: Return rate limit info in response headers
    - **Graceful Degradation**: Return 429 with retry-after header
    - **Whitelist Support**: Bypass rate limits for developer team

***

## 5.0 Technical Stack

* **Backend**: Python 3.11+ (Always use latest stable version)
* **Libraries**: Always use latest stable versions unless there is a specific conflict
* **Discord API Wrapper**: discord.py
* **Database ORM**: SQLAlchemy
* **Backend API Framework**: FastAPI
* **ASGI Server**: Uvicorn
* **Frontend Framework**: Next.js 14+ (React)
* **Frontend Styling**: TailwindCSS
* **UI Components**: shadcn/ui
* **Frontend Animations**: Framer Motion (optional)
* **Task Scheduler**: APScheduler
* **Database**: PostgreSQL 15+
* **Cache/Session Store**: Redis
* **Authentication**: Discord OAuth 2.0
* **Deployment**: Docker & Docker Compose
* **Docker Networks**: 
    - `internet` (frontend access)
    - `intranet` (backend-frontend communication)
    - `dbnet` (database access)

***

## 6.0 Database Schema (Baseline Tables)

### 6.1 guilds
Stores information about Discord servers where the bot is installed.
- `guild_id` (BIGINT, PK): Discord guild ID
- `guild_name` (VARCHAR): Guild name
- `added_by_user_id` (BIGINT): Discord user ID who added the bot
- `added_at` (TIMESTAMP): When bot was added
- `is_active` (BOOLEAN): Whether bot is still in guild

### 6.2 authorized_users
Stores users who have UI access for each guild.
- `id` (SERIAL, PK): Auto-increment ID
- `guild_id` (BIGINT, FK): Guild this permission is for
- `user_id` (BIGINT): Discord user ID
- `granted_by_user_id` (BIGINT): User who granted this permission
- `granted_at` (TIMESTAMP): When permission was granted
- `is_active` (BOOLEAN): Whether permission is active

### 6.3 guild_settings
Stores dynamic settings per guild (schema varies by bot implementation).
- `id` (SERIAL, PK): Auto-increment ID
- `guild_id` (BIGINT, FK): Guild ID
- `setting_key` (VARCHAR): Setting name
- `setting_value` (JSONB): Setting value (flexible JSON structure)
- `updated_at` (TIMESTAMP): Last update time

### 6.4 llm_usage
Stores LLM API usage for cost tracking and analytics.
- `id` (SERIAL, PK): Auto-increment ID
- `guild_id` (BIGINT, FK, NULLABLE): Guild ID (nullable for global/system usage)
- `user_id` (BIGINT, NULLABLE): Discord user ID who triggered the request
- `cog_name` (VARCHAR): Name of cog that made the request
- `provider` (VARCHAR): LLM provider (openai, google, xai, anthropic)
- `model` (VARCHAR): Specific model used
- `request_type` (VARCHAR): Type of request (text, function_call, image, audio, structured)
- `prompt_tokens` (INTEGER): Number of prompt tokens
- `completion_tokens` (INTEGER): Number of completion tokens
- `cache_tokens` (INTEGER, DEFAULT 0): Number of cached tokens (Claude)
- `total_tokens` (INTEGER): Total tokens used
- `estimated_cost_usd` (DECIMAL(10,6)): Estimated cost in USD
- `created_at` (TIMESTAMP): When request was made
- `metadata` (JSONB, NULLABLE): Additional metadata (input length, output length, etc.)

### 6.5 llm_model_pricing
Stores pricing information per model (updateable configuration).
- `id` (SERIAL, PK): Auto-increment ID
- `provider` (VARCHAR): Provider name
- `model` (VARCHAR): Model name
- `input_cost_per_1k_tokens` (DECIMAL(10,6)): Cost per 1K input tokens
- `output_cost_per_1k_tokens` (DECIMAL(10,6)): Cost per 1K output tokens
- `cache_cost_per_1k_tokens` (DECIMAL(10,6), NULLABLE): Cost per 1K cache tokens
- `image_cost_per_unit` (DECIMAL(10,6), NULLABLE): Cost per image generation
- `audio_cost_per_minute` (DECIMAL(10,6), NULLABLE): Cost per minute of audio
- `is_active` (BOOLEAN): Whether this model is currently available
- `updated_at` (TIMESTAMP): Last update time

### 6.6 Additional Tables
Bot-specific implementations may add additional tables as needed, all including `guild_id` for proper scoping.

***

##     - **LLMUsage**:
        - `id`: PK
        - `user_id`: FK to User
        - `guild_id`: FK to Guild (Optional)
        - `context_id`: String (Optional, for chat grouping)
        - `tokens`: Total tokens
        - `cost`: Estimated cost (USD)
        - `provider`, `model`: Strings
        - `timestamp`: DateTime
    - **LLMModelPricing**:
        - `provider`, `model`: PK/Unique
        - `input_cost_per_1k`: Float
        - `output_cost_per_1k`: Float

7.0 API Endpoints (Baseline)

### 7.1 Authentication
- `POST /auth/discord/callback` - OAuth callback for Discord authentication
- `POST /auth/logout` - User logout
- `GET /auth/me` - Get current authenticated user info

### 7.2 Guild Management
- `GET /guilds` - List guilds the authenticated user has access to
- `GET /guilds/{guild_id}` - Get specific guild information
- `GET /guilds/{guild_id}/members` - Get guild members (for permission delegation)

### 7.3 Permission Management
- `GET /guilds/{guild_id}/authorized-users` - List authorized users for guild
- `POST /guilds/{guild_id}/authorized-users` - Grant UI access to user
- `DELETE /guilds/{guild_id}/authorized-users/{user_id}` - Revoke UI access

### 7.4 Settings
- `GET /guilds/{guild_id}/settings` - Get all settings for guild
- `PUT /guilds/{guild_id}/settings` - Update settings for guild
- `GET /guilds/{guild_id}/settings/{key}` - Get specific setting

### 7.5 Monitoring
- `GET /health` - Backend health check
- `GET /shards` - Get shard status (developer team only)
- `GET /shards/{guild_id}` - Get shard info for specific guild

### 7.6 Bot-Specific Endpoints
Bot implementations add additional endpoints as needed.

***

## 8.0 Frontend Structure (Baseline)

### 8.1 Common Pages
- `/` - Landing page / Guild selector
- `/auth/callback` - OAuth callback handler
- `/guilds/{guild_id}/settings` - Settings management (common)
- `/admin/shards` - Shard status monitor (developer team only)

### 8.2 Common Components
- Authentication wrapper
- Guild selector/switcher
- Navigation sidebar
- Permission guard components
- API client with auth token management
- Common form components for settings

### 8.3 Bot-Specific Pages
Bot implementations add custom pages under `/guilds/{guild_id}/` routes.

***

## 9.0 Environment Variables (Baseline)

Required environment variables for all bot implementations:

```
# Discord Bot
DISCORD_BOT_TOKEN=<bot_token>

# Discord OAuth
DISCORD_CLIENT_ID=<oauth_client_id>
DISCORD_CLIENT_SECRET=<oauth_client_secret>
DISCORD_REDIRECT_URI=<frontend_callback_url>

# Main/Developer Server (for elevated access)
MAIN_GUILD_ID=<developer_server_guild_id>

# Database
DATABASE_URL=postgresql://user:password@host:port/dbname

# Redis
REDIS_URL=redis://host:port/db

# Backend API
API_SECRET_KEY=<random_secret_for_sessions>
API_CORS_ORIGINS=<comma_separated_frontend_urls>

# Health Check
HEALTH_HOST=0.0.0.0
HEALTH_PORT=8080

# Bot-Specific Variables
# (Added by individual bot implementations)
DISCORD_INTENTS=guilds,members,messages # Optional: Comma-separated list of intents to enable
```

***

## 10.0 Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Docker Network: internet                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Frontend (Next.js)                        │    │
│  │  - Public facing                                    │    │
│  │  - OAuth callback                                   │    │
│  │  - Dynamic page loading                             │    │
│  └─────────────────────────────────────────────────────┘    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│                   Docker Network: intranet                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Backend API (FastAPI)                     │    │
│  │  - Stateless (N instances)                          │    │
│  │  - REST API                                         │    │
│  │  - OAuth token exchange                             │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Discord Bot (Sharded)                     │    │
│  │  - AutoShardedBot                                   │    │
│  │  - Dynamic cog loading                              │    │
│  │  - Shard status to Redis                            │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Redis                                      │    │
│  │  - Sessions, cache, shard status                    │    │
│  └─────────────────────────────────────────────────────┘    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│                    Docker Network: dbnet                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           PostgreSQL                                 │    │
│  │  - Persistent volume                                │    │
│  │  - Guild-scoped data                                │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

***

## 11.0 Implementation Guidelines

### 11.1 Creating a New Bot

1. Clone baseline codebase
2. Add bot-specific cogs to `cogs/` directory
3. Add bot-specific UI pages to frontend
4. Define bot-specific database tables (all including `guild_id`)
5. Add bot-specific environment variables (including `DISCORD_INTENTS` if custom intents are needed)
6. Update `README.md` with bot-specific functionality

### 11.2 Cog Guidelines

- Cogs must be self-contained
- Minimal dependencies on baseline code
- Use dependency injection for database/Redis access
- Document required settings in guild_settings table

### 11.3 UI Page Guidelines

- Use baseline components for auth, navigation, forms
- Pages receive `guild_id` from route parameters
- API calls automatically scoped to authenticated user's accessible guilds
- Follow TailwindCSS + shadcn/ui design patterns

***

## 12.0 Comprehensive Testing Suite

### 12.1 Testing Philosophy

The baseline must maintain >80% code coverage and prevent regressions through automated testing at multiple levels.

### 12.2 Unit Tests

**Scope**: Individual functions and classes in isolation

**Requirements**:
- All service classes (DB, Redis, LLM, Config) must have unit tests
- Mock external dependencies (database, Redis, API calls)
- Test both success and error paths
- Use pytest fixtures for test data
- Coverage target: >90% for core services

**Example Test Structure**:
```
tests/
├── unit/
│   ├── test_llm_service.py
│   ├── test_database_service.py
│   ├── test_redis_service.py
│   ├── test_config_service.py
│   └── test_auth.py
```

**Framework**: pytest, pytest-asyncio, pytest-mock

### 12.3 Integration Tests

**Scope**: Multiple components working together

**Requirements**:
- Test database operations with real PostgreSQL (test database)
- Test Redis operations with real Redis (test instance)
- Test API endpoints with TestClient
- Test LLM service with mocked provider responses
- Test cog loading and initialization
- Coverage target: >70%

**Example Tests**:
- API authentication flow
- Guild settings CRUD operations
- LLM request with cost tracking to database
- Shard status updates to Redis
- Permission delegation workflow

**Framework**: pytest, httpx.AsyncClient, testcontainers

### 12.4 End-to-End Tests

**Scope**: Complete user workflows

**Requirements**:
- OAuth login flow (frontend → backend → Discord)
- Cog command execution (Discord → bot → database → response)
- UI settings update (frontend → API → database → bot)
- LLM-powered command (Discord → bot → LLM → database → response)

**Framework**: pytest, playwright (for frontend), discord.py test utilities

### 12.5 Performance Tests

**Scope**: Ensure system meets performance requirements

**Requirements**:
- API endpoint latency <200ms (p95)
- Database query performance
- Redis operation performance
- LLM request handling under load
- Concurrent user simulation
- Memory leak detection

**Tools**: locust, pytest-benchmark, memory_profiler

### 12.6 Security Tests

**Scope**: Identify security vulnerabilities

**Requirements**:
- SQL injection prevention
- XSS prevention in UI
- CSRF protection
- Authentication bypass attempts
- Rate limit enforcement
- Secrets not exposed in logs

**Tools**: bandit, safety, semgrep

### 12.7 Regression Test Suite

**Critical**: Tests that ensure baseline changes don't break bot implementations

**Requirements**:
- Reference cog implementation that exercises all baseline features
- Test cog loading/unloading
- Test service injection
- Test LLM integration across all providers
- Test database migration compatibility
- Test frontend plugin registration
- Run on every baseline commit

**Purpose**: Any change to baseline must pass regression suite to ensure bot implementations won't break

### 12.8 CI/CD Integration

**Requirements**:
- All tests run on every PR
- Tests must pass before merge
- Coverage reports generated
- Failed tests block deployment
- Nightly full test suite run
- Performance regression alerts

**GitHub Actions Workflow**:
```yaml
name: Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run Unit Tests
      - name: Run Integration Tests
      - name: Run E2E Tests
      - name: Upload Coverage
      - name: Check Coverage Threshold
```

### 12.9 Test Data Management

**Requirements**:
- Fixtures for common test data (guilds, users, settings)
- Factory functions for generating test data
- Database seeding scripts for integration tests
- Consistent test data across test types
- Cleanup after tests (no test pollution)

### 12.10 Testing Checklist

Before merging any baseline change:
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] E2E tests pass
- [ ] Regression suite passes
- [ ] Coverage >80%
- [ ] No security vulnerabilities
- [ ] Performance benchmarks met
- [ ] Logs properly structured
- [ ] Documentation updated

***
# Comprehensive additions to baseline-bot-platform-specs.txt

## Add to Section 6.0 Database Schema

### 6.5 llm_usage
Stores LLM API usage for cost tracking and analytics.
- `id` (SERIAL, PK): Auto-increment ID
- `guild_id` (BIGINT, FK, NULLABLE): Guild ID (nullable for global/system usage)
- `user_id` (BIGINT, NULLABLE): Discord user ID who triggered the request
- `cog_name` (VARCHAR): Name of cog that made the request
- `provider` (VARCHAR): LLM provider (openai, google, xai, anthropic)
- `model` (VARCHAR): Specific model used
- `request_type` (VARCHAR): Type of request (text, function_call, image, audio, structured)
- `prompt_tokens` (INTEGER): Number of prompt tokens
- `completion_tokens` (INTEGER): Number of completion tokens
- `cache_tokens` (INTEGER, DEFAULT 0): Number of cached tokens (Claude)
- `total_tokens` (INTEGER): Total tokens used
-`estimated_cost_usd` (DECIMAL(10,6)): Estimated cost in USD
- `created_at` (TIMESTAMP): When request was made
- `metadata` (JSONB, NULLABLE): Additional metadata (input length, output length, etc.)

###  6.6 llm_model_pricing
Stores pricing information per model (updateable configuration).
- `id` (SERIAL, PK): Auto-increment ID
- `provider` (VARCHAR): Provider name
- `model` (VARCHAR): Model name
- `input_cost_per_1k_tokens` (DECIMAL(10,6)): Cost per 1K input tokens
- `output_cost_per_1k_tokens` (DECIMAL(10,6)): Cost per 1K output tokens
- `cache_cost_per_1k_tokens` (DECIMAL(10,6), NULLABLE): Cost per 1K cache tokens
- `image_cost_per_unit` (DECIMAL(10,6), NULLABLE): Cost per image generation
- `audio_cost_per_minute` (DECIMAL(10,6), NULLABLE): Cost per minute of audio
- `is_active` (BOOLEAN): Whether this model is currently available
- `updated_at` (TIMESTAMP): Last update time

## Add to Section 7.0 API Endpoints

### Update all endpoints to include /v1/ prefix

All API endpoints should be versioned. Update section to note:
- All endpoints prefixed with `/api/v1/`
- Example: `POST /api/v1/auth/discord/callback`

### 7.7 LLM Analytics (Developer Team Only)
- `GET /api/v1/llm/usage/summary` - Get aggregated LLM usage summary
- `GET /api/v1/llm/usage/by-guild/{guild_id}` - Get usage for specific guild
- `GET /api/v1/llm/usage/by-cog/{cog_name}` - Get usage by cog
- `GET /api/v1/llm/models` - List available models per provider
- `PUT /api/v1/llm/models/{provider}/{model}/pricing` - Update model pricing

## Add to Section 9.0 Environment Variables

```
# LLM Provider API Keys
OPENAI_API_KEY=<openai_key>
GOOGLE_API_KEY=<google_gemini_key>
XAI_API_KEY=<grok_key>
ANTHROPIC_API_KEY=<claude_key>

# LLM Configuration
LLM_DEFAULT_PROVIDER=openai  # Default provider if not specified
LLM_MAX_RETRIES=3
LLM_TIMEOUT_SECONDS=60
```

## Add to Section 5.0 Technical Stack

```
* **LLM SDKs**: 
    - openai (OpenAI)
    - google-generativeai (Gemini)
    - anthropic (Claude)
    - (xAI/Grok SDK when available)
* **Database Migrations**: Alembic
* **Validation**: Pydantic 2.0+
* **Rate Limiting**: slowapi (FastAPI)
```

## NEW SECTION 13.0: Cog Developer Documentation

This is the most important addition - comprehensive documentation for developers building new cogs.

---

## 13.0 Cog Developer Documentation

### 13.1 Overview

This section provides comprehensive guidance for developing cogs (bot extensions) for the baseline platform. Cogs are self-contained modules that add bot-specific functionality.

### 13.2 Cog Structure

Every cog follows this structure:

```python
from discord.ext import commands
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from baseline.services import BotServices

class MyCog(commands.Cog):
    """Description of what this cog does."""
    
    def __init__(self, bot: commands.Bot, services: 'BotServices'):
        self.bot = bot
        self.services = services
        # Access injected services
        self.db = services.db
        self.redis = services.redis
        self.llm = services.llm
        self.config = services.config
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Called when cog is loaded."""
        print(f"{self.__class__.__name__} is ready!")
    
    @commands.slash_command(name="mycommand", description="My command")
    async def my_command(self, ctx):
        """Example command."""
        await ctx.respond("Hello!", ephemeral=True)

# Required: setup function for cog loading
async def setup(bot: commands.Bot):
    await bot.add_cog(MyCog(bot, bot.services))
```

### 13.3 Accessing Services

The `BotServices` container provides access to:

#### Database (SQLAlchemy)
```python
# Get a database session
async with self.services.db.session() as session:
    # Query guilds
    result = await session.execute(
        select(Guild).where(Guild.guild_id == guild_id)
    )
    guild = result.scalar_one_or_none()
    
    # Insert data
    new_record = MyModel(guild_id=guild_id, data="value")
    session.add(new_record)
    await session.commit()
```

#### Redis
```python
# Set a value
await self.services.redis.set(f"my_key:{guild_id}", "value", ex=3600)

# Get a value
value = await self.services.redis.get(f"my_key:{guild_id}")

# Publish event
await self.services.redis.publish("my_channel", json.dumps({"event": "data"}))
```

#### Configuration
```python
# Get guild settings
settings = await self.services.config.get_guild_settings(guild_id)

# Update guild setting
await self.services.config.set_guild_setting(
    guild_id, 
    "my_setting_key", 
    {"value": "data"}
)
```

### 13.4 Using the LLM Service

The LLM service is the most powerful feature of the baseline. Here's how to use it:

#### Basic Text Completion
```python
from baseline.llm import LLMProvider

response = await self.services.llm.complete(
    provider=LLMProvider.OPENAI,
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ],
    temperature=0.7,
    max_tokens=150,
    guild_id=guild_id,  # For cost tracking
    user_id=user_id,    # Optional
    cog_name=self.__class__.__name__
)

# Access response
text = response.content
tokens_used = response.usage.total_tokens
cost = response.cost_usd
```

#### Function Calling
```python
from pydantic import BaseModel, Field

# Define function schema
class GetWeatherParams(BaseModel):
    location: str = Field(description="City name")
    unit: str = Field(description="Temperature unit (celsius/fahrenheit)")

functions = [
    {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": GetWeatherParams.model_json_schema()
    }
]

response = await self.services.llm.complete(
    provider=LLMProvider.ANTHROPIC,
    model="claude-3-5-sonnet",
    messages=[{"role": "user", "content": "What's the weather in Paris?"}],
    functions=functions,
    guild_id=guild_id,
    cog_name=self.__class__.__name__
)

# Check if function was called
if response.function_call:
    function_name = response.function_call.name
    arguments = GetWeatherParams(**response.function_call.arguments)
    
    # Execute function
    weather_data = await get_weather(arguments.location, arguments.unit)
    
    # Send result back to LLM
    final_response = await self.services.llm.complete(
        provider=LLMProvider.ANTHROPIC,
        model="claude-3-5-sonnet",
        messages=[
            {"role": "user", "content": "What's the weather in Paris?"},
            {"role": "assistant", "function_call": response.function_call},
            {"role": "function", "name": function_name, "content": json.dumps(weather_data)}
        ],
        guild_id=guild_id,
        cog_name=self.__class__.__name__
    )
```

#### Structured Output
```python
class UserProfile(BaseModel):
    name: str
    age: int
    interests: list[str]

response = await self.services.llm.complete_structured(
    provider=LLMProvider.OPENAI,
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Extract user info: John is 25 and likes coding and gaming"}
    ],
    response_format=UserProfile,
    guild_id=guild_id,
    cog_name=self.__class__.__name__
)

# Type-safe parsed response
profile: UserProfile = response.parsed
print(profile.name)  # "John"
print(profile.age)   # 25
```

#### Image Generation
```python
response = await self.services.llm.generate_image(
    provider=LLMProvider.OPENAI,
    model="dall-e-3",
    prompt="A futuristic cityscape at sunset",
    size="1024x1024",
    quality="hd",
    guild_id=guild_id,
    cog_name=self.__class__.__name__
)

image_url = response.image_url
cost = response.cost_usd
```

#### Multi-Provider Usage
```python
# Try multiple providers with fallback
providers = [
    (LLMProvider.ANTHROPIC, "claude-3-5-sonnet"),
    (LLMProvider.OPENAI, "gpt-4"),
    (LLMProvider.GOOGLE, "gemini-1.5-pro")
]

for provider, model in providers:
    try:
        response = await self.services.llm.complete(
            provider=provider,
            model=model,
            messages=messages,
            guild_id=guild_id,
            cog_name=self.__class__.__name__
        )
        break  # Success
    except Exception as e:
        logging.warning(f"{provider} failed: {e}")
        continue  # Try next provider
```

### 13.5 Database Patterns

#### Creating Bot-Specific Tables
```python
# In your cog's models.py
from sqlalchemy import Column, BigInteger, String, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class MyBotData(Base):
    __tablename__ = 'my_bot_data'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)  # ALWAYS include
    user_id = Column(BigInteger, nullable=False)
    data = Column(String)
    created_at = Column(TIMESTAMP, server_default='now()')
```

#### Guild-Scoped Queries
```python
# ALWAYS scope queries by guild_id
async with self.services.db.session() as session:
    result = await session.execute(
        select(MyBotData)
        .where(MyBotData.guild_id == guild_id)  # Critical!
        .where(MyBotData.user_id == user_id)
    )
    records = result.scalars().all()
```

### 13.6 Event Handlers

```python
@commands.Cog.listener()
async def on_message(self, message):
    """Respond to messages."""
    if message.author.bot:
        return
    
    # Get guild-specific settings
    settings = await self.services.config.get_guild_settings(message.guild.id)
    
    if settings.get("auto_response_enabled"):
        # Use LLM to generate response
        response = await self.services.llm.complete(
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            messages=[{
                "role": "user",
                "content": message.content
            }],
            guild_id=message.guild.id,
            user_id=message.author.id,
            cog_name=self.__class__.__name__
        )
        
        await message.reply(response.content)

@commands.Cog.listener()
async def on_guild_join(self, guild):
    """Initialize settings when bot joins a guild."""
    default_settings = {
        "auto_response_enabled": False,
        "welcome_message": "Welcome!"
    }
    
    for key, value in default_settings.items():
        await self.services.config.set_guild_setting(
            guild.id,
            key,
            value
        )
```

### 13.7 Error Handling

```python
@commands.slash_command()
async def my_command(self, ctx):
    try:
        # Your logic here
        response = await self.services.llm.complete(...)
        await ctx.respond(response.content)
        
    except RateLimitError as e:
        await ctx.respond(
            "⏳ Rate limited. Please try again later.",
            ephemeral=True
        )
    except LLMError as e:
        logging.error(f"LLM error: {e}")
        await ctx.respond(
            "❌ AI service error. Please try again.",
            ephemeral=True
        )
    except Exception as e:
        logging.exception("Unexpected error")
        await ctx.respond(
            "❌ An error occurred.",
            ephemeral=True
        )
```

### 13.8 Testing Cogs

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_my_cog():
    # Mock services
    services = MagicMock()
    services.llm.complete = AsyncMock(return_value=MagicMock(
        content="Test response",
        usage=MagicMock(total_tokens=100),
        cost_usd=0.001
    ))
    
    # Create cog
    bot = MagicMock()
    bot.services = services
    cog = MyCog(bot, services)
    
    # Test command
    ctx = AsyncMock()
    await cog.my_command(ctx)
    
    # Assert
    ctx.respond.assert_called_once()
    services.llm.complete.assert_called_once()
```

### 13.9 Best Practices

1. **Always scope by guild_id**: Never forget to filter queries by guild_id
2. **Use dependency injection**: Access services through `self.services`, not global imports
3. **Handle errors gracefully**: Wrap LLM calls in try/except blocks
4. **Track costs**: Always pass `guild_id` and `cog_name` to LLM calls
5. **Use ephemeral responses**: For status/error messages, use `ephemeral=True`
6. **Validate user permissions**: Check if user has permission before executing commands
7. **Log important actions**: Use logging for debugging and auditing
8. **Test your cogs**: Write unit tests for critical functionality
9. **Document commands**: Add clear descriptions to slash commands
10. **Respect rate limits**: Implement backoff strategies for external API calls

### 13.10 Example: Complete Cog

See `examples/example_cog.py` in the baseline repository for a fully-featured example cog demonstrating all patterns and best practices.
