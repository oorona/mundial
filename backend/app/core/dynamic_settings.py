"""Runtime accessor for dynamic (DB-overridable) settings.

Settings edited on the System Config page are persisted to the ``app_config``
table (and cached in Redis under ``config:dynamic:``), but until now nothing read
them at request time — so e.g. ``LLM_DEFAULT_PROVIDER`` had no effect.

``get_dynamic_setting`` resolves a setting's *effective* value the same way the
config UI displays it (see ``_build_setting_response`` in ``app/api/config.py``):

    DB override (app_config) → environment variable → SettingDef default → caller fallback

Empty strings are treated as "unset" so a blank override falls through to the
next source.
"""
import os
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_definitions import APP_SETTINGS_BY_KEY
from app.models import AppConfig


async def get_dynamic_setting(db: AsyncSession, key: str, default: Any = None) -> Optional[str]:
    """Return the effective value of a dynamic setting, or ``default``."""
    # 1. DB override — what the System Config page writes.
    row = (
        await db.execute(select(AppConfig).where(AppConfig.key == key))
    ).scalar_one_or_none()
    if row is not None and row.value not in (None, ""):
        return row.value

    # 2. Environment variable.
    env_val = os.environ.get(key)
    if env_val not in (None, ""):
        return env_val

    # 3. SettingDef default.
    defn = APP_SETTINGS_BY_KEY.get(key)
    if defn is not None and defn.default not in (None, ""):
        return defn.default

    # 4. Caller fallback.
    return default
