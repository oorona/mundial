from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings

engine = None
AsyncSessionLocal = None

if settings.DB_HOST and settings.DB_USER and settings.DB_NAME:
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Confine every connection to the app schema.
    # asyncpg's server_settings sets the session-level search_path so that
    # all unqualified object references resolve to the app schema only,
    # never to public.
    schema = settings.effective_schema
    engine = create_async_engine(
        db_url,
        echo=False,
        connect_args={
            "server_settings": {"search_path": schema},
        },
    )
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    """
    Yield a database session with RLS bypassed.

    Use this dependency ONLY for endpoints that access non-guild-scoped
    tables (users, shards, llm_model_pricing, app_config, etc.).

    For guild-specific data use get_guild_db (from app.db.guild_session)
    which activates Row-Level Security for the request's guild.
    For cross-guild admin operations use get_admin_db (also guild_session).
    """
    if AsyncSessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Database not configured",
                "setup_required": True,
                "message": "Complete the setup wizard to configure the database connection.",
            },
        )
    async with AsyncSessionLocal() as session:
        # Bypass RLS for this session — safe for non-guild-scoped tables
        # and for existing code that manually filters by guild_id.
        # New guild-scoped endpoints should use get_guild_db instead.
        from sqlalchemy import text as _text
        await session.execute(_text("SET LOCAL app.bypass_guild_rls = 'true'"))
        yield session
