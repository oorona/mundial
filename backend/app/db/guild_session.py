"""
Guild-scoped database sessions — the correct way to access guild data.

Three session providers are available, each with a distinct purpose:

┌─────────────────┬──────────────────────────────────────────────────────┐
│ Dependency      │ When to use                                          │
├─────────────────┼──────────────────────────────────────────────────────┤
│ get_guild_db    │ Guild-specific endpoints. RLS is ACTIVE — only rows  │
│                 │ belonging to the current guild are visible/writable. │
├─────────────────┼──────────────────────────────────────────────────────┤
│ get_admin_db    │ Platform-admin endpoints that legitimately need       │
│                 │ cross-guild or global access. RLS bypassed.          │
│                 │ Automatically requires verify_platform_admin.        │
├─────────────────┼──────────────────────────────────────────────────────┤
│ get_db          │ Endpoints that access ONLY non-guild-scoped tables   │
│                 │ (users, shards, llm_model_pricing, app_config, etc.) │
│                 │ RLS is bypassed for backward compatibility.           │
└─────────────────┴──────────────────────────────────────────────────────┘

How RLS is applied
──────────────────
PostgreSQL Row-Level Security (RLS) is enabled on every guild-scoped
table (migration 1.1.0).  The active policy is:

    USING (
        guild_id = current_setting('app.current_guild_id', true)::bigint
        OR current_setting('app.bypass_guild_rls', true) = 'true'
    )

get_guild_db sets:  SET LOCAL app.current_guild_id = '<guild_id>'
get_admin_db sets:  SET LOCAL app.bypass_guild_rls = 'true'
get_db sets:        SET LOCAL app.bypass_guild_rls = 'true'  (backward compat)

SET LOCAL is transaction-scoped: the setting is automatically cleared
when the transaction commits or rolls back, so connection pool connections
are never left in a dirty state.

Important
─────────
- FastAPI resolves `guild_id: int` from the path parameter automatically.
  Your endpoint must have `{guild_id}` in its route path.
- Use get_guild_db for ALL endpoints under /{guild_id}/.
- Use get_admin_db for cross-guild admin operations (requires L5 auth).
- Never use get_db for endpoints that touch guild-scoped tables.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException

from app.api.deps import verify_platform_admin
from app.db.session import get_db
from app.db.redis import get_redis_optional


async def get_guild_db(
    guild_id: int,
    db: AsyncSession = Depends(get_db),
) -> AsyncSession:
    """
    Yield a database session scoped to *guild_id*.

    PostgreSQL RLS is activated for this session: every query on a
    guild-scoped table is automatically filtered to rows where
    guild_id matches.  INSERT/UPDATE with a mismatched guild_id is
    rejected by the database engine.

    FastAPI resolves `guild_id` from the route path parameter — the
    route must include `/{guild_id}/` in its path.

    Example
    -------
        @router.get("/{guild_id}/tickets")
        async def list_tickets(
            guild_id: int,
            db: AsyncSession = Depends(get_guild_db),
        ):
            # Only this guild's tickets are returned, even without
            # an explicit WHERE clause.
            return (await db.execute(select(Ticket))).scalars().all()
    """
    # get_db (our base dependency) sets bypass_guild_rls='true' so that
    # global-table queries (users, shards, etc.) work without a guild context.
    # For guild-scoped sessions we must override that: disable the bypass and
    # activate the guild-specific RLS policy instead.  This ensures:
    #   1. Every query on a guild-scoped table sees ONLY rows for this guild.
    #   2. The FK check on guilds.id (FORCE RLS) resolves correctly because
    #      guilds.id = current_guild_id satisfies the policy.
    await db.execute(text("SET LOCAL app.bypass_guild_rls = 'false'"))
    await db.execute(text(f"SET LOCAL app.current_guild_id = '{int(guild_id)}'"))
    yield db


async def get_admin_db(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
) -> AsyncSession:
    """
    Yield a database session with RLS bypassed.

    Use this ONLY in platform-admin endpoints (Level 5) that have a
    legitimate need to read or write data across multiple guilds —
    for example, the database management page or background jobs.

    The bypass flag is set for the current transaction only and cleared
    automatically when the session closes.

    The verify_platform_admin dependency is included automatically:
    any non-admin request is rejected with 403 before the session is
    even opened.
    """
    await db.execute(text("SET LOCAL app.bypass_guild_rls = 'true'"))
    yield db


async def get_public_guild_db(
    slug: str,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_optional),
) -> AsyncSession:
    """Resolve a public *slug* to a guild and yield an RLS-active session
    scoped to that guild — the framework primitive for **public, no-auth,
    per-server pages** (Level 0 / PUBLIC).

    Why a dedicated dependency: the ``guilds`` table is guild-scoped (RLS on
    ``id``), so the slug→``guild_id`` lookup is a chicken-and-egg problem — we
    can't scope to a guild we haven't identified yet. This dependency therefore:

      1. resolves the slug RLS-**bypassed** (``get_db`` already set
         ``bypass_guild_rls='true'``) via :func:`app.core.slugs.resolve`;
      2. raises 404 if the slug is unknown or the guild is inactive;
      3. switches the same session to RLS-**active**, scoped to the resolved
         guild, exactly like :func:`get_guild_db`.

    FastAPI resolves ``slug`` from the route path — the route must include
    ``/{slug}`` (or ``/{slug}/…``). No authentication is required, so plugin
    public routes that use this must export at Level 0/1 on the frontend.

    Example
    -------
        @router.get("/public/site/{slug}/canvas")
        async def public_canvas(
            slug: str,
            db: AsyncSession = Depends(get_public_guild_db),
        ):
            # RLS is active for the resolved guild — only its rows are visible.
            return (await db.execute(select(Pixel))).scalars().all()
    """
    # Lazy import avoids a circular import at module load (slugs imports models,
    # which is imported widely across the app).
    from app.core import slugs

    guild_id = await slugs.resolve(redis, db, slug)
    if guild_id is None:
        raise HTTPException(status_code=404, detail="Unknown or inactive site")

    await db.execute(text("SET LOCAL app.bypass_guild_rls = 'false'"))
    await db.execute(text(f"SET LOCAL app.current_guild_id = '{int(guild_id)}'"))
    # Stash the resolved id so downstream code/route handlers can read it
    # without re-resolving (FastAPI can't inject it as a separate param).
    db.info["public_guild_id"] = guild_id
    yield db
