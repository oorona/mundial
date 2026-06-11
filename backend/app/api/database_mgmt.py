"""
Database Management API — Level 5 (Platform Admin only)

Provides endpoints for:
  - Inspecting the live PostgreSQL and Redis connections
  - Comparing framework version vs database schema version
  - Listing and applying pending Alembic migrations
  - Running a full database validation test suite
  - Testing connection parameters supplied by the caller
"""

import asyncio
import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, AsyncConnection  # noqa: F401

from app.api.deps import verify_platform_admin
from app.models import DbMigrationHistory
from app.core.version import (
    FRAMEWORK_VERSION,
    MIGRATION_CHANGELOG,
    PLUGIN_MIGRATIONS,
    REQUIRED_DB_REVISION,
    _version_key,
    get_app_version_for_revision,
    get_changelog_entry,
    get_plugin_migration,
    get_upgrade_path,
    is_plugin_revision,
)
from app.core.config import settings
from app.db.redis import get_redis
from app.db.session import get_db, engine

router = APIRouter()
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    """Run alembic with DB_SCHEMA injected so migrations target the app schema."""
    env = os.environ.copy()
    schema = settings.effective_schema
    if schema:
        env["DB_SCHEMA"]       = schema
        env["POSTGRES_SCHEMA"] = schema
    return subprocess.run(
        ["alembic"] + list(args),
        capture_output=True,
        text=True,
        cwd="/app",
        env=env,
    )


async def _get_alembic_revisions(db: AsyncSession) -> set[str]:
    """Return ALL current Alembic revision IDs.

    With independent plugin branches each installed plugin adds its own row to
    alembic_version.  The framework head is always a separate row from any
    plugin revision.  Old linear-chain plugins produce only one row.
    """
    try:
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        return {row[0] for row in result.fetchall()}
    except Exception:
        return set()


async def _get_alembic_current(db: AsyncSession) -> Optional[str]:
    """Return the current Alembic revision for the framework branch.

    With independent plugin branches, alembic_version may have several rows.
    We return the framework head if it is present.  Fallback: for legacy
    linear-chain installs (plugin revision is the only row), we return that
    single revision so the rest of the logic can handle it as before.
    """
    revisions = await _get_alembic_revisions(db)
    if not revisions:
        return None
    if REQUIRED_DB_REVISION in revisions:
        return REQUIRED_DB_REVISION
    # Legacy single-revision case (linear chain or framework not at head)
    if len(revisions) == 1:
        return next(iter(revisions))
    # Multiple revisions but framework head not present — return the most
    # recent framework revision that is applied
    for entry in reversed(MIGRATION_CHANGELOG):
        if entry["head_revision"] in revisions:
            return entry["head_revision"]
    return next(iter(revisions))


async def _get_alembic_history() -> List[Dict[str, str]]:
    """Parse `alembic history` output into a list of revision dicts."""
    proc = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _run_alembic("history", "--verbose")
    )
    revisions = []
    current_rev = None
    for line in proc.stdout.splitlines():
        if line.startswith("Rev:"):
            parts = line.replace("Rev:", "").strip().split(" ")
            current_rev = parts[0].strip().rstrip(",")
        elif line.startswith("Parent:") and current_rev:
            revisions.append({"revision": current_rev, "parent": line.replace("Parent:", "").strip()})
    return revisions


# ---------------------------------------------------------------------------
# Expected schema for the validation suite
# ---------------------------------------------------------------------------

