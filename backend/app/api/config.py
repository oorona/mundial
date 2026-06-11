"""
Config API — Level 5 (Platform Admin only)

Endpoints:
  GET  /api/v1/config/settings          — list all settings with metadata + current values
  GET  /api/v1/config/settings/{key}    — single setting detail
  PUT  /api/v1/config/settings          — bulk-update dynamic settings
  POST /api/v1/config/settings/refresh  — push dynamic overrides to Redis so they take
                                          effect without a restart
  DELETE /api/v1/config/settings/{key}  — remove a DB override (revert to env-var default)
  GET  /api/v1/config/api-keys          — read LLM provider API key status from encrypted file
  PUT  /api/v1/config/api-keys          — update LLM provider API keys in encrypted file
"""

import os
import json
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_platform_admin
from app.core.encrypted_settings import (
    load_encrypted_settings,
    save_encrypted_settings,
    verify_key,
)
from app.core.settings_definitions import (
    APP_SETTINGS,
    DATABASE_SETTINGS,
    APP_SETTINGS_BY_KEY,
    DB_SETTINGS_BY_KEY,
    DYNAMIC_KEYS,
    SETTING_CATEGORIES,
    DATABASE_CATEGORIES,
)
from app.db.redis import get_redis
from app.db.session import get_db
from app.models import AppConfig

router = APIRouter()
logger = structlog.get_logger()

REDIS_CONFIG_PREFIX = "config:dynamic:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask(value: Optional[str]) -> Optional[str]:
    """Mask a secret value for display."""
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


def _current_env(key: str, is_secret: bool) -> Optional[str]:
    """Read the current env-var value, masking secrets."""
    raw = os.environ.get(key)
    if raw is None:
        return None
    return _mask(raw) if is_secret else raw


async def _get_db_overrides(db: AsyncSession) -> Dict[str, str]:
    """Return all rows from app_config as key→value dict."""
    result = await db.execute(select(AppConfig))
    return {row.key: row.value for row in result.scalars().all()}


def _build_setting_response(defn, db_overrides: Dict[str, str]) -> dict:
    """Merge definition + env + db override into a single response object."""
    env_value = os.environ.get(defn.key)
    db_value  = db_overrides.get(defn.key)
    effective = db_value if db_value is not None else env_value

    d = defn.to_dict()
    d["env_value"]       = _mask(env_value) if defn.is_secret else env_value
    d["db_override"]     = _mask(db_value)  if defn.is_secret else db_value
    d["effective_value"] = _mask(effective) if defn.is_secret else effective
    d["source"]          = "database" if db_value is not None else ("environment" if env_value is not None else "default")
    return d


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SettingUpdate(BaseModel):
    key: str
    value: str


class BulkSettingsUpdate(BaseModel):
    settings: List[SettingUpdate]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/settings")
