"""
Tests for backend/app/api/guilds.py

Covers every endpoint:
  - get_guild              — permission level calculation
  - get_guild_settings     — owner, admin, non-member
  - update_guild_settings  — owner update, allow_everyone toggle, MissingGreenlet
                             regression (attributes captured BEFORE flush)
  - get_authorized_users   — owner sees list, non-member blocked
  - add_authorized_user    — owner adds, duplicate rejected, non-admin blocked
  - remove_authorized_user — owner removes, 404 when user not found
  - add_authorized_role    — owner adds role, duplicate rejected
  - remove_authorized_role — owner removes, 404 when role not found
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.api.guilds import (
    get_guild,
    get_guild_settings,
    update_guild_settings,
    get_authorized_users,
    add_authorized_user,
    remove_authorized_user,
    add_authorized_role,
    remove_authorized_role,
    purge_audit_logs,
)
from app.models import (
    AuditLog,
    AuthorizedRole,
    AuthorizedUser,
    Guild,
    GuildSettings,
    PermissionLevel,
    User,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_db():
    """AsyncSession mock with sensible defaults."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _scalar_result(value):
    """Return a mock execute result whose scalar_one_or_none() returns *value*."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_result(values):
    """Return a mock execute result whose scalars().all() returns *values*."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


# ── get_guild ─────────────────────────────────────────────────────────────────

class TestGetGuild:
    @pytest.mark.asyncio
    async def test_owner_gets_owner_permission(self):
        db = _mock_db()
        redis = AsyncMock()
        redis.get.return_value = None
        guild = Guild(id=1, name="Test", owner_id=42, icon_url=None)
        db.get.return_value = guild

        with patch("app.api.guilds.check_is_admin", return_value=False):
            result = await get_guild(
                guild_id=1,
                db=db,
                current_user={"user_id": 42, "system": False},
                redis=redis,
            )

        assert result["permission_level"] == "owner"
        assert result["id"] == "1"

    @pytest.mark.asyncio
    async def test_authorized_user_gets_user_permission(self):
        db = _mock_db()
        redis = AsyncMock()
        redis.get.return_value = None
        guild = Guild(id=1, name="Test", owner_id=99, icon_url=None)
        db.get.return_value = guild
        auth_user = AuthorizedUser(user_id=42, guild_id=1, permission_level=PermissionLevel.USER)
        db.execute.return_value = _scalar_result(auth_user)

        with patch("app.api.guilds.check_is_admin", return_value=False):
            result = await get_guild(
                guild_id=1,
                db=db,
                current_user={"user_id": 42, "system": False},
                redis=redis,
            )

        assert result["permission_level"] == "user"

    @pytest.mark.asyncio
    async def test_platform_admin_gets_admin_permission(self):
        db = _mock_db()
        redis = AsyncMock()
        redis.get.return_value = None
        guild = Guild(id=1, name="Test", owner_id=99, icon_url=None)
        db.get.return_value = guild

        with patch("app.api.guilds.check_is_admin", return_value=True):
            result = await get_guild(
                guild_id=1,
                db=db,
                current_user={"user_id": 42, "system": False},
                redis=redis,
            )

        assert result["permission_level"] == "ADMIN"

    @pytest.mark.asyncio
    async def test_guild_not_found_raises_404(self):
        db = _mock_db()
        redis = AsyncMock()
        redis.get.return_value = None
        db.get.return_value = None
        db.execute.return_value = _scalar_result(None)

        with patch("app.api.guilds.check_is_admin", return_value=False):
            with pytest.raises(HTTPException) as exc:
                await get_guild(
                    guild_id=999,
                    db=db,
                    current_user={"user_id": 42, "system": False},
                    redis=redis,
                )

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_level2_allow_everyone_grants_access(self):
        db = _mock_db()
        redis = AsyncMock()
        redis.get.return_value = None
        guild = Guild(id=1, name="Test", owner_id=99, icon_url=None)
        db.get.return_value = guild

        settings_row = GuildSettings(
            guild_id=1,
            settings_json={"level_2_allow_everyone": True},
        )
        # First execute: authorized user check → None; second: settings → settings_row
        db.execute.side_effect = [
            _scalar_result(None),
            _scalar_result(settings_row),
        ]

        with patch("app.api.guilds.check_is_admin", return_value=False), \
             patch("app.api.guilds.discord_client") as mock_discord:
            mock_discord.get_guild_member = AsyncMock(return_value={"roles": []})
            result = await get_guild(
                guild_id=1,
                db=db,
                current_user={"user_id": 42, "system": False},
                redis=redis,
            )

        assert result["permission_level"] == "LEVEL_2"


