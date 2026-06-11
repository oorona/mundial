import structlog
import os
from contextlib import asynccontextmanager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from redis.asyncio import Redis
from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional

logger = structlog.get_logger()

def _inject_encrypted_settings() -> None:
    """Load settings from the shared encrypted file into os.environ (setdefault)."""
    import json
    from pathlib import Path
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    settings_path = Path(os.getenv("SETTINGS_FILE_PATH", "/data/settings.enc"))
    key_file = os.getenv("ENCRYPTION_KEY_FILE", "").strip()
    master = ""
    if key_file:
        try:
            master = Path(key_file).read_text().strip()
        except OSError:
            pass
    if not master:
        master = os.getenv("ENCRYPTION_KEY", "").strip()
    if not master or not settings_path.exists():
        return
    try:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=b"baseline-platform-v1", iterations=480_000)
        key = kdf.derive(master.encode())
        raw = settings_path.read_bytes()
        plaintext = AESGCM(key).decrypt(raw[:12], raw[12:], None)
        for k, v in json.loads(plaintext).get("settings", {}).items():
            if v is not None:
                os.environ.setdefault(k, str(v))
    except Exception:
        pass

_inject_encrypted_settings()

class Config(BaseSettings):
    # Database configuration
    DB_HOST: str = Field(default="", alias="POSTGRES_HOST")
    DB_PORT: int = Field(default=5432, alias="POSTGRES_PORT")
    DB_USER: str = Field(default="", alias="POSTGRES_USER")
    DB_NAME: str = Field(default="", alias="POSTGRES_DB")
    DB_PASSWORD: Optional[str] = Field(default=None, alias="POSTGRES_PASSWORD")  # Loaded from secret
    DB_SCHEMA: str = Field(default="", alias="POSTGRES_SCHEMA")  # App schema (never "public")

    # Redis configuration
    REDIS_HOST: str = ""
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    
    # LLM API Keys (loaded from secrets)
    OPENAI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    XAI_API_KEY: Optional[str] = None
    
    # Discord configuration
    DISCORD_BOT_TOKEN: Optional[str] = None
    DISCORD_INTENTS: Optional[str] = None
    DISCORD_GUILD_ID: Optional[int] = None
    TARGET_USER_ID: Optional[str] = None
    
    @property
    def DATABASE_URL(self) -> str:
        """Construct DATABASE_URL from components"""
        password = self.DB_PASSWORD or ""
        password_part = f":{password}" if password else ""
        return f"postgresql://{self.DB_USER}{password_part}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def REDIS_URL(self) -> str:
        """Construct REDIS_URL from components"""
        password_part = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{password_part}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def effective_schema(self) -> str:
        """App schema for the bot's DB connection — mirrors the backend's
        resolution (DB_SCHEMA, else DB_USER; never 'public')."""
        schema = self.DB_SCHEMA or self.DB_USER
        return schema if schema and schema != "public" else self.DB_USER

    class Config:
        env_file = ".env"


class WorkerDB:
    """Bot-side database access for **worker cogs** (`tasks.loop` jobs that read
    and write Postgres on a timer). It is the bot-side analogue of the backend's
    ``get_admin_db`` / ``get_guild_db``.

    Single-writer guarantee: the bot is a single ``AutoShardedBot`` process, so
    timed jobs running here have exactly one writer. **Never scale the bot to
    multiple processes** — that would break the single-writer assumption these
    jobs rely on.

    RLS note: ``SET LOCAL`` is transaction-scoped. The context managers set the
    RLS state on entry; if you ``commit()`` inside the session, re-enter the
    context manager (or re-apply the setting) before further guild-scoped work.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    @asynccontextmanager
    async def worker_session(self):
        """Yield an RLS-**bypassed** session for cross-guild iteration."""
        async with self._session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_guild_rls = 'true'"))
            yield session

    @asynccontextmanager
    async def scoped_session(self, guild_id: int):
        """Yield an RLS-**active** session scoped to a single guild."""
        async with self._session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_guild_rls = 'false'"))
            await session.execute(text(f"SET LOCAL app.current_guild_id = '{int(guild_id)}'"))
            yield session

class BotServices:
    def __init__(self):
        self._load_secrets()
        self.config = Config()
        self.db_engine = None
        self.session_factory = None
        self.db = None       # WorkerDB — DB access for worker cogs (bot.services.db)
        self.redis = None
        self.llm = None
        if self.config.DB_HOST and self.config.REDIS_HOST:
            db_url = self.config.DATABASE_URL
            if db_url.startswith("postgresql://"):
                db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            # Confine the bot's connections to the app schema, exactly like the
            # backend (app/db/session.py), so unqualified names never resolve to
            # public and RLS policies apply to the same tables.
            self.db_engine = create_async_engine(
                db_url,
                connect_args={"server_settings": {"search_path": self.config.effective_schema}},
            )
            self.session_factory = async_sessionmaker(self.db_engine, expire_on_commit=False)
            self.db = WorkerDB(self.session_factory)
            self.redis = Redis.from_url(self.config.REDIS_URL)

    def _load_secrets(self):
        """Load secrets from Docker secret files into environment variables."""
        for key, value in os.environ.items():
            if key.endswith('_FILE'):
                env_var = key[:-5]
                try:
                    with open(value, 'r') as f:
                        secret_value = f.read().strip()
                    os.environ[env_var] = secret_value
                    logger.info(f"Loaded secret {env_var} from {value}")
                except Exception as e:
                    logger.error(f"Failed to load secret {env_var}: {e}")
        

    async def initialize(self, http_session=None):
        from .llm import LLMService
        from .analysis import AnalysisService
        
        self.llm = LLMService(self.config)
        self.llm.set_redis(self.redis)
        self.llm.set_db_session_factory(self.session_factory)
        if http_session:
            self.llm.set_http_session(http_session)
        self.llm.set_db_session_factory(self.session_factory)
        
        self.analysis = AnalysisService(self.llm, self.redis)
        
        logger.info("Services initialized")

    async def close(self):
        if self.db_engine:
            await self.db_engine.dispose()
        if self.redis:
            await self.redis.close()
