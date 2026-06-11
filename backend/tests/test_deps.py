"""
Tests for backend/app/api/deps.py

Covers:
  - get_current_user — Bearer token (Redis hit), Bot auth (valid/invalid),
                       DB fallback, expired session, revoked session,
                       unauthenticated request
  - check_is_admin   — owner match, role match, no dev guild, exception swallowed
  - verify_platform_admin — system user passes, non-admin raises 403
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


# ── get_current_user ──────────────────────────────────────────────────────────

class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_bearer_token_redis_hit(self):
        from app.api.deps import get_current_user

        redis = AsyncMock()
        session_data = {"user_id": "42", "username": "alice", "token_created_at": 9999999999.0}
        redis.get.side_effect = [
            json.dumps(session_data),  # session lookup
            None,                      # revoked_at lookup
        ]
        db = AsyncMock()

        result = await get_current_user(
            cookie_session_id=None,
            authorization="Bearer my_token",
            redis=redis,
            db=db,
        )

        assert result["user_id"] == "42"
        assert result["username"] == "alice"

    @pytest.mark.asyncio
    async def test_bot_token_valid(self):
        from app.api.deps import get_current_user

        redis = AsyncMock()
        db = AsyncMock()

        with patch("app.core.config.settings") as mock_cfg:
            mock_cfg.DISCORD_BOT_TOKEN = "secret_bot_token"
            result = await get_current_user(
                cookie_session_id=None,
                authorization="Bot secret_bot_token",
                redis=redis,
                db=db,
            )

        assert result["system"] is True
        assert result["permission_level"] == "admin"

    @pytest.mark.asyncio
    async def test_bot_token_invalid_falls_through_to_401(self):
        from app.api.deps import get_current_user

        redis = AsyncMock()
        redis.get.return_value = None
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

        with patch("app.core.config.settings") as mock_cfg:
            mock_cfg.DISCORD_BOT_TOKEN = "secret_bot_token"
            with pytest.raises(HTTPException) as exc:
                await get_current_user(
                    cookie_session_id=None,
                    authorization="Bot wrong_token",
                    redis=redis,
                    db=db,
                )

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_credentials_raises_401(self):
        from app.api.deps import get_current_user

        redis = AsyncMock()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                cookie_session_id=None,
                authorization=None,
                redis=redis,
                db=db,
            )

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_session_not_in_redis_or_db_raises_401(self):
        from app.api.deps import get_current_user

        redis = AsyncMock()
        redis.get.return_value = None
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                cookie_session_id=None,
                authorization="Bearer nonexistent",
                redis=redis,
                db=db,
            )

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_revoked_session_raises_401(self):
        from app.api.deps import get_current_user

        redis = AsyncMock()
        session_data = {"user_id": "42", "username": "alice", "token_created_at": 1000.0}
        redis.get.side_effect = [
            json.dumps(session_data),  # session lookup
            "2000.0",                  # revoked_at — newer than token_created_at
        ]
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                cookie_session_id=None,
                authorization="Bearer my_token",
                redis=redis,
                db=db,
            )

        assert exc.value.status_code == 401
        assert "revoked" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_cookie_only_no_header_raises_401(self):
        """
        cookie_session_id is declared as a FastAPI Cookie dependency but is
        never assigned to session_id in the current implementation — only
        Bearer/Bot Authorization headers are supported.  A request with only
        a session cookie and no Authorization header must therefore return 401.
        """
        from app.api.deps import get_current_user

        redis = AsyncMock()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                cookie_session_id="cookie_token",
                authorization=None,
                redis=redis,
                db=db,
            )

        assert exc.value.status_code == 401


# ── check_is_admin ────────────────────────────────────────────────────────────

class TestCheckIsAdmin:
    @pytest.mark.asyncio
    async def test_no_dev_guild_returns_false(self):
        from app.api.deps import check_is_admin

        with patch("app.core.config.settings") as mock_cfg:
            mock_cfg.DISCORD_GUILD_ID = None
            result = await check_is_admin("42")

        assert result is False

    @pytest.mark.asyncio
    async def test_guild_owner_is_admin(self):
        from app.api.deps import check_is_admin

        with patch("app.core.config.settings") as mock_cfg, \
             patch("app.core.discord.discord_client") as mock_discord:
            mock_cfg.DISCORD_GUILD_ID = "dev_guild"
            mock_cfg.DEVELOPER_ROLE_ID = None
            mock_discord.get_guild = AsyncMock(return_value={"owner_id": "42"})
            result = await check_is_admin("42")

        assert result is True

    @pytest.mark.asyncio
    async def test_developer_role_grants_admin(self):
        from app.api.deps import check_is_admin

        with patch("app.core.config.settings") as mock_cfg, \
             patch("app.core.discord.discord_client") as mock_discord:
            mock_cfg.DISCORD_GUILD_ID = "dev_guild"
            mock_cfg.DEVELOPER_ROLE_ID = "dev_role"
            mock_discord.get_guild = AsyncMock(return_value={"owner_id": "999"})
            mock_discord.get_guild_member = AsyncMock(return_value={"roles": ["dev_role"]})
            result = await check_is_admin("42")

        assert result is True

    @pytest.mark.asyncio
    async def test_non_member_returns_false(self):
        from app.api.deps import check_is_admin

        with patch("app.core.config.settings") as mock_cfg, \
             patch("app.core.discord.discord_client") as mock_discord:
            mock_cfg.DISCORD_GUILD_ID = "dev_guild"
            mock_cfg.DEVELOPER_ROLE_ID = "dev_role"
            mock_discord.get_guild = AsyncMock(return_value={"owner_id": "999"})
            mock_discord.get_guild_member = AsyncMock(return_value={"roles": []})
            result = await check_is_admin("42")

        assert result is False

    @pytest.mark.asyncio
    async def test_discord_exception_returns_false(self):
        from app.api.deps import check_is_admin

        with patch("app.core.config.settings") as mock_cfg, \
             patch("app.core.discord.discord_client") as mock_discord:
            mock_cfg.DISCORD_GUILD_ID = "dev_guild"
            mock_discord.get_guild = AsyncMock(side_effect=Exception("network error"))
            result = await check_is_admin("42")

        assert result is False


# ── verify_platform_admin ─────────────────────────────────────────────────────

class TestVerifyPlatformAdmin:
    @pytest.mark.asyncio
    async def test_system_user_passes(self):
        from app.api.deps import verify_platform_admin

        user = {"user_id": "0", "permission_level": "admin"}
        result = await verify_platform_admin(current_user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self):
        from app.api.deps import verify_platform_admin

        with patch("app.api.deps.check_is_admin", return_value=False):
            with pytest.raises(HTTPException) as exc:
                await verify_platform_admin(current_user={"user_id": "42"})

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_user_passes(self):
        from app.api.deps import verify_platform_admin

        user = {"user_id": "42"}
        with patch("app.api.deps.check_is_admin", return_value=True):
            result = await verify_platform_admin(current_user=user)

        assert result == user
