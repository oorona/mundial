"""
Settings Definitions — Single source of truth for all configurable parameters.

Each entry defines:
- key:           Environment variable name (canonical identifier)
- friendly_name: Human-readable label shown in the UI
- description:   Plain-English explanation of the setting's purpose
- category:      Grouping for the configuration page
- type:          Data type (string | boolean | integer | select)
- is_dynamic:    True = can be changed at runtime without a server restart
- is_secret:     True = value is masked in the UI
- possible_values: List of [value, label] pairs for 'select' type (None = free input)
- default:       Default value when the env var is not set
- requires_restart_note: Additional note shown when is_dynamic is False
"""

from typing import Any, List, Optional

SETTING_CATEGORIES = {
    "general":      "General",
    "bot_identity": "Bot Identity",
    "discord":      "Discord",
    "api":          "API & Security",
    "llm":          "LLM / AI",
    "rate_limit":   "Rate Limits",
    "features":     "Feature Flags",
    "frontend":     "Frontend (display only)",
}

class SettingDef:
    def __init__(
        self,
        key: str,
        friendly_name: str,
        description: str,
        category: str,
        type: str = "string",
        is_dynamic: bool = False,
        is_secret: bool = False,
        possible_values: Optional[List[List[str]]] = None,
        default: Any = None,
        requires_restart_note: str = "Changing this value requires a server restart to take effect.",
    ):
        self.key = key
        self.friendly_name = friendly_name
        self.description = description
        self.category = category
        self.type = type
        self.is_dynamic = is_dynamic
        self.is_secret = is_secret
        self.possible_values = possible_values
        self.default = default
        self.requires_restart_note = requires_restart_note

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "friendly_name": self.friendly_name,
            "description": self.description,
            "category": self.category,
            "type": self.type,
            "is_dynamic": self.is_dynamic,
            "is_secret": self.is_secret,
            "possible_values": self.possible_values,
            "default": self.default,
            "requires_restart_note": self.requires_restart_note if not self.is_dynamic else None,
        }


# ---------------------------------------------------------------------------
# Application settings definitions (non-database)
# ---------------------------------------------------------------------------

