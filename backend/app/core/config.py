"""
Application configuration.

Loading order (highest priority first):
  1. Values already set in os.environ at import time
  2. Values from the encrypted settings file (injected by inject_into_environment())
  3. .env file (pydantic-settings fallback)
  4. Field defaults

All fields that require external infrastructure (DB, Redis, Discord) are
optional with safe defaults so the app can start in wizard mode even when
those systems haven't been configured yet.
"""

import os
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Inject encrypted settings BEFORE the Settings class is instantiated ───────
# This must happen first so that POSTGRES_HOST etc. are available when
# pydantic-settings reads the environment.
from app.core.encrypted_settings import inject_into_environment

inject_into_environment()   # True = file found and loaded, False = wizard mode


def load_secrets():
    """
    Load Docker secret files (_FILE env vars) into plain env vars.
    Runs after encrypted settings are injected; Docker secrets override
    encrypted-file values when both are present.
    """
    for key, value in list(os.environ.items()):
        if key.endswith("_FILE"):
            env_var = key[:-5]
            try:
                with open(value, "r") as f:
                    os.environ[env_var] = f.read().strip()
            except Exception as e:
                print(f"Warning: could not load secret {env_var} from {value}: {e}")


load_secrets()


class Settings(BaseSettings):
    PROJECT_NAME: str = os.getenv("APP_NAME", "Baseline Bot Platform API")
    API_V1_STR:   str = "/api/v1"

    BACKEND_CORS_ORIGINS: list[str] = []

    # ── PostgreSQL ─────────────────────────────────────────────────────────
    # All optional — absent when the app is running in wizard (setup) mode.
    DB_HOST:     str           = Field(default="",   alias="POSTGRES_HOST")
    DB_PORT:     int           = Field(default=5432, alias="POSTGRES_PORT")
    DB_USER:     str           = Field(default="",   alias="POSTGRES_USER")
    DB_NAME:     str           = Field(default="",   alias="POSTGRES_DB")
    DB_PASSWORD: Optional[str] = Field(default=None, alias="POSTGRES_PASSWORD")
    # Schema that owns all application objects.  Must never be "public".
    # Defaults to DB_USER when not explicitly set (set by setup_database.sh).
    DB_SCHEMA:   str           = Field(default="",   alias="POSTGRES_SCHEMA")

    # ── Redis ──────────────────────────────────────────────────────────────
    REDIS_HOST:     str           = Field(default="")
    REDIS_PORT:     int           = 6379
    REDIS_DB:       int           = 0
    REDIS_PASSWORD: Optional[str] = None

    # ── Bot Identity ───────────────────────────────────────────────────────
    BOT_NAME:           str = "My Discord Bot"
    BOT_TAGLINE:        str = ""
    BOT_TAGLINE_ES:     str = ""
    BOT_DESCRIPTION:    str = ""
    BOT_DESCRIPTION_ES: str = ""
    BOT_INVITE_URL:     str = ""

    # ── Discord ────────────────────────────────────────────────────────────
    DISCORD_CLIENT_ID:     Optional[str] = None
    DISCORD_CLIENT_SECRET: Optional[str] = None
    DISCORD_BOT_TOKEN:     Optional[str] = None
    DISCORD_REDIRECT_URI:  Optional[str] = None
    FRONTEND_URL:          str           = "http://localhost:3000"
    ADMIN_USER_IDS:        Optional[str] = None
    DISCORD_GUILD_ID:      Optional[str] = "1423815821674676267"
    DEVELOPER_ROLE_ID:     Optional[str] = "1513345032252297430"

    # ── LLM Providers ──────────────────────────────────────────────────────
    OPENAI_API_KEY:    Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY:    Optional[str] = None
    XAI_API_KEY:       Optional[str] = None

    # ── Auth ───────────────────────────────────────────────────────────────
    SECRET_KEY: str = "development_secret_key_change_in_production"
    ALGORITHM:  str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # ── Public site surface (Level 0 / PUBLIC) ───────────────────────────────
    # Configurable URL prefix for per-server public sites (e.g. /p/<slug>).
    # The backend treats this as the source of truth for canonical link
    # generation; the frontend mirrors it via NEXT_PUBLIC_SLUG_PREFIX (used by
    # a next.config rewrite onto the (public)/p route group).
    PUBLIC_SLUG_PREFIX:        str = Field(default="/p", alias="PUBLIC_SLUG_PREFIX")
    # Branding for the generic, project-wide landing page (not guild-scoped).
    PROJECT_PUBLIC_NAME:        str = Field(default="", alias="PROJECT_PUBLIC_NAME")
    PROJECT_PUBLIC_DESCRIPTION: str = Field(default="", alias="PROJECT_PUBLIC_DESCRIPTION")

    # ── Discord Activity (Embedded App SDK) ──────────────────────────────────
    # TTL for activity sessions minted by POST /auth/activity (seconds).
    ACTIVITY_SESSION_TTL:    int       = 60 * 60 * 12  # 12h
    # Extra CORS origins permitted for Activity requests (Discord proxy etc.).
    ACTIVITY_ALLOWED_ORIGINS: list[str] = []

    # ── Resolved schema ────────────────────────────────────────────────────
    @property
    def effective_schema(self) -> str:
        """
        The PostgreSQL schema used for all application objects.
        Falls back to DB_USER when DB_SCHEMA is not explicitly configured,
        since setup_database.sh creates a schema with the same name as the user.
        Never returns 'public'.
        """
        schema = self.DB_SCHEMA or self.DB_USER
        return schema if schema and schema != "public" else self.DB_USER

    # ── Setup state ────────────────────────────────────────────────────────
    @property
    def is_configured(self) -> bool:
        """True when all critical infrastructure settings are present."""
        return bool(self.DB_HOST and self.DB_USER and self.DB_NAME and self.REDIS_HOST)

    # ── Constructed URLs ───────────────────────────────────────────────────
    @property
    def DATABASE_URL(self) -> str:
        if not self.DB_HOST:
            return ""
        pw = f":{self.DB_PASSWORD}" if self.DB_PASSWORD else ""
        return f"postgresql://{self.DB_USER}{pw}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def REDIS_URL(self) -> str:
        if not self.REDIS_HOST:
            return ""
        pw = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{pw}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore",
    )