EXPECTED_TABLES: Dict[str, List[Dict[str, Any]]] = {
    "users": [
        {"name": "id",              "type": "bigint",  "nullable": False},
        {"name": "username",        "type": "varchar", "nullable": False},
        {"name": "discriminator",   "type": "varchar", "nullable": True},
        {"name": "avatar_url",      "type": "varchar", "nullable": True},
        {"name": "refresh_token",   "type": "varchar", "nullable": True},
        {"name": "token_expires_at","type": "timestamp with time zone", "nullable": True},
        {"name": "created_at",      "type": "timestamp with time zone", "nullable": True},
        {"name": "updated_at",      "type": "timestamp with time zone", "nullable": True},
        {"name": "preferences",     "type": "json",    "nullable": True},
    ],
    "guilds": [
        {"name": "id",        "type": "bigint",  "nullable": False},
        {"name": "name",      "type": "varchar", "nullable": False},
        {"name": "icon_url",  "type": "varchar", "nullable": True},
        {"name": "owner_id",  "type": "bigint",  "nullable": False},
        {"name": "joined_at", "type": "timestamp with time zone", "nullable": True},
        {"name": "is_active", "type": "boolean", "nullable": True},
    ],
    "authorized_users": [
        {"name": "id",               "type": "bigint",  "nullable": False},
        {"name": "user_id",          "type": "bigint",  "nullable": False},
        {"name": "guild_id",         "type": "bigint",  "nullable": False},
        {"name": "permission_level", "type": "permissionlevel", "nullable": True},
        {"name": "created_at",       "type": "timestamp with time zone", "nullable": True},
        {"name": "created_by",       "type": "bigint",  "nullable": True},
    ],
    "authorized_roles": [
        {"name": "id",               "type": "bigint",  "nullable": False},
        {"name": "guild_id",         "type": "bigint",  "nullable": False},
        {"name": "role_id",          "type": "varchar", "nullable": False},
        {"name": "permission_level", "type": "permissionlevel", "nullable": True},
        {"name": "created_at",       "type": "timestamp with time zone", "nullable": True},
        {"name": "created_by",       "type": "bigint",  "nullable": True},
    ],
    "guild_settings": [
        {"name": "id",           "type": "bigint",  "nullable": False},
        {"name": "guild_id",     "type": "bigint",  "nullable": False},
        {"name": "settings_json","type": "json",    "nullable": True},
        {"name": "updated_at",   "type": "timestamp with time zone", "nullable": True},
        {"name": "updated_by",   "type": "bigint",  "nullable": True},
    ],
    "audit_logs": [
        {"name": "id",         "type": "bigint",  "nullable": False},
        {"name": "guild_id",   "type": "bigint",  "nullable": False},
        {"name": "user_id",    "type": "bigint",  "nullable": False},
        {"name": "action",     "type": "varchar", "nullable": False},
        {"name": "details",    "type": "json",    "nullable": True},
        {"name": "created_at", "type": "timestamp with time zone", "nullable": True},
    ],
    "user_tokens": [
        {"name": "id",          "type": "bigint",  "nullable": False},
        {"name": "user_id",     "type": "bigint",  "nullable": False},
        {"name": "token_hash",  "type": "varchar", "nullable": False},
        {"name": "created_at",  "type": "timestamp with time zone", "nullable": True},
        {"name": "expires_at",  "type": "timestamp with time zone", "nullable": False},
        {"name": "last_used_at","type": "timestamp with time zone", "nullable": True},
        {"name": "client_info", "type": "varchar", "nullable": True},
    ],
    "shards": [
        {"name": "shard_id",       "type": "bigint",  "nullable": False},
        {"name": "status",         "type": "varchar", "nullable": True},
        {"name": "latency",        "type": "bigint",  "nullable": True},
        {"name": "guild_count",    "type": "bigint",  "nullable": True},
        {"name": "last_heartbeat", "type": "timestamp with time zone", "nullable": True},
    ],
    "llm_model_pricing": [
        {"name": "id",                 "type": "bigint",  "nullable": False},
        {"name": "provider",           "type": "varchar", "nullable": False},
        {"name": "model",              "type": "varchar", "nullable": False},
        {"name": "input_cost_per_1k",  "type": "double precision", "nullable": True},
        {"name": "output_cost_per_1k", "type": "double precision", "nullable": True},
        {"name": "is_active",          "type": "boolean", "nullable": True},
        {"name": "updated_at",         "type": "timestamp with time zone", "nullable": True},
    ],
    "llm_usage": [
        {"name": "id",         "type": "bigint",  "nullable": False},
        {"name": "provider",   "type": "varchar", "nullable": False},
        {"name": "model",      "type": "varchar", "nullable": False},
        {"name": "tokens",     "type": "bigint",  "nullable": True},
        {"name": "cost",       "type": "double precision", "nullable": True},
        {"name": "timestamp",  "type": "timestamp with time zone", "nullable": True},
    ],
    "llm_usage_summary": [
        {"name": "id",           "type": "bigint",  "nullable": False},
        {"name": "period_start", "type": "timestamp with time zone", "nullable": False},
        {"name": "period_type",  "type": "varchar", "nullable": False},
        {"name": "provider",     "type": "varchar", "nullable": False},
        {"name": "model",        "type": "varchar", "nullable": False},
    ],
    "app_config": [
        {"name": "id",         "type": "bigint",  "nullable": False},
        {"name": "key",        "type": "varchar", "nullable": False},
        {"name": "value",      "type": "text",    "nullable": False},
        {"name": "updated_at", "type": "timestamp with time zone", "nullable": True},
        {"name": "updated_by", "type": "bigint",  "nullable": True},
    ],
    "alembic_version": [
        {"name": "version_num", "type": "varchar", "nullable": False},
    ],
    "db_migration_history": [
        {"name": "id",            "type": "bigint",  "nullable": False},
        {"name": "from_revision", "type": "varchar", "nullable": True},
        {"name": "to_revision",   "type": "varchar", "nullable": False},
        {"name": "from_version",  "type": "varchar", "nullable": True},
        {"name": "to_version",    "type": "varchar", "nullable": True},
        {"name": "applied_at",    "type": "timestamp with time zone", "nullable": True},
        {"name": "applied_by",    "type": "bigint",  "nullable": True},
        {"name": "duration_ms",   "type": "bigint",  "nullable": True},
        {"name": "status",        "type": "varchar", "nullable": False},
        {"name": "error",         "type": "text",    "nullable": True},
    ],
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/info")
async def get_database_info(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Return framework version, database schema version, connection status for
    both PostgreSQL and Redis, and whether a schema upgrade is needed.
    """
    # ── PostgreSQL ────────────────────────────────────────────────────────────
    pg_status: Dict[str, Any] = {"status": "error"}
    current_revision: Optional[str] = None
    try:
        result = await db.execute(text("SELECT version()"))
        pg_version = result.scalar()

        result = await db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))
        db_size = result.scalar()

        result = await db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"))
        active_conns = result.scalar()

        current_revision = await _get_alembic_current(db)

        pg_status = {
            "status":           "connected",
            "version":          pg_version,
            "size":             db_size,
            "active_connections": active_conns,
            "current_revision": current_revision,
        }
    except Exception as exc:
        pg_status = {"status": "error", "error": str(exc)}

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_status: Dict[str, Any] = {"status": "error"}
    try:
        info = await redis.info()
        redis_status = {
            "status":            "connected",
            "version":           info.get("redis_version"),
            "used_memory_human": info.get("used_memory_human"),
            "connected_clients": info.get("connected_clients"),
            "uptime_in_days":    info.get("uptime_in_days"),
        }
    except Exception as exc:
        redis_status = {"status": "error", "error": str(exc)}

    # ── Version comparison ────────────────────────────────────────────────────
    # schema_match: framework migrations are applied.  A plugin revision sitting
    # on top of REQUIRED_DB_REVISION is still a match — plugins do not change
    # the framework version.
    current_db_version = get_app_version_for_revision(current_revision)
    framework_applied  = (
        current_revision == REQUIRED_DB_REVISION
        or is_plugin_revision(current_revision)
    )
    schema_match   = framework_applied
    upgrade_needed = not framework_applied and current_revision is not None
    upgrade_path   = get_upgrade_path(current_revision) if upgrade_needed else []

    revision_history = {
        entry["version"]: entry["head_revision"]
        for entry in MIGRATION_CHANGELOG
    }

    return {
        "framework_version":    FRAMEWORK_VERSION,
        "current_db_version":   current_db_version,
        "required_db_revision": REQUIRED_DB_REVISION,
        "current_db_revision":  current_revision,
        "schema_match":         schema_match,
        "upgrade_needed":       upgrade_needed,
        "upgrade_path":         upgrade_path,
        "revision_history":     revision_history,
        "plugin_migrations":    PLUGIN_MIGRATIONS,
        "postgres":             pg_status,
        "redis":                redis_status,
    }


@router.get("/migrations")
async def list_migrations(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Return version-aware migration status.

    Each entry in ``changelog`` represents one app version and shows:
    - which Alembic revisions it introduced
    - whether it has already been applied to the live database
    - whether it is the version that matches the current DB revision

    ``pending_versions`` is the subset of changelog entries not yet applied.
    """
    current_revision   = await _get_alembic_current(db)
    applied_revisions  = await _get_alembic_revisions(db)
    current_db_version = get_app_version_for_revision(current_revision)
    upgrade_path       = get_upgrade_path(current_revision)

    # Annotate each changelog entry with live status
    changelog = []
    for entry in MIGRATION_CHANGELOG:
        is_current = entry["head_revision"] == current_revision
        is_applied = (
            current_db_version is not None
            and _version_key(entry["version"]) <= _version_key(current_db_version)
        )
        changelog.append({
            **entry,
            "is_current":      is_current,
            "already_applied": is_applied,
        })

    pending_versions = [e for e in upgrade_path if not e.get("already_applied")]

    # Plugin migrations are independent Alembic branches — each plugin's
    # head_revision appears as its own row in alembic_version when applied.
    # For legacy linear-chain installs the revision set check still works
    # because the plugin revision IS in the set.
    plugin_changelog = [
        {**entry, "already_applied": entry["head_revision"] in applied_revisions}
        for entry in PLUGIN_MIGRATIONS
    ]

    framework_applied       = REQUIRED_DB_REVISION in applied_revisions or is_plugin_revision(current_revision)
    any_plugin_applied      = any(is_plugin_revision(r) for r in applied_revisions)

    return {
        "current_revision":           current_revision,
        "current_db_version":         current_db_version,
        "framework_version":          FRAMEWORK_VERSION,
        "head_revision":              REQUIRED_DB_REVISION,
        "schema_up_to_date":          framework_applied,
        "is_plugin_revision_current": any_plugin_applied,
        "changelog":                  changelog,
        "pending_versions":           pending_versions,
        "plugin_migrations":          plugin_changelog,
    }


class UpgradeToRequest(BaseModel):
    target_version: str


@router.post("/migrations/upgrade")
async def apply_all_migrations(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Run `alembic upgrade head` — applies ALL pending migrations.
    Use this when you want to jump straight to the current app version.
    Records the upgrade in db_migration_history.
    """
    from_revision = await _get_alembic_current(db)
    from_version  = get_app_version_for_revision(from_revision)

    start_ms = time.monotonic()
    proc = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _run_alembic("upgrade", "head")
    )
    duration_ms = int((time.monotonic() - start_ms) * 1000)

    success = proc.returncode == 0
    to_revision = await _get_alembic_current(db)
    to_version  = get_app_version_for_revision(to_revision)

    record = DbMigrationHistory(
        from_revision = from_revision,
        to_revision   = to_revision or REQUIRED_DB_REVISION,
        from_version  = from_version,
        to_version    = to_version,
        applied_by    = int(_admin["user_id"]),
        duration_ms   = duration_ms,
        status        = "success" if success else "failure",
        error         = proc.stderr if not success else None,
    )
    db.add(record)
    await db.commit()

    if success:
        logger.info("database_upgraded_to_head", admin_id=_admin.get("user_id"),
                    from_revision=from_revision, to_revision=to_revision)
    else:
        logger.error("database_upgrade_failed", stderr=proc.stderr)
    return {
        "success":     success,
        "stdout":      proc.stdout,
        "stderr":      proc.stderr,
        "return_code": proc.returncode,
    }


@router.post("/migrations/upgrade-to")
async def upgrade_to_version(
    body: UpgradeToRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Run `alembic upgrade <head_revision>` for a specific app version.

    This lets operators upgrade one version at a time rather than jumping
    directly to head.  Useful when each version requires manual data
    migration steps between schema upgrades.
    """
    entry = get_changelog_entry(body.target_version)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{body.target_version}' not found in MIGRATION_CHANGELOG.",
        )

    target_revision = entry["head_revision"]
    from_revision   = await _get_alembic_current(db)
    from_version    = get_app_version_for_revision(from_revision)

    start_ms = time.monotonic()
    proc = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _run_alembic("upgrade", target_revision)
    )
    duration_ms = int((time.monotonic() - start_ms) * 1000)

    success     = proc.returncode == 0
    to_revision = await _get_alembic_current(db)
    to_version  = get_app_version_for_revision(to_revision)

    record = DbMigrationHistory(
        from_revision = from_revision,
        to_revision   = to_revision or target_revision,
        from_version  = from_version,
        to_version    = to_version,
        applied_by    = int(_admin["user_id"]),
        duration_ms   = duration_ms,
        status        = "success" if success else "failure",
        error         = proc.stderr if not success else None,
    )
    db.add(record)
    await db.commit()

    if success:
        logger.info(
            "database_upgraded_to_version",
            target=body.target_version,
            revision=target_revision,
            admin_id=_admin.get("user_id"),
        )
    else:
        logger.error("database_upgrade_to_version_failed", stderr=proc.stderr)
    return {
        "success":          success,
        "target_version":   body.target_version,
        "target_revision":  target_revision,
        "stdout":           proc.stdout,
        "stderr":           proc.stderr,
        "return_code":      proc.returncode,
    }


@router.post("/migrations/framework/upgrade")
async def upgrade_framework_schema(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Apply all pending framework migrations up to REQUIRED_DB_REVISION.

    Plugin migrations are on independent branches and are NOT affected by this
    endpoint.  Use POST /migrations/plugins/{name}/apply for plugins.
    """
    from_revision = await _get_alembic_current(db)
    from_version  = get_app_version_for_revision(from_revision)

    start_ms = time.monotonic()
    proc = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _run_alembic("upgrade", REQUIRED_DB_REVISION)
    )
    duration_ms = int((time.monotonic() - start_ms) * 1000)

    success     = proc.returncode == 0
    to_revision = await _get_alembic_current(db)
    to_version  = get_app_version_for_revision(to_revision)

    record = DbMigrationHistory(
        from_revision = from_revision,
        to_revision   = to_revision or REQUIRED_DB_REVISION,
        from_version  = from_version,
        to_version    = to_version,
        applied_by    = int(_admin["user_id"]),
        duration_ms   = duration_ms,
        status        = "success" if success else "failure",
        error         = proc.stderr if not success else None,
    )
    db.add(record)
    await db.commit()

    if success:
        logger.info("framework_schema_upgraded", admin_id=_admin.get("user_id"),
                    from_revision=from_revision, to_revision=to_revision)
    else:
        logger.error("framework_schema_upgrade_failed", stderr=proc.stderr)
    return {
        "success":     success,
        "stdout":      proc.stdout,
        "stderr":      proc.stderr,
        "return_code": proc.returncode,
    }


@router.post("/migrations/plugins/{plugin_name}/apply")
async def apply_plugin_migration(
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Apply the migration for a specific plugin.

    Plugin migrations are independent Alembic branches — this runs
    `alembic upgrade <plugin_head_revision>` which only touches the
    plugin's branch and never the framework chain.
    """
    entry = get_plugin_migration(plugin_name)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Plugin '{plugin_name}' not found in migration_inventory.json.",
        )

    target_revision = entry.get("head_revision")
    if not target_revision:
        raise HTTPException(status_code=422, detail=f"Plugin '{plugin_name}' has no head_revision.")

    from_revision = await _get_alembic_current(db)
    from_version  = get_app_version_for_revision(from_revision)

    start_ms = time.monotonic()
    proc = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _run_alembic("upgrade", target_revision)
    )
    duration_ms = int((time.monotonic() - start_ms) * 1000)

    success     = proc.returncode == 0
    to_revision = await _get_alembic_current(db)

    record = DbMigrationHistory(
        from_revision = from_revision,
        to_revision   = to_revision or target_revision,
        from_version  = from_version,
        to_version    = f"plugin:{plugin_name}@{entry.get('version', '?')}",
        applied_by    = int(_admin["user_id"]),
        duration_ms   = duration_ms,
        status        = "success" if success else "failure",
        error         = proc.stderr if not success else None,
    )
    db.add(record)
    await db.commit()

    if success:
        logger.info("plugin_migration_applied", plugin=plugin_name,
                    revision=target_revision, admin_id=_admin.get("user_id"))
    else:
        logger.error("plugin_migration_failed", plugin=plugin_name, stderr=proc.stderr)
    return {
        "success":     success,
        "plugin":      plugin_name,
        "revision":    target_revision,
        "stdout":      proc.stdout,
        "stderr":      proc.stderr,
        "return_code": proc.returncode,
    }