APP_SETTINGS: List[SettingDef] = [

    # ── General ──────────────────────────────────────────────────────────────
    SettingDef(
        key="APP_NAME",
        friendly_name="Application Name",
        description="The internal name of the platform used in API responses and service identifiers.",
        category="general",
        type="string",
        is_dynamic=False,
        default="discord-bot-baseline",
    ),
    SettingDef(
        key="ENVIRONMENT",
        friendly_name="Environment",
        description="Deployment environment. Controls certain safety checks and logging verbosity. "
                    "Must be 'development', 'staging', or 'production'.",
        category="general",
        type="select",
        is_dynamic=False,
        possible_values=[
            ["development", "Development"],
            ["staging", "Staging"],
            ["production", "Production"],
        ],
        default="development",
    ),
    SettingDef(
        key="DEBUG",
        friendly_name="Debug Mode",
        description="Enables verbose debug output across all services. "
                    "In debug mode, additional stack traces and internal state are logged. "
                    "Should be disabled in production for security and performance.",
        category="general",
        type="boolean",
        is_dynamic=True,
        default="false",
    ),
    SettingDef(
        key="LOG_LEVEL",
        friendly_name="Log Level",
        description="Minimum severity level for log messages to be recorded. "
                    "'DEBUG' records everything; 'ERROR' records only failures.",
        category="general",
        type="select",
        is_dynamic=True,
        possible_values=[
            ["DEBUG",    "DEBUG — All messages"],
            ["INFO",     "INFO — Informational and above"],
            ["WARNING",  "WARNING — Warnings and above"],
            ["ERROR",    "ERROR — Errors only"],
            ["CRITICAL", "CRITICAL — Critical failures only"],
        ],
        default="INFO",
    ),
    SettingDef(
        key="LOG_FORMAT",
        friendly_name="Log Format",
        description="Output format for log entries. 'json' is recommended for production environments "
                    "and log aggregation tools. 'text' is more readable during local development.",
        category="general",
        type="select",
        is_dynamic=False,
        possible_values=[["json", "JSON (structured)"], ["text", "Text (human-readable)"]],
        default="json",
    ),
    SettingDef(
        key="HOT_RELOAD",
        friendly_name="Hot Reload",
        description="Automatically restarts the backend server when source files change. "
                    "Only meaningful during development; must be disabled in production.",
        category="general",
        type="boolean",
        is_dynamic=False,
        default="true",
    ),

    # ── Bot Identity ──────────────────────────────────────────────────────────
    SettingDef(
        key="BOT_NAME",
        friendly_name="Bot Name",
        description="The public display name of this bot deployment. Shown on the landing page and "
                    "in the 'Add to Server' invitation button.",
        category="bot_identity",
        type="string",
        is_dynamic=False,
        default="My Discord Bot",
    ),
    SettingDef(
        key="BOT_TAGLINE",
        friendly_name="Bot Tagline (English)",
        description="A short one-line description displayed beneath the bot name on the public landing page.",
        category="bot_identity",
        type="string",
        is_dynamic=False,
        default="",
    ),
    SettingDef(
        key="BOT_TAGLINE_ES",
        friendly_name="Bot Tagline (Spanish)",
        description="Spanish version of the tagline. Falls back to the English tagline if not set.",
        category="bot_identity",
        type="string",
        is_dynamic=False,
        default="",
    ),
    SettingDef(
        key="BOT_DESCRIPTION",
        friendly_name="Bot Description (English)",
        description="A longer marketing description explaining what the bot does. Shown on the public "
                    "landing page below the tagline.",
        category="bot_identity",
        type="string",
        is_dynamic=False,
        default="",
    ),
    SettingDef(
        key="BOT_DESCRIPTION_ES",
        friendly_name="Bot Description (Spanish)",
        description="Spanish version of the description. Falls back to the English description if not set.",
        category="bot_identity",
        type="string",
        is_dynamic=False,
        default="",
    ),
    SettingDef(
        key="BOT_INVITE_URL",
        friendly_name="Bot Invite URL",
        description="The full Discord OAuth2 invite URL for this bot, including the permissions integer "
                    "and scopes. Generate this in the Discord Developer Portal under OAuth2 → URL Generator. "
                    "Example: https://discord.com/oauth2/authorize?client_id=...&permissions=...&scope=bot",
        category="bot_identity",
        type="string",
        is_dynamic=False,
        default="",
    ),

    # ── Discord ───────────────────────────────────────────────────────────────
    SettingDef(
        key="DISCORD_CLIENT_ID",
        friendly_name="Discord OAuth Client ID",
        description="The application's Client ID from the Discord Developer Portal. "
                    "Required for OAuth2 login flows.",
        category="discord",
        type="string",
        is_dynamic=False,
        is_secret=False,
        default=None,
    ),
    SettingDef(
        key="DISCORD_CLIENT_SECRET",
        friendly_name="Discord OAuth Client Secret",
        description="The OAuth2 client secret from the Discord Developer Portal. "
                    "This value is sensitive and should be stored as a Docker secret file.",
        category="discord",
        type="string",
        is_dynamic=False,
        is_secret=True,
        default=None,
    ),
    SettingDef(
        key="DISCORD_REDIRECT_URI",
        friendly_name="Discord OAuth Redirect URI",
        description="The URL Discord will redirect to after a user authorises the application. "
                    "Must exactly match the redirect URI registered in the Discord Developer Portal.",
        category="discord",
        type="string",
        is_dynamic=False,
        default="http://localhost:3000/auth/callback",
    ),
    SettingDef(
        key="DISCORD_BOT_TOKEN",
        friendly_name="Discord Bot Token",
        description="Authentication token for the Discord bot. "
                    "Treat this as a password — never commit it to source control. "
                    "Stored as a Docker secret file in production.",
        category="discord",
        type="string",
        is_dynamic=False,
        is_secret=True,
        default=None,
    ),
    SettingDef(
        key="DISCORD_GUILD_ID",
        friendly_name="Developer Guild ID",
        description="Discord server (guild) ID used to identify developer/platform-admin members. "
                    "Users who own this guild or hold the Developer Role in it are granted Level 5 access.",
        category="discord",
        type="string",
        is_dynamic=False,
        default="1423815821674676267",
    ),
    SettingDef(
        key="DEVELOPER_ROLE_ID",
        friendly_name="Developer Role ID",
        description="ID of the Discord role that grants platform-admin (Level 5) access. "
                    "Any member of the Developer Guild holding this role is treated as a developer.",
        category="discord",
        type="string",
        is_dynamic=False,
        default="1513345032252297430",
    ),

    # ── API & Security ────────────────────────────────────────────────────────
    SettingDef(
        key="API_VERSION",
        friendly_name="API Version",
        description="Version prefix appended to all API routes (e.g. 'v1' produces /api/v1/…). "
                    "Changing this requires frontend configuration updates.",
        category="api",
        type="string",
        is_dynamic=False,
        default="v1",
    ),
    SettingDef(
        key="API_SECRET_KEY",
        friendly_name="API Secret Key",
        description="Secret used to sign session tokens and other cryptographic material. "
                    "Must be a long, random string. Stored as a Docker secret file in production. "
                    "Rotating this key will invalidate all active sessions.",
        category="api",
        type="string",
        is_dynamic=False,
        is_secret=True,
        default=None,
    ),
    SettingDef(
        key="API_CORS_ORIGINS",
        friendly_name="CORS Allowed Origins",
        description="Comma-separated list of URLs that are permitted to make cross-origin requests "
                    "to the API. Example: 'http://localhost:3000,https://yourdomain.com'.",
        category="api",
        type="string",
        is_dynamic=True,
        default="http://localhost:3000",
    ),
    SettingDef(
        key="HEALTH_HOST",
        friendly_name="Health Check Host",
        description="Network interface the health-check HTTP server binds to. "
                    "Use '0.0.0.0' to listen on all interfaces.",
        category="api",
        type="string",
        is_dynamic=False,
        default="0.0.0.0",
    ),
    SettingDef(
        key="HEALTH_PORT",
        friendly_name="Health Check Port",
        description="Port number the health-check endpoint listens on.",
        category="api",
        type="integer",
        is_dynamic=False,
        default="8080",
    ),

    # ── LLM / AI ──────────────────────────────────────────────────────────────
    SettingDef(
        key="LLM_DEFAULT_PROVIDER",
        friendly_name="Default LLM Provider",
        description="The AI model provider used when no explicit provider is specified in an API request.",
        category="llm",
        type="select",
        is_dynamic=True,
        possible_values=[
            ["openai",    "OpenAI"],
            ["anthropic", "Anthropic (Claude)"],
            ["google",    "Google (Gemini)"],
            ["xai",       "xAI (Grok)"],
        ],
        default="openai",
    ),
    SettingDef(
        key="LLM_DEFAULT_MODEL",
        friendly_name="Default LLM Model",
        description="The model used when no explicit model is specified in a request. Must be a model "
                    "offered by the default provider (e.g. gpt-4o, gemini-3-flash-preview). Leave blank "
                    "to use the provider's built-in default. The System Config page offers a live "
                    "dropdown of available models.",
        category="llm",
        type="string",
        is_dynamic=True,
        default=None,
    ),
    SettingDef(
        key="LLM_MAX_RETRIES",
        friendly_name="LLM Max Retries",
        description="Maximum number of retry attempts for a failed LLM API call before returning an error.",
        category="llm",
        type="integer",
        is_dynamic=True,
        default="3",
    ),
    SettingDef(
        key="LLM_TIMEOUT_SECONDS",
        friendly_name="LLM Request Timeout",
        description="Maximum number of seconds to wait for a response from an LLM provider before "
                    "treating the request as timed out.",
        category="llm",
        type="integer",
        is_dynamic=True,
        default="60",
    ),

    # ── Rate Limits ───────────────────────────────────────────────────────────
    SettingDef(
        key="RATE_LIMIT_PER_USER",
        friendly_name="Per-User Rate Limit",
        description="Maximum number of API requests a single authenticated user may make per minute.",
        category="rate_limit",
        type="integer",
        is_dynamic=True,
        default="100",
    ),
    SettingDef(
        key="RATE_LIMIT_PER_GUILD",
        friendly_name="Per-Guild Rate Limit",
        description="Maximum number of API requests originating from a single Discord guild per minute.",
        category="rate_limit",
        type="integer",
        is_dynamic=True,
        default="500",
    ),
    SettingDef(
        key="RATE_LIMIT_GLOBAL",
        friendly_name="Global Rate Limit",
        description="Total maximum number of API requests across all users and guilds per minute.",
        category="rate_limit",
        type="integer",
        is_dynamic=True,
        default="1000",
    ),

    # ── Feature Flags ─────────────────────────────────────────────────────────
    SettingDef(
        key="ENABLE_LLM_FEATURES",
        friendly_name="Enable LLM Features",
        description="Master switch for all large-language-model features (text generation, chat, etc.). "
                    "Disabling this blocks all requests to /api/v1/llm.",
        category="features",
        type="boolean",
        is_dynamic=True,
        default="true",
    ),
    SettingDef(
        key="ENABLE_IMAGE_GENERATION",
        friendly_name="Enable Image Generation",
        description="Enables the image-generation capability via AI providers. "
                    "Requires ENABLE_LLM_FEATURES to also be enabled.",
        category="features",
        type="boolean",
        is_dynamic=True,
        default="true",
    ),
    SettingDef(
        key="ENABLE_AUDIO_FEATURES",
        friendly_name="Enable Audio Features",
        description="Enables audio transcription and text-to-speech capabilities. "
                    "These features may incur additional cost on the AI provider.",
        category="features",
        type="boolean",
        is_dynamic=True,
        default="false",
    ),

    # ── Frontend (display only) ───────────────────────────────────────────────
    SettingDef(
        key="NEXT_PUBLIC_APP_NAME",
        friendly_name="Public Application Name",
        description="Application name shown in the browser tab, navigation, and public-facing pages. "
                    "This is baked into the Next.js build and requires a frontend rebuild to update.",
        category="frontend",
        type="string",
        is_dynamic=False,
        default="Baseline Bot",
    ),
    SettingDef(
        key="NEXT_PUBLIC_API_URL",
        friendly_name="Public API URL",
        description="The base URL the browser uses to reach the backend API. "
                    "Typically empty string (relative) in production and 'http://localhost:8000' in development.",
        category="frontend",
        type="string",
        is_dynamic=False,
        default="",
    ),
    SettingDef(
        key="NEXT_TELEMETRY_DISABLED",
        friendly_name="Disable Next.js Telemetry",
        description="When set to '1', disables Next.js anonymous usage telemetry sent to Vercel. "
                    "Has no effect on application functionality.",
        category="frontend",
        type="select",
        is_dynamic=False,
        possible_values=[["1", "Disabled"], ["0", "Enabled"]],
        default="1",
    ),
]

