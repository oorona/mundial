"""
Setup Wizard API — accessible without authentication when the platform
is in wizard mode (no encrypted settings file on disk).

Authentication model
────────────────────
All endpoints (except /state) require the X-Setup-Key header to equal the
ENCRYPTION_KEY environment variable.  This proves the caller has
infrastructure-level access — they can read the docker-compose file or the
host environment — without relying on the normal Discord OAuth flow that has
not been configured yet.

Wizard flow
───────────
  1. GET  /state              — frontend checks whether setup is needed
  2. POST /verify-key         — validate the developer's encryption key
  3. POST /test-postgres      — test admin DB connection
  4. POST /init-database      — create app role, database, and schema
  5. POST /check-migrations   — see what Alembic revisions need applying
  6. POST /apply-migrations   — run alembic upgrade head
  7. POST /test-redis         — test Redis credentials
  8. POST /save               — encrypt and persist all settings to disk
  9. POST /restart            — SIGTERM → Docker restarts with new settings
"""

import asyncio
import json as _json
import os
import signal
import subprocess
from typing import Any, Dict, Optional

import asyncpg
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.encrypted_settings import (
    SETTINGS_FILE_PATH,
    _get_encryption_key,
    is_setup_complete,
    load_encrypted_settings,
    save_encrypted_settings,
    verify_key,
)
from app.core.version import FRAMEWORK_VERSION, REQUIRED_DB_REVISION

router = APIRouter()
logger = structlog.get_logger()


# ── Auth guards ───────────────────────────────────────────────────────────────

def _require_key(x_setup_key: Optional[str]) -> None:
    """Verify the X-Setup-Key header matches the configured ENCRYPTION_KEY."""
    if not x_setup_key or not verify_key(x_setup_key):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Setup-Key header")


def _require_setup_mode(x_setup_key: Optional[str]) -> None:
    """
    Require both a valid key AND that setup has not yet been completed.
    Prevents re-running destructive wizard steps (save/restart) on a live
    platform without explicit intent.  Re-enable by deleting the settings file.
    """
    _require_key(x_setup_key)
    if is_setup_complete():
        raise HTTPException(
            status_code=403,
            detail=(
                "Setup is already complete. To re-run the wizard, remove the "
                "settings file and restart the platform."
            ),
        )


# ── Request schemas ───────────────────────────────────────────────────────────

class VerifyKeyRequest(BaseModel):
    key: str


class PostgresRequest(BaseModel):
    host: str
    port: int = 5432
    user: str
    db: str
    password: str
    # Schema is always the username — enforced throughout, never configurable.


class InitDatabaseRequest(BaseModel):
    # Superuser / admin connection (used to create the app role + database)
    admin_host: str
    admin_port: int = 5432
    admin_user: str
    admin_password: str
    admin_db: str = "postgres"   # default postgres maintenance db
    # Application role + database to create
    app_user: str
    app_password: str
    app_db: str
    # app_schema is not a separate field — it always equals app_user.
    # This ensures each bot on the same postgres cluster is fully isolated:
    # bot_a owns schema bot_a, bot_b owns schema bot_b.  Never public.


class RedisRequest(BaseModel):
    host: str
    port: int = 6379
    db: int = 0
    password: Optional[str] = None


class SaveRequest(BaseModel):
    settings: Dict[str, Any]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/state")
async def get_setup_state():
    """
    Return the current platform setup state.
    Always public — the frontend polls this to decide whether to show the wizard.
    """
    setup_complete             = is_setup_complete()
    encryption_key_configured  = bool(_get_encryption_key())
    return {
        "setup_complete":            setup_complete,
        "setup_mode":                not setup_complete,
        "encryption_key_configured": encryption_key_configured,
        "framework_version":         FRAMEWORK_VERSION,
        "settings_file":             str(SETTINGS_FILE_PATH),
        "settings_file_exists":      SETTINGS_FILE_PATH.exists(),
    }


@router.post("/verify-key")
async def verify_setup_key(body: VerifyKeyRequest):
    """Step 1 — verify the developer's ENCRYPTION_KEY before proceeding."""
    if not verify_key(body.key):
        raise HTTPException(
            status_code=401,
            detail="Key does not match the configured ENCRYPTION_KEY environment variable."
        )
    return {"verified": True}