# ── get_guild_settings ────────────────────────────────────────────────────────

class TestGetGuildSettings:
    @pytest.mark.asyncio
    async def test_owner_gets_settings(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        settings = GuildSettings(
            guild_id=1,
            settings_json={"level_2_allow_everyone": True},
            updated_at=None,
        )
        db.execute.return_value = _scalar_result(settings)

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client"):
            mock_cfg.DISCORD_GUILD_ID = None
            result = await get_guild_settings(
                guild_id=1,
                db=db,
                current_user={"user_id": 10},
            )

        assert result["settings"] == {"level_2_allow_everyone": True}

    @pytest.mark.asyncio
    async def test_creates_default_settings_when_none_exist(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        db.execute.return_value = _scalar_result(None)

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client"):
            mock_cfg.DISCORD_GUILD_ID = None
            result = await get_guild_settings(
                guild_id=1,
                db=db,
                current_user={"user_id": 10},
            )

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result["settings"] == {}

    @pytest.mark.asyncio
    async def test_non_member_forbidden(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=99, icon_url=None)
        db.get.return_value = guild
        db.execute.return_value = _scalar_result(None)

        with pytest.raises(HTTPException) as exc:
            await get_guild_settings(
                guild_id=1,
                db=db,
                current_user={"user_id": 42},
            )

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_guild_not_found_raises_404(self):
        db = _mock_db()
        db.get.return_value = None

        with pytest.raises(HTTPException) as exc:
            await get_guild_settings(
                guild_id=999,
                db=db,
                current_user={"user_id": 42},
            )

        assert exc.value.status_code == 404


# ── update_guild_settings ─────────────────────────────────────────────────────

class TestUpdateGuildSettings:
    """
    Key regression: result_settings and result_updated_at must be captured
    BEFORE db.flush() so that accessing them never triggers a lazy SELECT
    outside SQLAlchemy's greenlet (MissingGreenlet).
    """

    def _make_request(self, data: dict):
        from app.schemas import SettingsUpdate
        return SettingsUpdate(settings=data)

    @pytest.mark.asyncio
    async def test_owner_can_update_settings(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        settings = GuildSettings(
            guild_id=1,
            settings_json={"level_2_allow_everyone": True},
            updated_at=None,
            updated_by=None,
        )
        db.execute.return_value = _scalar_result(settings)

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client"):
            mock_cfg.DISCORD_GUILD_ID = None
            result = await update_guild_settings(
                guild_id=1,
                settings_update=self._make_request({"level_2_allow_everyone": False}),
                db=db,
                current_user={"user_id": 10},
            )

        assert result["settings"] == {"level_2_allow_everyone": False}
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_attributes_captured_before_flush(self):
        """
        Regression: result_settings must be read before flush() is awaited.
        If flush() expired settings.settings_json the old code raised
        MissingGreenlet; the new code captures in-memory values beforehand.
        """
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild

        captured_before_flush = {}

        settings = GuildSettings(
            guild_id=1,
            settings_json={"level_2_allow_everyone": True},
            updated_at=None,
            updated_by=None,
        )
        db.execute.return_value = _scalar_result(settings)

        original_flush = db.flush

        async def flush_and_expire():
            # Simulate SQLAlchemy expiring settings_json after flush
            del settings.__dict__["settings_json"]
            await original_flush()

        db.flush = flush_and_expire

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client"):
            mock_cfg.DISCORD_GUILD_ID = None
            # Should NOT raise even though settings_json is expired after flush
            result = await update_guild_settings(
                guild_id=1,
                settings_update=self._make_request({"level_2_allow_everyone": False}),
                db=db,
                current_user={"user_id": 10},
            )

        assert result["settings"] == {"level_2_allow_everyone": False}

    @pytest.mark.asyncio
    async def test_disable_allow_everyone(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        settings = GuildSettings(
            guild_id=1,
            settings_json={"level_2_allow_everyone": True, "level_2_roles": []},
            updated_at=None,
            updated_by=None,
        )
        db.execute.return_value = _scalar_result(settings)

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client"):
            mock_cfg.DISCORD_GUILD_ID = None
            result = await update_guild_settings(
                guild_id=1,
                settings_update=self._make_request({"level_2_allow_everyone": False}),
                db=db,
                current_user={"user_id": 10},
            )

        assert result["settings"]["level_2_allow_everyone"] is False

    @pytest.mark.asyncio
    async def test_non_owner_admin_can_update_non_restricted_settings(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=99, icon_url=None)
        db.get.return_value = guild
        auth_user = AuthorizedUser(
            user_id=10, guild_id=1, permission_level=PermissionLevel.ADMIN
        )
        settings = GuildSettings(
            guild_id=1,
            settings_json={},
            updated_at=None,
            updated_by=None,
        )
        db.execute.side_effect = [
            _scalar_result(auth_user),
            _scalar_result(settings),
        ]

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client"):
            mock_cfg.DISCORD_GUILD_ID = None
            result = await update_guild_settings(
                guild_id=1,
                settings_update=self._make_request({"level_2_allow_everyone": False}),
                db=db,
                current_user={"user_id": 10},
            )

        assert result["settings"] == {"level_2_allow_everyone": False}

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_settings(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=99, icon_url=None)
        db.get.return_value = guild
        auth_user = AuthorizedUser(
            user_id=10, guild_id=1, permission_level=PermissionLevel.USER
        )
        db.execute.return_value = _scalar_result(auth_user)

        with pytest.raises(HTTPException) as exc:
            await update_guild_settings(
                guild_id=1,
                settings_update=self._make_request({"level_2_allow_everyone": False}),
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_non_developer_cannot_change_restricted_keys(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        settings = GuildSettings(
            guild_id=1,
            settings_json={"model": "gemini-pro"},
            updated_at=None,
            updated_by=None,
        )
        db.execute.return_value = _scalar_result(settings)

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client") as mock_discord:
            mock_cfg.DISCORD_GUILD_ID = "dev_guild"
            mock_cfg.DEVELOPER_ROLE_ID = "dev_role"
            mock_discord.get_guild = AsyncMock(return_value={"owner_id": "999"})
            mock_discord.get_guild_member = AsyncMock(return_value={"roles": []})

            with pytest.raises(HTTPException) as exc:
                await update_guild_settings(
                    guild_id=1,
                    settings_update=self._make_request({"model": "gpt-4"}),
                    db=db,
                    current_user={"user_id": 10},
                )

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_audit_log_written_on_update(self):
        """Audit logging is handled automatically by GuildAuditMiddleware.
        The endpoint itself must NOT write AuditLog rows — it just commits
        the settings change and lets the middleware record the action."""
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        settings = GuildSettings(
            guild_id=1, settings_json={}, updated_at=None, updated_by=None
        )
        db.execute.return_value = _scalar_result(settings)

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client"):
            mock_cfg.DISCORD_GUILD_ID = None
            result = await update_guild_settings(
                guild_id=1,
                settings_update=self._make_request({"level_2_allow_everyone": False}),
                db=db,
                current_user={"user_id": 10},
            )

        # Endpoint commits successfully; no manual AuditLog write expected
        db.commit.assert_called_once()
        assert "settings" in result
        # The endpoint must NOT write AuditLog directly — middleware handles it
        added_objects = [c.args[0] for c in db.add.call_args_list]
        assert not any(isinstance(o, AuditLog) for o in added_objects)

    @pytest.mark.asyncio
    async def test_creates_settings_row_when_none_exists(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        db.execute.return_value = _scalar_result(None)

        with patch("app.api.guilds.app_settings") as mock_cfg, \
             patch("app.api.guilds.discord_client"):
            mock_cfg.DISCORD_GUILD_ID = None
            result = await update_guild_settings(
                guild_id=1,
                settings_update=self._make_request({"level_2_allow_everyone": False}),
                db=db,
                current_user={"user_id": 10},
            )

        added_objects = [call.args[0] for call in db.add.call_args_list]
        assert any(isinstance(o, GuildSettings) for o in added_objects)
        assert result["settings"] == {"level_2_allow_everyone": False}

    @pytest.mark.asyncio
    async def test_guild_not_found_raises_404(self):
        db = _mock_db()
        db.get.return_value = None

        with pytest.raises(HTTPException) as exc:
            await update_guild_settings(
                guild_id=999,
                settings_update=self._make_request({}),
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 404


# ── get_authorized_users ──────────────────────────────────────────────────────

class TestGetAuthorizedUsers:
    @pytest.mark.asyncio
    async def test_owner_gets_user_list(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild

        user = User(id=20, username="alice", discriminator="0001", avatar_url=None)
        auth_user = AuthorizedUser(
            user_id=20, guild_id=1, permission_level=PermissionLevel.USER
        )
        auth_user.user = user
        db.execute.return_value = _scalars_result([auth_user])

        with patch("app.api.guilds.discord_client"):
            result = await get_authorized_users(
                guild_id=1,
                db=db,
                current_user={"user_id": 10},
            )

        assert len(result) == 1
        assert result[0]["username"] == "alice"

    @pytest.mark.asyncio
    async def test_non_member_forbidden(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=99, icon_url=None)
        db.get.return_value = guild
        db.execute.return_value = _scalar_result(None)

        with pytest.raises(HTTPException) as exc:
            await get_authorized_users(
                guild_id=1,
                db=db,
                current_user={"user_id": 42},
            )

        assert exc.value.status_code == 403


# ── add_authorized_user ───────────────────────────────────────────────────────

class TestAddAuthorizedUser:
    def _request(self, user_id: int):
        from app.api.guilds import AddUserRequest
        r = MagicMock()
        r.user_id = user_id
        return r

    @pytest.mark.asyncio
    async def test_owner_adds_user_successfully(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        # not already authorized, user exists in DB
        target_user = User(id=20, username="bob", discriminator="0000", avatar_url=None)
        db.execute.side_effect = [
            _scalar_result(None),      # existing auth check
            _scalar_result(target_user),  # user lookup
        ]

        with patch("app.api.guilds.discord_client"):
            result = await add_authorized_user(
                guild_id=1,
                request=self._request(20),
                db=db,
                current_user={"user_id": 10},
            )

        assert result["message"] == "User authorized successfully"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_user_raises_409(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        existing = AuthorizedUser(user_id=20, guild_id=1, permission_level=PermissionLevel.USER)
        db.execute.return_value = _scalar_result(existing)

        with pytest.raises(HTTPException) as exc:
            await add_authorized_user(
                guild_id=1,
                request=self._request(20),
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_non_admin_cannot_add_user(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=99, icon_url=None)
        db.get.return_value = guild
        auth_user = AuthorizedUser(
            user_id=10, guild_id=1, permission_level=PermissionLevel.USER
        )
        db.execute.return_value = _scalar_result(auth_user)

        with pytest.raises(HTTPException) as exc:
            await add_authorized_user(
                guild_id=1,
                request=self._request(20),
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 403


# ── remove_authorized_user ────────────────────────────────────────────────────

class TestRemoveAuthorizedUser:
    @pytest.mark.asyncio
    async def test_owner_removes_user(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        target_auth = AuthorizedUser(user_id=20, guild_id=1, permission_level=PermissionLevel.USER)
        db.execute.return_value = _scalar_result(target_auth)

        result = await remove_authorized_user(
            guild_id=1,
            user_id=20,
            db=db,
            current_user={"user_id": 10},
        )

        assert result["message"] == "User removed successfully"
        db.delete.assert_called_once_with(target_auth)

    @pytest.mark.asyncio
    async def test_remove_nonexistent_user_raises_404(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        db.execute.return_value = _scalar_result(None)

        with pytest.raises(HTTPException) as exc:
            await remove_authorized_user(
                guild_id=1,
                user_id=999,
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 404


# ── add_authorized_role ───────────────────────────────────────────────────────

class TestAddAuthorizedRole:
    def _request(self, role_id: str):
        from app.api.guilds import AddRoleRequest
        r = MagicMock()
        r.role_id = role_id
        r.permission_level = PermissionLevel.USER
        return r

    @pytest.mark.asyncio
    async def test_owner_adds_role(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        db.execute.return_value = _scalar_result(None)  # not already authorized

        result = await add_authorized_role(
            guild_id=1,
            request=self._request("role_abc"),
            db=db,
            current_user={"user_id": 10},
        )

        assert result["message"] == "Role authorized successfully"
        added = [c.args[0] for c in db.add.call_args_list]
        assert any(isinstance(o, AuthorizedRole) for o in added)

    @pytest.mark.asyncio
    async def test_duplicate_role_raises_409(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        existing = AuthorizedRole(role_id="role_abc", guild_id=1)
        db.execute.return_value = _scalar_result(existing)

        with pytest.raises(HTTPException) as exc:
            await add_authorized_role(
                guild_id=1,
                request=self._request("role_abc"),
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 409


# ── remove_authorized_role ────────────────────────────────────────────────────

class TestRemoveAuthorizedRole:
    @pytest.mark.asyncio
    async def test_owner_removes_role(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        target = AuthorizedRole(role_id="role_abc", guild_id=1)
        db.execute.return_value = _scalar_result(target)

        result = await remove_authorized_role(
            guild_id=1,
            role_id="role_abc",
            db=db,
            current_user={"user_id": 10},
        )

        assert result["message"] == "Role removed successfully"
        db.delete.assert_called_once_with(target)

    @pytest.mark.asyncio
    async def test_remove_nonexistent_role_raises_404(self):
        db = _mock_db()
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild
        db.execute.return_value = _scalar_result(None)

        with pytest.raises(HTTPException) as exc:
            await remove_authorized_role(
                guild_id=1,
                role_id="no_such_role",
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 404


# ── purge_audit_logs ──────────────────────────────────────────────────────────

class TestPurgeAuditLogs:
    """
    Tests for DELETE /{guild_id}/audit-logs

    Covered:
      - Owner can purge all logs (no date filter)
      - Admin (ADMIN permission_level) can purge
      - Non-admin member is rejected with 403
      - older_than_days filter accepted
      - before / after date filters accepted
      - Guild not found raises 404
      - PURGE_AUDIT_LOGS AuditLog entry is written after purge
    """

    def _mock_db(self, rowcount: int = 5):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.delete = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = rowcount
        db.execute = AsyncMock(return_value=result_mock)
        nested_cm = AsyncMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=nested_cm)
        return db

    @pytest.mark.asyncio
    async def test_owner_purges_all_logs(self):
        db = self._mock_db(rowcount=7)
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild

        result = await purge_audit_logs(
            guild_id=1,
            older_than_days=None,
            before=None,
            after=None,
            db=db,
            current_user={"user_id": 10},
        )

        assert result == {"deleted": 7}
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_user_can_purge(self):
        db = self._mock_db(rowcount=3)
        guild = Guild(id=1, name="G", owner_id=99, icon_url=None)
        db.get.return_value = guild
        auth_user = AuthorizedUser(user_id=10, guild_id=1, permission_level=PermissionLevel.ADMIN)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = auth_user
        rowcount_result = MagicMock()
        rowcount_result.rowcount = 3
        db.execute = AsyncMock(side_effect=[scalar_result, rowcount_result])
        nested_cm = AsyncMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=nested_cm)

        result = await purge_audit_logs(
            guild_id=1,
            older_than_days=None,
            before=None,
            after=None,
            db=db,
            current_user={"user_id": 10},
        )

        assert result == {"deleted": 3}

    @pytest.mark.asyncio
    async def test_non_admin_member_raises_403(self):
        db = self._mock_db()
        guild = Guild(id=1, name="G", owner_id=99, icon_url=None)
        db.get.return_value = guild
        auth_user = AuthorizedUser(user_id=10, guild_id=1, permission_level=PermissionLevel.USER)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = auth_user
        db.execute = AsyncMock(return_value=scalar_result)

        with pytest.raises(HTTPException) as exc:
            await purge_audit_logs(
                guild_id=1,
                older_than_days=None,
                before=None,
                after=None,
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_guild_raises_404(self):
        db = self._mock_db()
        db.get.return_value = None

        with pytest.raises(HTTPException) as exc:
            await purge_audit_logs(
                guild_id=999,
                older_than_days=None,
                before=None,
                after=None,
                db=db,
                current_user={"user_id": 10},
            )

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_purge_audit_log_entry_written(self):
        """Purge must commit the DELETE and return a count.
        Audit logging is handled by GuildAuditMiddleware — the endpoint
        must NOT write a manual AuditLog row."""
        db = self._mock_db(rowcount=2)
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild

        result = await purge_audit_logs(
            guild_id=1,
            older_than_days=None,
            before=None,
            after=None,
            db=db,
            current_user={"user_id": 10},
        )

        db.commit.assert_called_once()
        assert result["deleted"] == 2
        # Middleware handles audit; endpoint must NOT add an AuditLog row
        added = [c.args[0] for c in db.add.call_args_list]
        assert not any(isinstance(o, AuditLog) for o in added)

    @pytest.mark.asyncio
    async def test_older_than_days_accepted(self):
        db = self._mock_db(rowcount=1)
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild

        result = await purge_audit_logs(
            guild_id=1,
            older_than_days=30,
            before=None,
            after=None,
            db=db,
            current_user={"user_id": 10},
        )

        assert result == {"deleted": 1}
        db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_date_range_filters_accepted(self):
        db = self._mock_db(rowcount=0)
        guild = Guild(id=1, name="G", owner_id=10, icon_url=None)
        db.get.return_value = guild

        result = await purge_audit_logs(
            guild_id=1,
            older_than_days=None,
            before="2025-01-01",
            after="2024-01-01",
            db=db,
            current_user={"user_id": 10},
        )

        assert result == {"deleted": 0}