# ---------------------------------------------------------------------------
# Database connection settings (shown on the Database Configuration page)
# ---------------------------------------------------------------------------

DATABASE_SETTINGS: List[SettingDef] = [

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    SettingDef(
        key="POSTGRES_HOST",
        friendly_name="PostgreSQL Host",
        description="Hostname or IP address of the PostgreSQL server. "
                    "Use the Docker service name (e.g. 'postgres') inside a Compose stack.",
        category="postgres",
        type="string",
        is_dynamic=False,
        default="postgres",
    ),
    SettingDef(
        key="POSTGRES_PORT",
        friendly_name="PostgreSQL Port",
        description="TCP port the PostgreSQL server listens on. The default is 5432.",
        category="postgres",
        type="integer",
        is_dynamic=False,
        default="5432",
    ),
    SettingDef(
        key="POSTGRES_USER",
        friendly_name="PostgreSQL Username",
        description="Username the backend uses to authenticate with PostgreSQL. "
                    "This user must have sufficient privileges on the target database.",
        category="postgres",
        type="string",
        is_dynamic=False,
        default="baseline",
    ),
    SettingDef(
        key="POSTGRES_DB",
        friendly_name="PostgreSQL Database Name",
        description="Name of the specific database within the PostgreSQL cluster that the application uses. "
                    "Only this database will be affected by migrations and queries.",
        category="postgres",
        type="string",
        is_dynamic=False,
        default="baseline",
    ),
    SettingDef(
        key="POSTGRES_PASSWORD",
        friendly_name="PostgreSQL Password",
        description="Password for the PostgreSQL user. Stored as a Docker secret file in production. "
                    "Changing this requires a server restart.",
        category="postgres",
        type="string",
        is_dynamic=False,
        is_secret=True,
        default=None,
    ),

    # ── Redis ─────────────────────────────────────────────────────────────────
    SettingDef(
        key="REDIS_HOST",
        friendly_name="Redis Host",
        description="Hostname or IP address of the Redis server. "
                    "Use the Docker service name (e.g. 'redis') inside a Compose stack.",
        category="redis",
        type="string",
        is_dynamic=False,
        default="redis",
    ),
    SettingDef(
        key="REDIS_PORT",
        friendly_name="Redis Port",
        description="TCP port the Redis server listens on. The default is 6379.",
        category="redis",
        type="integer",
        is_dynamic=False,
        default="6379",
    ),
    SettingDef(
        key="REDIS_DB",
        friendly_name="Redis Database Index",
        description="Logical database number within Redis (0–15). "
                    "Default is 0. Use different indexes to isolate data between environments.",
        category="redis",
        type="integer",
        is_dynamic=False,
        default="0",
    ),
    SettingDef(
        key="REDIS_PASSWORD",
        friendly_name="Redis Password",
        description="Password for Redis authentication. Leave empty if your Redis instance does not "
                    "require authentication (common in internal Docker networks).",
        category="redis",
        type="string",
        is_dynamic=False,
        is_secret=True,
        default=None,
    ),
]

DATABASE_CATEGORIES = {
    "postgres": "PostgreSQL",
    "redis":    "Redis",
}

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

APP_SETTINGS_BY_KEY = {s.key: s for s in APP_SETTINGS}
DB_SETTINGS_BY_KEY  = {s.key: s for s in DATABASE_SETTINGS}

DYNAMIC_KEYS = {s.key for s in APP_SETTINGS if s.is_dynamic}