@router.post("/test-connection")
async def test_connection(
    _admin: dict = Depends(verify_platform_admin),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Test that the current configured connections to PostgreSQL and Redis are healthy.
    """
    pg_ok = False
    pg_detail: Dict[str, Any] = {}
    try:
        result = await db.execute(text("SELECT 1 AS ping"))
        result.fetchone()
        result2 = await db.execute(text("SELECT current_database(), current_user, version()"))
        row = result2.fetchone()
        pg_ok = True
        pg_detail = {
            "database": row[0],
            "user":     row[1],
            "version":  row[2],
        }
    except Exception as exc:
        pg_detail = {"error": str(exc)}

    redis_ok = False
    redis_detail: Dict[str, Any] = {}
    try:
        pong = await redis.ping()
        redis_ok = pong is True or pong == b"PONG"
        info = await redis.info("server")
        redis_detail = {
            "version":        info.get("redis_version"),
            "uptime_seconds": info.get("uptime_in_seconds"),
        }
    except Exception as exc:
        redis_detail = {"error": str(exc)}

    return {
        "postgres": {"ok": pg_ok, **pg_detail},
        "redis":    {"ok": redis_ok, **redis_detail},
        "all_ok":   pg_ok and redis_ok,
    }


@router.get("/validate")
async def validate_database(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Run the database validation test suite:

    1. Table existence — every expected table is present.
    2. Column validation — required columns exist with the correct nullability.
    3. Alembic version — schema version matches the framework requirement.
    4. Catalog/seeded data — row-count checks for static reference tables.
    """
    results: List[Dict[str, Any]] = []
    overall_pass = True

    # ── Fetch live schema via SQLAlchemy async inspector ─────────────────────
    try:
        from sqlalchemy.ext.asyncio import AsyncConnection
        async with engine.connect() as conn:
            def _sync_inspect(sync_conn):
                insp = inspect(sync_conn)
                return {
                    t: {c["name"]: c for c in insp.get_columns(t)}
                    for t in insp.get_table_names()
                }
            live_schema = await conn.run_sync(_sync_inspect)
    except Exception as exc:
        return {
            "passed": False,
            "results": [{"check": "Schema Inspection", "passed": False, "detail": str(exc)}],
        }

    # ── 1. Table existence ────────────────────────────────────────────────────
    for table_name, expected_columns in EXPECTED_TABLES.items():
        exists = table_name in live_schema
        check = {
            "check":   f"Table: {table_name}",
            "passed":  exists,
            "detail":  "OK" if exists else f"Table '{table_name}' not found in database",
        }
        results.append(check)
        if not exists:
            overall_pass = False
            continue

        # ── 2. Column validation ──────────────────────────────────────────────
        live_cols = live_schema[table_name]
        for exp_col in expected_columns:
            col_name = exp_col["name"]
            present  = col_name in live_cols
            col_check = {
                "check":  f"  Column: {table_name}.{col_name}",
                "passed": present,
                "detail": "OK" if present else f"Column '{col_name}' missing from '{table_name}'",
            }
            if present:
                live_col  = live_cols[col_name]
                live_null = live_col.get("nullable", True)
                exp_null  = exp_col.get("nullable", True)
                if live_null != exp_null:
                    col_check["passed"] = False
                    col_check["detail"] = (
                        f"Nullability mismatch for {table_name}.{col_name}: "
                        f"expected nullable={exp_null}, got nullable={live_null}"
                    )
                    overall_pass = False
            else:
                overall_pass = False

            results.append(col_check)

    # ── 3. Alembic version check ──────────────────────────────────────────────
    current_revision = await _get_alembic_current(db)
    # Pass if at exact framework revision OR at a known plugin revision
    # (plugin migrations chain off REQUIRED_DB_REVISION, so its presence
    # implies the framework schema was applied first).
    framework_ok = (
        current_revision == REQUIRED_DB_REVISION
        or is_plugin_revision(current_revision)
    )
    plugin_suffix = " (+ plugin migrations)" if is_plugin_revision(current_revision) else ""
    results.append({
        "check":  "Alembic schema version",
        "passed": framework_ok,
        "detail": (
            f"OK — framework revision {REQUIRED_DB_REVISION}{plugin_suffix}"
            if framework_ok
            else f"Expected {REQUIRED_DB_REVISION}, got {current_revision}"
        ),
    })
    if not framework_ok:
        overall_pass = False

    # ── 4. Catalog / seeded row-count checks ─────────────────────────────────
    # These tables should never be empty after a fresh deployment
    non_empty_tables: List[str] = []  # Add table names here if you seed data
    # Example: non_empty_tables = ["llm_model_pricing"]
    for tbl in non_empty_tables:
        try:
            result = await db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            count  = result.scalar() or 0
            passed = count > 0
            results.append({
                "check":  f"Seeded data: {tbl}",
                "passed": passed,
                "detail": f"OK — {count} row(s)" if passed else f"Table '{tbl}' is empty (expected seeded rows)",
            })
            if not passed:
                overall_pass = False
        except Exception as exc:
            results.append({"check": f"Seeded data: {tbl}", "passed": False, "detail": str(exc)})
            overall_pass = False

    passed_count = sum(1 for r in results if r["passed"])
    return {
        "passed":       overall_pass,
        "total_checks": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "results":      results,
    }


@router.get("/migration-history")
async def get_migration_history(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
    limit: int = 50,
):
    """
    Return the audit trail of every migration run applied to this database.

    Each record shows:
    - from/to revision and app version
    - who triggered it (Discord user ID)
    - when it ran and how long it took (ms)
    - whether it succeeded or failed (with error output if not)

    Results are ordered newest-first.  Use ``limit`` (default 50) to cap output.
    """
    from sqlalchemy import select, desc
    result = await db.execute(
        select(DbMigrationHistory)
        .order_by(desc(DbMigrationHistory.applied_at))
        .limit(max(1, min(limit, 500)))
    )
    rows = result.scalars().all()
    return {
        "count":   len(rows),
        "history": [
            {
                "id":            r.id,
                "from_revision": r.from_revision,
                "to_revision":   r.to_revision,
                "from_version":  r.from_version,
                "to_version":    r.to_version,
                "applied_at":    r.applied_at.isoformat() if r.applied_at else None,
                "applied_by":    r.applied_by,
                "duration_ms":   r.duration_ms,
                "status":        r.status,
                "error":         r.error,
            }
            for r in rows
        ],
    }
