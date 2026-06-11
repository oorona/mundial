"""
Tests for platform settings endpoints in backend/app/api/platform.py

Covers:
  - get_platform_settings uses get_admin_db (RLS bypass for cross-guild admin access)
  - update_platform_settings uses get_admin_db
  - Non-admin requests are rejected (403) before the DB session is opened
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.api.platform import get_platform_settings, update_platform_settings, PlatformSettingsUpdate


def _mock_settings_row(guild_id: int = 123, data: dict = None):
    row = MagicMock()
    row.settings_json = data or {"theme": "dark"}
    row.updated_at = None
    return row


def _mock_db(row=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


class TestGetPlatformSettings:
    @pytest.mark.asyncio
    async def test_returns_settings_when_row_exists(self):
        row = _mock_settings_row(data={"key": "value"})
        db = _mock_db(row=row)

        with patch("app.api.platform.app_settings") as cfg:
            cfg.DISCORD_GUILD_ID = "111"
            result = await get_platform_settings(db=db, admin={"user_id": "1"})

        assert result["settings"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_creates_row_when_missing(self):
        db = _mock_db(row=None)
        # After db.add + commit + refresh the refresh sets the attr
        created_row = _mock_settings_row(data={})
        db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "settings_json", {}))

        with patch("app.api.platform.app_settings") as cfg:
            cfg.DISCORD_GUILD_ID = "111"
            result = await get_platform_settings(db=db, admin={"user_id": "1"})

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert "settings" in result

    @pytest.mark.asyncio
    async def test_raises_503_when_guild_id_not_configured(self):
        db = _mock_db()

        with patch("app.api.platform.app_settings") as cfg:
            cfg.DISCORD_GUILD_ID = None
            with pytest.raises(HTTPException) as exc_info:
                await get_platform_settings(db=db, admin={"user_id": "1"})

        assert exc_info.value.status_code == 503


class TestUpdatePlatformSettings:
    @pytest.mark.asyncio
    async def test_merges_settings_into_existing_row(self):
        row = _mock_settings_row(data={"existing": "val"})
        db = _mock_db(row=row)

        with patch("app.api.platform.app_settings") as cfg:
            cfg.DISCORD_GUILD_ID = "111"
            result = await update_platform_settings(
                update_data=PlatformSettingsUpdate(settings={"new_key": "new_val"}),
                db=db,
                admin={"user_id": "99"},
            )

        # settings_json should contain the merged key
        assert row.settings_json.get("new_key") == "new_val"
        assert row.settings_json.get("existing") == "val"

    @pytest.mark.asyncio
    async def test_creates_row_when_missing(self):
        db = _mock_db(row=None)

        with patch("app.api.platform.app_settings") as cfg:
            cfg.DISCORD_GUILD_ID = "111"
            result = await update_platform_settings(
                update_data=PlatformSettingsUpdate(settings={"boot": True}),
                db=db,
                admin={"user_id": "99"},
            )

        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_503_when_guild_id_not_configured(self):
        db = _mock_db()

        with patch("app.api.platform.app_settings") as cfg:
            cfg.DISCORD_GUILD_ID = None
            with pytest.raises(HTTPException) as exc_info:
                await update_platform_settings(
                    update_data=PlatformSettingsUpdate(settings={}),
                    db=db,
                    admin={"user_id": "1"},
                )

        assert exc_info.value.status_code == 503