try:
    settings = Settings()
except Exception as e:
    print(f"WARNING: Settings init issue ({e}). Starting in wizard mode with defaults.")
    settings = Settings.model_construct(
        PROJECT_NAME="Baseline Bot Platform API",
        API_V1_STR="/api/v1",
        BACKEND_CORS_ORIGINS=[],
        DB_HOST="", DB_PORT=5432, DB_USER="", DB_NAME="", DB_PASSWORD=None, DB_SCHEMA="",
        REDIS_HOST="", REDIS_PORT=6379, REDIS_DB=0, REDIS_PASSWORD=None,
        BOT_NAME="My Discord Bot", BOT_TAGLINE="", BOT_TAGLINE_ES="",
        BOT_DESCRIPTION="", BOT_DESCRIPTION_ES="", BOT_INVITE_URL="",
        DISCORD_CLIENT_ID=None, DISCORD_CLIENT_SECRET=None,
        DISCORD_BOT_TOKEN=None, DISCORD_REDIRECT_URI=None,
        FRONTEND_URL="http://localhost:3000", ADMIN_USER_IDS=None,
        DISCORD_GUILD_ID="1423815821674676267", DEVELOPER_ROLE_ID="1513345032252297430",
        OPENAI_API_KEY=None, ANTHROPIC_API_KEY=None,
        GOOGLE_API_KEY=None, XAI_API_KEY=None,
        SECRET_KEY="development_secret_key_change_in_production",
        ALGORITHM="HS256", ACCESS_TOKEN_EXPIRE_MINUTES=10080,
    )
