/**
 * Frontend mirror of the backend settings definitions.
 *
 * This file is the single source of truth on the client side for:
 *   - Every configurable parameter (key, friendly name, description)
 *   - Whether a setting is dynamic (changeable at runtime) or static (needs restart)
 *   - Whether a setting is sensitive (masked in the UI)
 *   - Allowed values for select-type settings
 *
 * Keep this in sync with:
 *   backend/app/core/settings_definitions.py
 */

export type SettingType = 'string' | 'boolean' | 'integer' | 'select';
export type SettingCategory =
  | 'general'
  | 'discord'
  | 'api'
  | 'llm'
  | 'rate_limit'
  | 'features'
  | 'frontend'
  | 'postgres'
  | 'redis';

export interface PossibleValue {
  value: string;
  label: string;
}

export interface SettingDef {
  key: string;
  friendlyName: string;
  description: string;
  category: SettingCategory;
  type: SettingType;
  isDynamic: boolean;
  isSecret?: boolean;
  possibleValues?: PossibleValue[];
  default?: string;
}

// ---------------------------------------------------------------------------
// Category metadata
// ---------------------------------------------------------------------------

export const APP_CATEGORIES: Record<string, string> = {
  general:      'General',
  bot_identity: 'Bot Identity',
  discord:      'Discord',
  api:          'API & Security',
  llm:          'LLM / AI',
  rate_limit:   'Rate Limits',
  features:     'Feature Flags',
  frontend:     'Frontend (display only)',
};

export const DB_CATEGORIES: Record<string, string> = {
  postgres: 'PostgreSQL',
  redis:    'Redis',
};

// ---------------------------------------------------------------------------
// Application settings
// ---------------------------------------------------------------------------

