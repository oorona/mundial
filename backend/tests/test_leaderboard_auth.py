"""Unit tests for the leaderboard view-auth gate (_require_guild_viewer).

The leaderboard data endpoints must not be readable by an anonymous, guild-id-
enumerable caller. The gate accepts EITHER a guild-scoped Activity session OR a
logged-in dashboard member with access to the guild. These exercise the branch
logic directly with the framework auth deps mocked (no DB / Redis needed for the
Activity-session and admin fast paths).
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

import app.api.leaderboard as lb


async def _call(guild_id=10, authorization="Bearer tok", cookie=None, db=None):
    return await lb._require_guild_viewer(
        guild_id=guild_id, cookie_session_id=cookie,
        authorization=authorization, redis=AsyncMock(), db=db or AsyncMock(),
    )


class TestActivitySession:
    async def test_matching_guild_passes(self):
        with patch.object(lb, "get_activity_user",
                          AsyncMock(return_value={"user_id": "1", "guild_id": "10"})):
            # returns None (gate passes, no exception)
            assert await _call(guild_id=10) is None

    async def test_wrong_guild_rejected(self):
        with patch.object(lb, "get_activity_user",
                          AsyncMock(return_value={"user_id": "1", "guild_id": "999"})):
            with pytest.raises(HTTPException) as ei:
                await _call(guild_id=10)
            assert ei.value.status_code == 403

    async def test_no_activity_falls_through_to_dashboard(self):
        # activity lookup fails (401) → must try the dashboard session path
        with patch.object(lb, "get_activity_user",
                          AsyncMock(side_effect=HTTPException(status_code=401, detail="x"))), \
             patch.object(lb, "get_current_user",
                          AsyncMock(return_value={"user_id": "5", "system": True})):
            assert await _call() is None


class TestDashboardSession:
    async def test_admin_passes(self):
        with patch.object(lb, "get_activity_user", AsyncMock(side_effect=HTTPException(401, "x"))), \
             patch.object(lb, "get_current_user", AsyncMock(return_value={"user_id": "5"})), \
             patch.object(lb, "check_is_admin", AsyncMock(return_value=True)):
            assert await _call() is None

    async def test_unauthenticated_is_rejected(self):
        # neither an activity session nor a dashboard session → 401 from get_current_user
        with patch.object(lb, "get_activity_user", AsyncMock(side_effect=HTTPException(401, "x"))), \
             patch.object(lb, "get_current_user", AsyncMock(side_effect=HTTPException(401, "no auth"))):
            with pytest.raises(HTTPException) as ei:
                await _call(authorization=None)
            assert ei.value.status_code == 401