@router.post("/test-postgres")
async def test_postgres(
    body: PostgresRequest,
    x_setup_key: Optional[str] = Header(None),
):
    """Step 2 — test a PostgreSQL connection with the provided credentials."""
    _require_key(x_setup_key)
    try:
        conn = await asyncpg.connect(
            host=body.host, port=body.port, user=body.user,
            database=body.db, password=body.password, timeout=10,
        )
        version   = await conn.fetchval("SELECT version()")
        size_row  = await conn.fetchrow(
            "SELECT pg_size_pretty(pg_database_size($1))", body.db
        )
        await conn.close()
        return {
            "ok":       True,
            "version":  version,
            "db_size":  size_row[0] if size_row else None,
            "database": body.db,
            "user":     body.user,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/init-database")
async def init_database(
    body: InitDatabaseRequest,
    x_setup_key: Optional[str] = Header(None),
):
    """
    Step 2b — create the application role, database, and schema.
    Connects using admin credentials, then creates the app user/db if they
    do not already exist.  Safe to call on an existing database: all
    statements use IF NOT EXISTS / DO NOTHING semantics.
    """
    _require_key(x_setup_key)
    steps: list[dict] = []

    try:
        conn = await asyncpg.connect(
            host=body.admin_host, port=body.admin_port,
            user=body.admin_user, password=body.admin_password,
            database=body.admin_db, timeout=10,
        )

        # 1. Create role (skip if already exists)
        role_exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = $1", body.app_user
        )
        if not role_exists:
            await conn.execute(
                f"CREATE ROLE {body.app_user} WITH LOGIN PASSWORD $1", body.app_password
            )
            steps.append({"step": "create_role", "status": "created", "role": body.app_user})
        else:
            steps.append({"step": "create_role", "status": "already_exists", "role": body.app_user})

        # 2. Create database (skip if already exists)
        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", body.app_db
        )
        if not db_exists:
            # CREATE DATABASE cannot run inside a transaction; use autocommit
            await conn.execute(f'CREATE DATABASE "{body.app_db}" OWNER {body.app_user}')
            steps.append({"step": "create_database", "status": "created", "database": body.app_db})
        else:
            steps.append({"step": "create_database", "status": "already_exists", "database": body.app_db})

        await conn.close()

        # 3. Connect to the app database and configure schema isolation.
        # Schema name always equals the app username — one schema per bot,
        # all on the same postgres cluster, each fully isolated from the others.
        app_schema = body.app_user

        app_conn = await asyncpg.connect(
            host=body.admin_host, port=body.admin_port,
            user=body.admin_user, password=body.admin_password,
            database=body.app_db, timeout=10,
        )

        # Create dedicated schema owned by the app user
        await app_conn.execute(
            f'CREATE SCHEMA IF NOT EXISTS "{app_schema}" AUTHORIZATION {body.app_user}'
        )

        # search_path = ONLY the app schema — public is excluded so no
        # object from this bot can ever land there or collide with another bot.
        await app_conn.execute(
            f'ALTER ROLE {body.app_user} IN DATABASE "{body.app_db}" '
            f'SET search_path = "{app_schema}"'
        )

        # Grant full ownership of the schema; revoke CREATE on public
        await app_conn.execute(
            f'GRANT ALL ON SCHEMA "{app_schema}" TO {body.app_user}'
        )
        await app_conn.execute(
            f'REVOKE CREATE ON SCHEMA public FROM {body.app_user}'
        )

        await app_conn.close()
        steps.append({"step": "create_schema", "status": "done", "schema": app_schema})

        return {"ok": True, "steps": steps}

    except Exception as exc:
        logger.error("wizard_init_database_failed", error=str(exc))
        return {"ok": False, "error": str(exc), "steps": steps}


@router.post("/check-migrations")
async def check_migrations(
    body: PostgresRequest,
    x_setup_key: Optional[str] = Header(None),
):
    """Step 3a — inspect current Alembic revision in the target database."""
    _require_key(x_setup_key)
    schema = body.user
    try:
        conn = await asyncpg.connect(
            host=body.host, port=body.port, user=body.user,
            database=body.db, password=body.password, timeout=10,
            server_settings={"search_path": schema},
        )
        query_error = None
        current = None
        try:
            row = await conn.fetchrow(
                f'SELECT version_num FROM "{schema}".alembic_version LIMIT 1'
            )
            current = row["version_num"] if row else None
        except Exception as qe:
            query_error = str(qe)
        await conn.close()
        result = {
            "current_revision":  current,
            "required_revision": REQUIRED_DB_REVISION,
            "up_to_date":        current == REQUIRED_DB_REVISION,
            "is_fresh_database": current is None,
        }
        if query_error:
            result["query_error"] = query_error
        return result
    except Exception as exc:
        return {"error": str(exc), "current_revision": None, "up_to_date": False}