export const APP_SETTINGS: SettingDef[] = [
  // ── General ────────────────────────────────────────────────────────────────
  {
    key: 'APP_NAME',
    friendlyName: 'Application Name',
    description:
      'The internal name of the platform used in API responses and service identifiers.',
    category: 'general',
    type: 'string',
    isDynamic: false,
    default: 'discord-bot-baseline',
  },
  {
    key: 'ENVIRONMENT',
    friendlyName: 'Environment',
    description:
      "Deployment environment. Controls certain safety checks and logging verbosity. Must be 'development', 'staging', or 'production'.",
    category: 'general',
    type: 'select',
    isDynamic: false,
    possibleValues: [
      { value: 'development', label: 'Development' },
      { value: 'staging',     label: 'Staging' },
      { value: 'production',  label: 'Production' },
    ],
    default: 'development',
  },
  {
    key: 'DEBUG',
    friendlyName: 'Debug Mode',
    description:
      'Enables verbose debug output across all services. In debug mode, additional stack traces and internal state are logged. Should be disabled in production.',
    category: 'general',
    type: 'boolean',
    isDynamic: true,
    default: 'false',
  },
  {
    key: 'LOG_LEVEL',
    friendlyName: 'Log Level',
    description:
      "Minimum severity level for log messages to be recorded. 'DEBUG' records everything; 'ERROR' records only failures.",
    category: 'general',
    type: 'select',
    isDynamic: true,
    possibleValues: [
      { value: 'DEBUG',    label: 'DEBUG — All messages' },
      { value: 'INFO',     label: 'INFO — Informational and above' },
      { value: 'WARNING',  label: 'WARNING — Warnings and above' },
      { value: 'ERROR',    label: 'ERROR — Errors only' },
      { value: 'CRITICAL', label: 'CRITICAL — Critical failures only' },
    ],
    default: 'INFO',
  },
  {
    key: 'LOG_FORMAT',
    friendlyName: 'Log Format',
    description:
      "'json' is recommended for production and log aggregation tools. 'text' is more readable during local development.",
    category: 'general',
    type: 'select',
    isDynamic: false,
    possibleValues: [
      { value: 'json', label: 'JSON (structured)' },
      { value: 'text', label: 'Text (human-readable)' },
    ],
    default: 'json',
  },
  {
    key: 'HOT_RELOAD',
    friendlyName: 'Hot Reload',
    description:
      'Automatically restarts the backend server when source files change. Only meaningful during development; must be disabled in production.',
    category: 'general',
    type: 'boolean',
    isDynamic: false,
    default: 'true',
  },

  // ── Discord ────────────────────────────────────────────────────────────────
  {
    key: 'DISCORD_CLIENT_ID',
    friendlyName: 'Discord OAuth Client ID',
    description:
      "The application's Client ID from the Discord Developer Portal. Required for OAuth2 login flows.",
    category: 'discord',
    type: 'string',
    isDynamic: false,
  },
  {
    key: 'DISCORD_CLIENT_SECRET',
    friendlyName: 'Discord OAuth Client Secret',
    description:
      'The OAuth2 client secret from the Discord Developer Portal. This value is sensitive and should be stored as a Docker secret file.',
    category: 'discord',
    type: 'string',
    isDynamic: false,
    isSecret: true,
  },
  {
    key: 'DISCORD_REDIRECT_URI',
    friendlyName: 'Discord OAuth Redirect URI',
    description:
      'The URL Discord redirects to after a user authorises the application. Must exactly match the redirect URI registered in the Discord Developer Portal.',
    category: 'discord',
    type: 'string',
    isDynamic: false,
    default: 'http://localhost:3000/auth/callback',
  },
  {
    key: 'DISCORD_BOT_TOKEN',
    friendlyName: 'Discord Bot Token',
    description:
      'Authentication token for the Discord bot. Treat this as a password — never commit it to source control. Stored as a Docker secret file in production.',
    category: 'discord',
    type: 'string',
    isDynamic: false,
    isSecret: true,
  },
  {
    key: 'DISCORD_GUILD_ID',
    friendlyName: 'Developer Guild ID',
    description:
      'Discord server (guild) ID used to identify developer/platform-admin members. Users who own this guild or hold the Developer Role are granted Level 5 access.',
    category: 'discord',
    type: 'string',
    isDynamic: false,
  },
  {
    key: 'DEVELOPER_ROLE_ID',
    friendlyName: 'Developer Role ID',
    description:
      'ID of the Discord role that grants platform-admin (Level 5) access. Any member of the Developer Guild holding this role is treated as a developer.',
    category: 'discord',
    type: 'string',
    isDynamic: false,
  },

  // ── API & Security ─────────────────────────────────────────────────────────
  {
    key: 'API_VERSION',
    friendlyName: 'API Version',
    description:
      "Version prefix appended to all API routes (e.g. 'v1' produces /api/v1/…). Changing this requires frontend configuration updates.",
    category: 'api',
    type: 'string',
    isDynamic: false,
    default: 'v1',
  },
  {
    key: 'API_SECRET_KEY',
    friendlyName: 'API Secret Key',
    description:
      'Secret used to sign session tokens. Must be a long, random string. Rotating this key will invalidate all active sessions.',
    category: 'api',
    type: 'string',
    isDynamic: false,
    isSecret: true,
  },
  {
    key: 'API_CORS_ORIGINS',
    friendlyName: 'CORS Allowed Origins',
    description:
      "Comma-separated list of URLs permitted to make cross-origin requests. Example: 'http://localhost:3000,https://yourdomain.com'.",
    category: 'api',
    type: 'string',
    isDynamic: true,
    default: 'http://localhost:3000',
  },
  {
    key: 'HEALTH_HOST',
    friendlyName: 'Health Check Host',
    description: "Network interface the health-check HTTP server binds to. Use '0.0.0.0' to listen on all interfaces.",
    category: 'api',
    type: 'string',
    isDynamic: false,
    default: '0.0.0.0',
  },
  {
    key: 'HEALTH_PORT',
    friendlyName: 'Health Check Port',
    description: 'Port number the health-check endpoint listens on.',
    category: 'api',
    type: 'integer',
    isDynamic: false,
    default: '8080',
  },

  // ── LLM / AI ──────────────────────────────────────────────────────────────
  {
    key: 'LLM_DEFAULT_PROVIDER',
    friendlyName: 'Default LLM Provider',
    description: 'The AI model provider used when no explicit provider is specified in a request.',
    category: 'llm',
    type: 'select',
    isDynamic: true,
    possibleValues: [
      { value: 'openai',    label: 'OpenAI' },
      { value: 'anthropic', label: 'Anthropic (Claude)' },
      { value: 'google',    label: 'Google (Gemini)' },
      { value: 'xai',       label: 'xAI (Grok)' },
    ],
    default: 'openai',
  },
  {
    key: 'LLM_MAX_RETRIES',
    friendlyName: 'LLM Max Retries',
    description: 'Maximum number of retry attempts for a failed LLM API call before returning an error.',
    category: 'llm',
    type: 'integer',
    isDynamic: true,
    default: '3',
  },
  {
    key: 'LLM_TIMEOUT_SECONDS',
    friendlyName: 'LLM Request Timeout',
    description: 'Maximum number of seconds to wait for a response from an LLM provider before timing out.',
    category: 'llm',
    type: 'integer',
    isDynamic: true,
    default: '60',
  },

  // ── Rate Limits ────────────────────────────────────────────────────────────
  {
    key: 'RATE_LIMIT_PER_USER',
    friendlyName: 'Per-User Rate Limit',
    description: 'Maximum number of API requests a single authenticated user may make per minute.',
    category: 'rate_limit',
    type: 'integer',
    isDynamic: true,
    default: '100',
  },
  {
    key: 'RATE_LIMIT_PER_GUILD',
    friendlyName: 'Per-Guild Rate Limit',
    description: 'Maximum number of API requests originating from a single Discord guild per minute.',
    category: 'rate_limit',
    type: 'integer',
    isDynamic: true,
    default: '500',
  },
  {
    key: 'RATE_LIMIT_GLOBAL',
    friendlyName: 'Global Rate Limit',
    description: 'Total maximum number of API requests across all users and guilds per minute.',
    category: 'rate_limit',
    type: 'integer',
    isDynamic: true,
    default: '1000',
  },

  // ── Feature Flags ──────────────────────────────────────────────────────────
  {
    key: 'ENABLE_LLM_FEATURES',
    friendlyName: 'Enable LLM Features',
    description:
      'Master switch for all large-language-model features. Disabling this blocks all requests to /api/v1/llm.',
    category: 'features',
    type: 'boolean',
    isDynamic: true,
    default: 'true',
  },
  {
    key: 'ENABLE_IMAGE_GENERATION',
    friendlyName: 'Enable Image Generation',
    description:
      'Enables the image-generation capability via AI providers. Requires ENABLE_LLM_FEATURES to also be enabled.',
    category: 'features',
    type: 'boolean',
    isDynamic: true,
    default: 'true',
  },
  {
    key: 'ENABLE_AUDIO_FEATURES',
    friendlyName: 'Enable Audio Features',
    description:
      'Enables audio transcription and text-to-speech capabilities. These features may incur additional cost on the AI provider.',
    category: 'features',
    type: 'boolean',
    isDynamic: true,
    default: 'false',
  },

  // ── Frontend (display only) ────────────────────────────────────────────────
  {
    key: 'NEXT_PUBLIC_APP_NAME',
    friendlyName: 'Public Application Name',
    description:
      'Application name shown in the browser tab, navigation, and public-facing pages. Requires a frontend rebuild to update.',
    category: 'frontend',
    type: 'string',
    isDynamic: false,
    default: 'My Discord Bot',
  },
  {
    key: 'NEXT_PUBLIC_API_URL',
    friendlyName: 'Public API URL',
    description:
      'The base URL the browser uses to reach the backend API. Typically empty (relative) in production.',
    category: 'frontend',
    type: 'string',
    isDynamic: false,
    default: '',
  },
  {
    key: 'NEXT_TELEMETRY_DISABLED',
    friendlyName: 'Disable Next.js Telemetry',
    description:
      "When set to '1', disables Next.js anonymous usage telemetry sent to Vercel. Has no effect on application functionality.",
    category: 'frontend',
    type: 'select',
    isDynamic: false,
    possibleValues: [
      { value: '1', label: 'Disabled' },
      { value: '0', label: 'Enabled' },
    ],
    default: '1',
  },
];

