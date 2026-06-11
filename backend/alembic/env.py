import asyncio
from logging.config import fileConfig
import os
import sys

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add backend directory to path
sys.path.append(os.getcwd())

from app.models import Base

# Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# ── Load encrypted settings and Docker secret files ───────────────────────────
# Inject the encrypted settings file into the environment so that DB_* vars
# are available when Alembic runs outside the FastAPI process (e.g. during
# the wizard's apply-migrations call).
try:
    sys.path.insert(0, os.path.join(os.getcwd(), "app"))
    from app.core.encrypted_settings import inject_into_environment
    inject_into_environment()
except Exception:
    pass

# Load any remaining _FILE secret references
for key, value in list(os.environ.items()):
    if key.endswith("_FILE"):
        env_var = key[:-5]
        try:
            with open(value, "r") as f:
                os.environ[env_var] = f.read().strip()
        except Exception as e:
            print(f"Warning: could not load secret {env_var}: {e}")

# ── Build the database URL ─────────────────────────────────────────────────────
db_host     = os.environ.get("DB_HOST",     os.environ.get("POSTGRES_HOST",     ""))
db_port     = os.environ.get("DB_PORT",     os.environ.get("POSTGRES_PORT",     "5432"))
db_user     = os.environ.get("DB_USER",     os.environ.get("POSTGRES_USER",     ""))
db_name     = os.environ.get("DB_NAME",     os.environ.get("POSTGRES_DB",       ""))
db_password = os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))

if not db_host or not db_user or not db_name:
    raise RuntimeError(
        "Database credentials not configured. "
        "Set DB_HOST, DB_USER, and DB_NAME (or POSTGRES_HOST, POSTGRES_USER, POSTGRES_DB) "
        "before running Alembic. These are loaded automatically when running through the "
        "Setup Wizard or after the encrypted settings file is present."
    )

# Schema always equals the username — one schema per app user, never public.
db_schema = os.environ.get("DB_SCHEMA", os.environ.get("POSTGRES_SCHEMA", ""))
if not db_schema or db_schema == "public":
    db_schema = db_user

password_part = f":{db_password}" if db_password else ""
db_url = f"postgresql+asyncpg://{db_user}{password_part}@{db_host}:{db_port}/{db_name}"

config.set_main_option("sqlalchemy.url", db_url)


# ── Migration helpers ─────────────────────────────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Store alembic_version inside the app schema, never public.
        version_table_schema=db_schema,
        include_schemas=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=db_schema,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # Set search_path at the connection level so every query alembic
        # makes — including _ensure_version_table — targets the app schema.
        connect_args={"server_settings": {"search_path": db_schema}},
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