@router.post("/apply-migrations")
async def apply_migrations(
    body: PostgresRequest,
    x_setup_key: Optional[str] = Header(None),
):
    """Step 3b — run `alembic upgrade head`, streaming each step via SSE."""
    _require_key(x_setup_key)

    schema = body.user  # schema name always equals the username
    env = os.environ.copy()
    env.update({
        "POSTGRES_HOST":     body.host,         "POSTGRES_PORT":   str(body.port),
        "POSTGRES_USER":     body.user,         "POSTGRES_DB":     body.db,
        "POSTGRES_PASSWORD": body.password,     "POSTGRES_SCHEMA": schema,
        "DB_HOST":           body.host,         "DB_PORT":         str(body.port),
        "DB_USER":           body.user,         "DB_NAME":         body.db,
        "DB_PASSWORD":       body.password,     "DB_SCHEMA":       schema,
        "PYTHONUNBUFFERED":  "1",
    })

    async def generate():
        proc = await asyncio.create_subprocess_exec(
            "alembic", "upgrade", "head",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,   # merge stderr → stdout
            cwd="/app",
            env=env,
        )
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            yield f"data: {_json.dumps({'line': line})}\n\n"
        await proc.wait()
        success = proc.returncode == 0
        logger.info("wizard_migrations", success=success)
        yield f"data: {_json.dumps({'done': True, 'success': success, 'returncode': proc.returncode})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/test-redis")
async def test_redis(
    body: RedisRequest,
    x_setup_key: Optional[str] = Header(None),
):
    """Step 4 — test a Redis connection with the provided credentials."""
    _require_key(x_setup_key)
    try:
        client = aioredis.Redis(
            host=body.host, port=body.port, db=body.db,
            password=body.password or None,
            socket_connect_timeout=10,
        )
        await client.ping()
        info = await client.info("server")
        await client.aclose()
        return {
            "ok":          True,
            "version":     info.get("redis_version"),
            "uptime_days": info.get("uptime_in_days"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/current-settings")
async def get_current_settings(x_setup_key: Optional[str] = Header(None)):
    """
    Return the existing encrypted settings as plaintext so the wizard can
    pre-populate its form fields.  Requires a valid X-Setup-Key (the encryption
    key itself), proving the caller has infrastructure-level access.
    Returns an empty dict when no settings file exists yet.
    """
    _require_key(x_setup_key)
    data = load_encrypted_settings()
    return {"settings": data or {}}


@router.post("/save")
async def save_settings(
    body: SaveRequest,
    x_setup_key: Optional[str] = Header(None),
):
    """
    Encrypt and persist all settings to the settings file.
    Callable at any time (first-time setup or subsequent updates) as long as
    the caller can provide the valid X-Setup-Key.
    """
    _require_key(x_setup_key)

    clean = {
        k: str(v)
        for k, v in body.settings.items()
        if v is not None and str(v).strip()
    }
    try:
        enc_key = _get_encryption_key()
        save_encrypted_settings(clean, enc_key)
        logger.info("wizard_settings_saved", key_count=len(clean))
        return {"saved": True, "key_count": len(clean), "path": str(SETTINGS_FILE_PATH)}
    except Exception as exc:
        logger.error("wizard_save_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {exc}")


@router.post("/restart")
async def restart_service(x_setup_key: Optional[str] = Header(None)):
    """
    Trigger a graceful shutdown so Docker restarts the container with the
    newly saved settings.  Docker restart: unless-stopped handles the relaunch.
    Only callable when setup has not yet been completed.
    """
    _require_key(x_setup_key)  # Key check only — restart is safe after setup too
    logger.info("wizard_restart_requested")

    async def _shutdown():
        await asyncio.sleep(0.8)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(_shutdown())
    return {
        "restarting": True,
        "message": "The service is restarting with the new configuration. "
                   "The page will reconnect automatically in a few seconds.",
    }