async def list_settings(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Return all configurable application settings with metadata and current values.
    Settings are grouped by category.
    """
    db_overrides = await _get_db_overrides(db)
    categories: Dict[str, List[dict]] = {}

    for defn in APP_SETTINGS:
        cat = defn.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(_build_setting_response(defn, db_overrides))

    return {
        "categories": SETTING_CATEGORIES,
        "settings":   categories,
    }


@router.get("/settings/database")
async def list_database_settings(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Return database connection settings (PostgreSQL + Redis) with metadata.
    These are always static — they require a server restart to take effect.
    """
    db_overrides = await _get_db_overrides(db)
    categories: Dict[str, List[dict]] = {}

    for defn in DATABASE_SETTINGS:
        cat = defn.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(_build_setting_response(defn, db_overrides))

    return {
        "categories": DATABASE_CATEGORIES,
        "settings":   categories,
    }


@router.get("/settings/{key}")
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """Get metadata and current value for a single setting key."""
    defn = APP_SETTINGS_BY_KEY.get(key) or DB_SETTINGS_BY_KEY.get(key)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown setting key: {key}")

    db_overrides = await _get_db_overrides(db)
    return _build_setting_response(defn, db_overrides)


@router.put("/settings")
async def update_settings(
    body: BulkSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    admin: dict = Depends(verify_platform_admin),
):
    """
    Update one or more settings.

    - Dynamic settings: stored in app_config table AND pushed to Redis immediately.
    - Static settings: stored in app_config table only; a restart is required.
    """
    updated: List[str] = []
    static_keys: List[str] = []

    for item in body.settings:
        defn = APP_SETTINGS_BY_KEY.get(item.key) or DB_SETTINGS_BY_KEY.get(item.key)
        if not defn:
            raise HTTPException(status_code=400, detail=f"Unknown setting key: {item.key}")

        # Upsert into app_config
        result = await db.execute(select(AppConfig).where(AppConfig.key == item.key))
        row = result.scalar_one_or_none()
        if row:
            row.value      = item.value
            row.updated_by = int(admin["user_id"])
        else:
            row = AppConfig(key=item.key, value=item.value, updated_by=int(admin["user_id"]))
            db.add(row)

        if defn.is_dynamic:
            # Push to Redis immediately so the running process picks it up
            await redis.set(f"{REDIS_CONFIG_PREFIX}{item.key}", item.value)
            updated.append(item.key)
        else:
            static_keys.append(item.key)

    await db.commit()

    logger.info(
        "config_updated",
        updated_dynamic=updated,
        updated_static=static_keys,
        admin_id=admin["user_id"],
    )

    return {
        "updated_dynamic": updated,
        "updated_static":  static_keys,
        "restart_required": len(static_keys) > 0,
        "message": (
            "Dynamic settings applied immediately. "
            + (f"Static settings ({', '.join(static_keys)}) require a server restart."
               if static_keys else "")
        ).strip(),
    }


@router.post("/settings/refresh")
async def refresh_dynamic_settings(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Re-publish all dynamic settings stored in the database to Redis.

    Use this if Redis was restarted or if a new backend instance needs to
    pick up overrides that were saved while it was down.
    """
    db_overrides = await _get_db_overrides(db)
    pushed = []

    for key, value in db_overrides.items():
        defn = APP_SETTINGS_BY_KEY.get(key)
        if defn and defn.is_dynamic:
            await redis.set(f"{REDIS_CONFIG_PREFIX}{key}", value)
            pushed.append(key)

    logger.info("config_refreshed", pushed=pushed)
    return {"refreshed": pushed, "count": len(pushed)}


@router.delete("/settings/{key}")
async def delete_setting_override(
    key: str,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    admin: dict = Depends(verify_platform_admin),
):
    """
    Remove a database override for a setting key, reverting to the env-var default.
    """
    defn = APP_SETTINGS_BY_KEY.get(key) or DB_SETTINGS_BY_KEY.get(key)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown setting key: {key}")

    result = await db.execute(select(AppConfig).where(AppConfig.key == key))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"No database override found for key: {key}")

    await db.delete(row)
    await db.commit()

    if defn.is_dynamic:
        await redis.delete(f"{REDIS_CONFIG_PREFIX}{key}")

    logger.info("config_override_deleted", key=key, admin_id=admin["user_id"])
    return {"deleted": key, "reverted_to": "environment_default"}


# ---------------------------------------------------------------------------
# API Keys (stored in encrypted settings file)
# ---------------------------------------------------------------------------

# The LLM provider API keys managed via the encrypted settings file.
# These cannot be stored in the database as they are needed at boot time.
_API_KEY_DEFS: Dict[str, dict] = {
    "OPENAI_API_KEY": {
        "friendly_name": "OpenAI API Key",
        "description": "API key for OpenAI services (GPT models, DALL-E, Whisper). Required when using OpenAI as the LLM provider.",
    },
    "ANTHROPIC_API_KEY": {
        "friendly_name": "Anthropic API Key",
        "description": "API key for Anthropic Claude models. Required when using Anthropic as the LLM provider.",
    },
    "GOOGLE_API_KEY": {
        "friendly_name": "Google API Key",
        "description": "API key for Google Gemini and related AI services. Required when using Google as the LLM provider.",
    },
    "XAI_API_KEY": {
        "friendly_name": "xAI API Key",
        "description": "API key for xAI Grok models. Required when using xAI as the LLM provider.",
    },
}


class ApiKeysUpdate(BaseModel):
    settings: Dict[str, str]


@router.get("/api-keys")
async def get_api_keys(
    _admin: dict = Depends(verify_platform_admin),
):
    """
    Return the status of each LLM provider API key.
    Values are masked — only whether each key is set is exposed, plus a masked preview.
    Keys are read from the encrypted settings file and the running environment.
    """
    encrypted = load_encrypted_settings() or {}
    result = {}
    for key, meta in _API_KEY_DEFS.items():
        value = encrypted.get(key) or os.environ.get(key)
        result[key] = {
            **meta,
            "is_set": bool(value),
            "masked_value": _mask(value) if value else None,
        }
    return result


@router.put("/api-keys")
async def update_api_keys(
    body: ApiKeysUpdate,
    admin: dict = Depends(verify_platform_admin),
    x_setup_key: Optional[str] = Header(None),
):
    """
    Update one or more LLM provider API keys in the encrypted settings file.

    The caller must supply the X-Setup-Key header containing the encryption key.
    The server verifies it matches but uses only the caller-supplied value to
    re-encrypt — the server's own copy of the key is never used for this write.
    This ensures that compromising the platform-admin session alone is not
    sufficient to modify the encrypted settings file.

    Pass an empty string for a key to clear it; omit a key to leave it unchanged.
    A server restart is recommended after updating.
    """
    if not x_setup_key or not verify_key(x_setup_key):
        raise HTTPException(
            status_code=401,
            detail="X-Setup-Key header is required and must match the configured encryption key.",
        )

    unknown = [k for k in body.settings if k not in _API_KEY_DEFS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown API key(s): {', '.join(unknown)}")

    current = load_encrypted_settings() or {}
    merged = {**current}

    updated: List[str] = []
    cleared: List[str] = []
    for key, value in body.settings.items():
        stripped = value.strip()
        if stripped:
            merged[key] = stripped
            os.environ[key] = stripped
            updated.append(key)
        elif key in merged:
            del merged[key]
            os.environ.pop(key, None)
            cleared.append(key)

    # Use the caller-supplied key — the server's key is not accessed here.
    save_encrypted_settings(merged, x_setup_key)
    logger.info("api_keys_updated", updated=updated, cleared=cleared, admin_id=admin["user_id"])

    return {
        "updated": updated,
        "cleared": cleared,
        "restart_recommended": True,
        "message": (
            "API keys saved to encrypted settings. "
            "A server restart is recommended so all services pick up the new keys."
        ),
    }