// ---------------------------------------------------------------------------
// Database connection settings
// ---------------------------------------------------------------------------

export const DATABASE_SETTINGS: SettingDef[] = [
  // ── PostgreSQL ─────────────────────────────────────────────────────────────
  {
    key: 'POSTGRES_HOST',
    friendlyName: 'PostgreSQL Host',
    description:
      "Hostname or IP address of the PostgreSQL server. Use the Docker service name (e.g. 'postgres') inside a Compose stack.",
    category: 'postgres',
    type: 'string',
    isDynamic: false,
    default: 'postgres',
  },
  {
    key: 'POSTGRES_PORT',
    friendlyName: 'PostgreSQL Port',
    description: 'TCP port the PostgreSQL server listens on. The default is 5432.',
    category: 'postgres',
    type: 'integer',
    isDynamic: false,
    default: '5432',
  },
  {
    key: 'POSTGRES_USER',
    friendlyName: 'PostgreSQL Username',
    description:
      'Username the backend uses to authenticate with PostgreSQL. This user must have sufficient privileges on the target database.',
    category: 'postgres',
    type: 'string',
    isDynamic: false,
    default: 'baseline',
  },
  {
    key: 'POSTGRES_DB',
    friendlyName: 'PostgreSQL Database Name',
    description:
      'Name of the specific database within the PostgreSQL cluster. Only this database will be affected by migrations and queries.',
    category: 'postgres',
    type: 'string',
    isDynamic: false,
    default: 'baseline',
  },
  {
    key: 'POSTGRES_PASSWORD',
    friendlyName: 'PostgreSQL Password',
    description:
      'Password for the PostgreSQL user. Stored as a Docker secret file in production. Changing this requires a server restart.',
    category: 'postgres',
    type: 'string',
    isDynamic: false,
    isSecret: true,
  },

  // ── Redis ──────────────────────────────────────────────────────────────────
  {
    key: 'REDIS_HOST',
    friendlyName: 'Redis Host',
    description:
      "Hostname or IP address of the Redis server. Use the Docker service name (e.g. 'redis') inside a Compose stack.",
    category: 'redis',
    type: 'string',
    isDynamic: false,
    default: 'redis',
  },
  {
    key: 'REDIS_PORT',
    friendlyName: 'Redis Port',
    description: 'TCP port the Redis server listens on. The default is 6379.',
    category: 'redis',
    type: 'integer',
    isDynamic: false,
    default: '6379',
  },
  {
    key: 'REDIS_DB',
    friendlyName: 'Redis Database Index',
    description:
      'Logical database number within Redis (0–15). Default is 0. Use different indexes to isolate data between environments.',
    category: 'redis',
    type: 'integer',
    isDynamic: false,
    default: '0',
  },
  {
    key: 'REDIS_PASSWORD',
    friendlyName: 'Redis Password',
    description:
      'Password for Redis authentication. Leave empty if your Redis instance does not require authentication.',
    category: 'redis',
    type: 'string',
    isDynamic: false,
    isSecret: true,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export const APP_SETTINGS_BY_KEY: Record<string, SettingDef> = Object.fromEntries(
  APP_SETTINGS.map((s) => [s.key, s])
);

export const DB_SETTINGS_BY_KEY: Record<string, SettingDef> = Object.fromEntries(
  DATABASE_SETTINGS.map((s) => [s.key, s])
);

export const DYNAMIC_KEYS: Set<string> = new Set(
  APP_SETTINGS.filter((s) => s.isDynamic).map((s) => s.key)
);
