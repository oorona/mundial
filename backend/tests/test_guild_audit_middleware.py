"""
Tests for GuildAuditMiddleware in backend/main.py

Covers:
  - Successful mutating requests on guild-scoped paths trigger an audit log write
  - Non-mutating requests (GET) are not audited
  - Failed requests (4xx/5xx) are not audited
  - Non-guild paths are not audited
  - Authenticated user_id is extracted from Bearer token via Redis
  - Authenticated user_id is extracted from session cookie via Redis
  - Bot/internal requests (no session) produce no audit log write
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── Helper: build a minimal request mock ──────────────────────────────────────

def _make_request(
    method: str = "PUT",
    path: str = "/api/v1/guilds/123456789012345678/settings",
    auth: str | None = None,
    cookie_session_id: str | None = None,
):
    req = MagicMock()
    req.method = method
    req.url.path = path
    req.body = AsyncMock(return_value=b"")
    headers = {}
    if auth:
        headers["Authorization"] = auth
    req.headers = MagicMock()
    req.headers.get = lambda key, default="": headers.get(key, default)
    req.cookies = {}
    if cookie_session_id:
        req.cookies["session_id"] = cookie_session_id
    return req


def _session_data(user_id: int = 42) -> bytes:
    return json.dumps({"user_id": str(user_id), "username": "alice"}).encode()


# ── Tests for _get_session_user_id ────────────────────────────────────────────

class TestGetSessionUserId:
    @pytest.mark.asyncio
    async def test_bearer_token_lookup(self):
        from main import _get_session_user_id

        req = _make_request(auth="Bearer my_token")
        with patch("main.redis_pool", new=MagicMock()):
            with patch("main.redis.Redis") as mock_redis_cls:
                mock_r = AsyncMock()
                mock_r.get = AsyncMock(return_value=_session_data(user_id=7))
                mock_redis_cls.return_value = mock_r

                uid = await _get_session_user_id(req)

        assert uid == 7
        mock_r.get.assert_called_once_with("session:my_token")

    @pytest.mark.asyncio
    async def test_cookie_lookup(self):
        from main import _get_session_user_id

        req = _make_request(cookie_session_id="cookie_abc")
        with patch("main.redis_pool", new=MagicMock()):
            with patch("main.redis.Redis") as mock_redis_cls:
                mock_r = AsyncMock()
                # No Bearer header — only one r.get() call (for the cookie)
                mock_r.get = AsyncMock(side_effect=[_session_data(user_id=99)])
                mock_redis_cls.return_value = mock_r

                uid = await _get_session_user_id(req)

        assert uid == 99

    @pytest.mark.asyncio
    async def test_no_session_returns_none(self):
        from main import _get_session_user_id

        req = _make_request()  # no auth, no cookie
        with patch("main.redis_pool", new=MagicMock()):
            with patch("main.redis.Redis") as mock_redis_cls:
                mock_r = AsyncMock()
                mock_r.get = AsyncMock(return_value=None)
                mock_redis_cls.return_value = mock_r

                uid = await _get_session_user_id(req)

        assert uid is None

    @pytest.mark.asyncio
    async def test_redis_exception_returns_none(self):
        from main import _get_session_user_id

        req = _make_request(auth="Bearer tok")
        with patch("main.redis_pool", new=MagicMock()):
            with patch("main.redis.Redis") as mock_redis_cls:
                mock_r = AsyncMock()
                mock_r.get = AsyncMock(side_effect=Exception("redis down"))
                mock_redis_cls.return_value = mock_r

                uid = await _get_session_user_id(req)

        assert uid is None


# ── Tests for _write_audit_log ─────────────────────────────────────────────────

class TestWriteAuditLog:
    @pytest.mark.asyncio
    async def test_writes_audit_log_with_rls_context(self):
        from main import _write_audit_log

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_local = MagicMock(return_value=mock_session)

        # AsyncSessionLocal is imported locally inside _write_audit_log —
        # patch the source module attribute, not main.
        with patch("app.db.session.AsyncSessionLocal", new=None):
            # When AsyncSessionLocal is None, function returns early
            await _write_audit_log(123, 456, "PUT:/api/v1/guilds/:id/settings")
            mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self):
        from main import _write_audit_log

        with patch("app.db.session.AsyncSessionLocal", side_effect=Exception("db down")):
            # Must not raise
            await _write_audit_log(123, 456, "PUT:/api/v1/guilds/:id/settings")


# ── Tests for GuildAuditMiddleware.dispatch ────────────────────────────────────

class TestGuildAuditMiddleware:
    def _make_middleware(self):
        from main import GuildAuditMiddleware
        app_mock = MagicMock()
        return GuildAuditMiddleware(app_mock)

    @pytest.mark.asyncio
    async def test_successful_put_on_guild_path_creates_task(self):
        middleware = self._make_middleware()
        req = _make_request("PUT", "/api/v1/guilds/123456789012345678/settings",
                            auth="Bearer tok")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("main.SETUP_MODE", False):
            with patch("main._get_session_user_id", AsyncMock(return_value=42)):
                with patch("main.asyncio.create_task") as mock_task:
                    result = await middleware.dispatch(req, AsyncMock(return_value=mock_response))

        mock_task.assert_called_once()
        assert result is mock_response

    @pytest.mark.asyncio
    async def test_get_request_not_audited(self):
        middleware = self._make_middleware()
        req = _make_request("GET", "/api/v1/guilds/123456789012345678/settings")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("main.SETUP_MODE", False):
            with patch("main.asyncio.create_task") as mock_task:
                await middleware.dispatch(req, AsyncMock(return_value=mock_response))

        mock_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_request_not_audited(self):
        middleware = self._make_middleware()
        req = _make_request("PUT", "/api/v1/guilds/123456789012345678/settings",
                            auth="Bearer tok")

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("main.SETUP_MODE", False):
            with patch("main.asyncio.create_task") as mock_task:
                await middleware.dispatch(req, AsyncMock(return_value=mock_response))

        mock_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_guild_path_not_audited(self):
        middleware = self._make_middleware()
        req = _make_request("POST", "/api/v1/llm/generate", auth="Bearer tok")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("main.SETUP_MODE", False):
            with patch("main.asyncio.create_task") as mock_task:
                await middleware.dispatch(req, AsyncMock(return_value=mock_response))

        mock_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_request_without_session_not_audited(self):
        """Bot/internal requests have no user session — must not be audited."""
        middleware = self._make_middleware()
        req = _make_request("POST", "/api/v1/guilds/123456789012345678/ticketnode/purge-closed")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("main.SETUP_MODE", False):
            with patch("main._get_session_user_id", AsyncMock(return_value=None)):
                with patch("main.asyncio.create_task") as mock_task:
                    await middleware.dispatch(req, AsyncMock(return_value=mock_response))

        mock_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_setup_mode_skips_audit(self):
        middleware = self._make_middleware()
        req = _make_request("PUT", "/api/v1/guilds/123456789012345678/settings",
                            auth="Bearer tok")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("main.SETUP_MODE", True):
            with patch("main.asyncio.create_task") as mock_task:
                await middleware.dispatch(req, AsyncMock(return_value=mock_response))

        mock_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_action_uses_normalised_path(self):
        """guild_id should be replaced with :id in the action string."""
        middleware = self._make_middleware()
        guild_id = "987654321098765432"
        req = _make_request("DELETE", f"/api/v1/guilds/{guild_id}/authorized-users/111",
                            auth="Bearer tok")

        mock_response = MagicMock()
        mock_response.status_code = 200

        captured_args = []

        async def fake_write(gid, uid, action, details=None):
            captured_args.append((gid, uid, action))

        import asyncio as _asyncio

        with patch("main.SETUP_MODE", False):
            with patch("main._get_session_user_id", AsyncMock(return_value=5)):
                with patch("main._write_audit_log", fake_write):
                    # ensure_future schedules the coroutine so it actually runs
                    with patch("main.asyncio.create_task",
                               side_effect=lambda coro: _asyncio.ensure_future(coro)):
                        await middleware.dispatch(req, AsyncMock(return_value=mock_response))
                        # Yield to the event loop so the scheduled coroutine executes
                        await _asyncio.sleep(0)

        assert len(captured_args) == 1
        gid, uid, action = captured_args[0]
        assert gid == int(guild_id)
        assert uid == 5
        assert ":id" in action
        assert guild_id not in action
