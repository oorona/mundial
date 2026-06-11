"""
Tests for backend/app/api/auth.py

Covers:
  - GET  /auth/discord/login       — OAuth URL construction
  - GET  /auth/discord/callback    — happy path, token exchange errors, state variants
  - GET  /auth/me                  — auth-gated user data
  - POST /auth/logout              — single-session logout
  - POST /auth/logout-all          — all-session logout + Redis revocation marker
  - GET  /auth/discord-config      — public config endpoint

Key production bugs targeted:
  - Token exchange exception with empty str(e) (e.g. ConnectionError()) must NOT crash
    or return a blank error — it must redirect to /login with error details (even if
    the details string is empty).
  - Outbound Discord call fails (non-200) → must redirect, not raise unhandled 500.
"""

import json
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse

from app.core.config import settings


# ── Rate-limiter bypass ────────────────────────────────────────────────────────
# slowapi tracks requests by IP; after 5 calls from 127.0.0.1 it raises
# RateLimitExceeded.  Patch _check_request_limit to a no-op so unit tests
# never hit the limit regardless of execution order.

@pytest.fixture(autouse=True)
def disable_rate_limit(monkeypatch):
    """
    Bypass slowapi without breaking its post-call header injection.
    _check_request_limit normally sets request.state.view_rate_limit as a
    side effect; the wrapper reads it after the endpoint returns.  Our no-op
    must also set that attribute so the wrapper doesn't raise AttributeError.
    """
    from app.core.limiter import limiter

    def _noop_check(request, *args, **kwargs):
        try:
            request.state.view_rate_limit = "999 per 1 minute"
        except Exception:
            pass

    monkeypatch.setattr(limiter, "_check_request_limit", _noop_check)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_httpx_mocks(
    token_status: int = 200,
    token_body: dict | None = None,
    user_status: int = 200,
    user_body: dict | None = None,
    post_side_effect=None,
):
    """
    Return a (mock_client_class, mock_client) pair that stubs httpx.AsyncClient
    as an async context manager.

    token_body / user_body default to valid Discord payloads when not supplied.
    post_side_effect, if set, is raised instead of returning a response.
    """
    if token_body is None:
        token_body = {
            "access_token": "discord_access_token",
            "refresh_token": "discord_refresh_token",
            "expires_in": 604800,
        }
    if user_body is None:
        user_body = {
            "id": "123456789",
            "username": "testuser",
            "discriminator": "0001",
            "avatar": None,
        }

    mock_token_res = MagicMock()
    mock_token_res.status_code = token_status
    mock_token_res.json.return_value = token_body
    mock_token_res.text = json.dumps(token_body)

    mock_user_res = MagicMock()
    mock_user_res.status_code = user_status
    mock_user_res.json.return_value = user_body

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    if post_side_effect is not None:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock_client.post = AsyncMock(return_value=mock_token_res)

    mock_client.get = AsyncMock(return_value=mock_user_res)

    mock_client_class = MagicMock(return_value=mock_client)

    return mock_client_class, mock_client


def _make_db():
    """AsyncSession stub with execute → scalar_one_or_none → None, add, commit."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result_mock)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def _make_redis():
    redis = AsyncMock()
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    return redis


def _make_response():
    """FastAPI Response stub with set_cookie / delete_cookie."""
    resp = MagicMock()
    resp.set_cookie = MagicMock()
    resp.delete_cookie = MagicMock()
    resp.headers = {}
    return resp


def _make_request(query_string: str = ""):
    """
    Real starlette.requests.Request built from a minimal ASGI scope.
    slowapi's rate limiter calls isinstance(request, starlette.requests.Request),
    so a MagicMock is rejected — we must supply the real class.
    """
    from starlette.requests import Request as StarletteRequest
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/auth/discord/login",
        "query_string": query_string.encode() if isinstance(query_string, str) else query_string,
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 8000),
        "scheme": "http",
    }
    return StarletteRequest(scope)


# ── TestDiscordLogin ───────────────────────────────────────────────────────────

class TestDiscordLogin:
    """GET /auth/discord/login"""

    @pytest.fixture(autouse=True)
    def patch_settings(self):
        """Ensure settings have Discord credentials for every test in this class."""
        with patch.object(settings, "DISCORD_CLIENT_ID", "test_client_id"), \
             patch.object(settings, "DISCORD_REDIRECT_URI", "http://localhost:8000/auth/discord/callback"):
            yield

    @pytest.mark.asyncio
    async def test_returns_redirect_response(self):
        from app.api.auth import login_discord
        result = await login_discord(request=_make_request())
        assert isinstance(result, RedirectResponse)

    @pytest.mark.asyncio
    async def test_redirect_url_points_to_discord(self):
        from app.api.auth import login_discord
        result = await login_discord(request=_make_request())
        location = result.headers["location"]
        assert "discord.com/oauth2/authorize" in location

    @pytest.mark.asyncio
    async def test_url_contains_required_oauth_params(self):
        from app.api.auth import login_discord
        result = await login_discord(request=_make_request())
        location = result.headers["location"]
        assert "client_id=test_client_id" in location
        assert "response_type=code" in location
        assert "scope=" in location
        assert "redirect_uri=" in location

    @pytest.mark.asyncio
    async def test_default_prompt_is_none(self):
        from app.api.auth import login_discord
        result = await login_discord(request=_make_request())
        location = result.headers["location"]
        assert "prompt=none" in location

    @pytest.mark.asyncio
    async def test_prompt_consent_passed_through(self):
        from app.api.auth import login_discord
        result = await login_discord(request=_make_request(), prompt="consent")
        location = result.headers["location"]
        assert "prompt=consent" in location

    @pytest.mark.asyncio
    async def test_missing_client_id_raises_500(self):
        from app.api.auth import login_discord
        with patch.object(settings, "DISCORD_CLIENT_ID", None):
            with pytest.raises(HTTPException) as exc:
                await login_discord(request=_make_request())
            assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_state_param_included_in_url(self):
        from app.api.auth import login_discord
        result = await login_discord(request=_make_request(), state="popup")
        location = result.headers["location"]
        assert "state=popup" in location


# ── TestDiscordCallback ────────────────────────────────────────────────────────

class TestDiscordCallback:
    """GET /auth/discord/callback — full flow variants."""

    @pytest.fixture(autouse=True)
    def patch_settings(self):
        with patch.object(settings, "DISCORD_CLIENT_ID", "test_client_id"), \
             patch.object(settings, "DISCORD_CLIENT_SECRET", "test_secret"), \
             patch.object(settings, "DISCORD_REDIRECT_URI", "http://localhost:8000/auth/discord/callback"), \
             patch.object(settings, "FRONTEND_URL", "http://localhost:3000"):
            yield

    # ── 6. Happy path — redirect state ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_happy_path_redirect_state(self):
        """code present + Discord APIs succeed → RedirectResponse to FRONTEND_URL with token."""
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks()

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="valid_code",
                state="redirect",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert isinstance(result, RedirectResponse)
        location = result.headers["location"]
        assert location.startswith("http://localhost:3000")
        assert "token=" in location

    # ── 7. error param (non-silent, non-interaction) ───────────────────────────

    @pytest.mark.asyncio
    async def test_error_param_redirects_to_access_denied(self):
        from app.api.auth import callback_discord

        result = await callback_discord(
            request=_make_request(),
            error="access_denied",
            state="redirect",
            response=_make_response(),
            db=_make_db(),
            redis=_make_redis(),
        )

        assert isinstance(result, RedirectResponse)
        location = result.headers["location"]
        assert "/access-denied" in location

    # ── 8. error="interaction_required" ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_interaction_required_redirects_to_discord_consent(self):
        from app.api.auth import callback_discord

        result = await callback_discord(
            request=_make_request(),
            error="interaction_required",
            state="redirect",
            response=_make_response(),
            db=_make_db(),
            redis=_make_redis(),
        )

        assert isinstance(result, RedirectResponse)
        location = result.headers["location"]
        assert "discord.com/oauth2/authorize" in location

    @pytest.mark.asyncio
    async def test_interaction_required_silent_state_returns_postmessage_html(self):
        from app.api.auth import callback_discord

        result = await callback_discord(
            request=_make_request(),
            error="interaction_required",
            state="silent",
            response=_make_response(),
            db=_make_db(),
            redis=_make_redis(),
        )

        assert isinstance(result, HTMLResponse)
        assert "DISCORD_SILENT_LOGIN_REQUIRED" in result.body.decode()

    # ── 9. No code and no error ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_code_no_error_raises_400(self):
        from app.api.auth import callback_discord

        with pytest.raises(HTTPException) as exc:
            await callback_discord(
                request=_make_request(),
                state="redirect",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_no_code_silent_state_returns_html_error(self):
        from app.api.auth import callback_discord

        result = await callback_discord(
            request=_make_request(),
            state="silent",
            response=_make_response(),
            db=_make_db(),
            redis=_make_redis(),
        )

        assert isinstance(result, HTMLResponse)
        body = result.body.decode()
        assert "DISCORD_SILENT_LOGIN_FAILED" in body

    # ── 12. state="silent" + generic error ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_error_param_silent_state_returns_postmessage_html(self):
        from app.api.auth import callback_discord

        result = await callback_discord(
            request=_make_request(),
            error="some_error",
            state="silent",
            response=_make_response(),
            db=_make_db(),
            redis=_make_redis(),
        )

        assert isinstance(result, HTMLResponse)
        body = result.body.decode()
        assert "DISCORD_SILENT_LOGIN_FAILED" in body
        assert "some_error" in body

    # ── 13. state="popup" → HTMLResponse with postMessage ─────────────────────

    @pytest.mark.asyncio
    async def test_popup_state_returns_html_with_postmessage(self):
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks()

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="valid_code",
                state="popup",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert isinstance(result, HTMLResponse)
        body = result.body.decode()
        assert "DISCORD_LOGIN_SUCCESS" in body
        assert "token" in body

    # ── 14. state="redirect" + success → redirect with token ──────────────────

    @pytest.mark.asyncio
    async def test_redirect_state_returns_redirect_with_token(self):
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks()

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="valid_code",
                state="redirect",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert isinstance(result, RedirectResponse)
        location = result.headers["location"]
        assert "token=" in location

    # ── 11. Discord token endpoint returns non-200 ─────────────────────────────

    @pytest.mark.asyncio
    async def test_non_200_token_response_redirects_to_login_with_error(self):
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks(
            token_status=400,
            token_body={"error": "invalid_grant"},
        )

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="bad_code",
                state="redirect",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert isinstance(result, RedirectResponse)
        location = result.headers["location"]
        assert "/login" in location
        assert "error=discord_error" in location

    @pytest.mark.asyncio
    async def test_non_200_token_response_silent_state_returns_html_error(self):
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks(token_status=401, token_body={"error": "unauthorized"})

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="bad_code",
                state="silent",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert isinstance(result, HTMLResponse)
        body = result.body.decode()
        assert "DISCORD_SILENT_LOGIN_FAILED" in body


# ── TestCallbackTokenExchangeError ────────────────────────────────────────────

class TestCallbackTokenExchangeError:
    """
    Critical production bugs:
      - httpx raises exception during token exchange
      - str(e) == "" (e.g. bare ConnectionError()) must not produce an empty/broken redirect
    """

    @pytest.fixture(autouse=True)
    def patch_settings(self):
        with patch.object(settings, "DISCORD_CLIENT_ID", "test_client_id"), \
             patch.object(settings, "DISCORD_CLIENT_SECRET", "test_secret"), \
             patch.object(settings, "DISCORD_REDIRECT_URI", "http://localhost:8000/auth/discord/callback"), \
             patch.object(settings, "FRONTEND_URL", "http://localhost:3000"):
            yield

    # ── 10/15. Exception with empty str(e) → still a redirect, not a crash ────

    @pytest.mark.asyncio
    async def test_connection_error_empty_message_does_not_crash(self):
        """
        ConnectionError() produces str(e) == "".
        The callback must still return a redirect (not raise, not 500).
        This is the exact production bug: the handler must survive an empty-string exception.
        """
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks(post_side_effect=ConnectionError())
        assert str(ConnectionError()) == "", "Precondition: ConnectionError() gives empty str"

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="some_code",
                state="redirect",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert isinstance(result, RedirectResponse)
        location = result.headers["location"]
        assert "/login" in location
        assert "error=internal_error" in location

    # ── 16. Error details present in redirect URL even when exception is empty ─

    @pytest.mark.asyncio
    async def test_redirect_contains_details_key_even_when_exception_message_is_empty(self):
        """
        The redirect URL must include a `details=` query parameter even when the
        exception message is an empty string.  An absent `details` key means the
        frontend has no way to distinguish error types.
        """
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks(post_side_effect=ConnectionError())

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="some_code",
                state="redirect",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        location = result.headers["location"]
        # The `details=` key must be present (value may be empty-encoded but the key must exist)
        assert "details=" in location

    @pytest.mark.asyncio
    async def test_runtime_error_with_message_included_in_redirect(self):
        """Exception with a non-empty message has its text URL-encoded into `details`."""
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks(post_side_effect=RuntimeError("network timeout"))

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="some_code",
                state="redirect",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert isinstance(result, RedirectResponse)
        location = result.headers["location"]
        assert "error=internal_error" in location
        # "network timeout" should appear URL-encoded or decoded in the location
        assert "network" in location or "network%20timeout" in location

    @pytest.mark.asyncio
    async def test_exception_silent_state_returns_html_not_crash(self):
        """Exception during token exchange with state=silent → HTMLResponse postMessage."""
        from app.api.auth import callback_discord

        mock_class, _ = _make_httpx_mocks(post_side_effect=ConnectionError())

        with patch("app.api.auth.httpx.AsyncClient", mock_class):
            result = await callback_discord(
                request=_make_request(),
                code="some_code",
                state="silent",
                response=_make_response(),
                db=_make_db(),
                redis=_make_redis(),
            )

        assert isinstance(result, HTMLResponse)
        body = result.body.decode()
        assert "DISCORD_SILENT_LOGIN_FAILED" in body


# ── TestMe ─────────────────────────────────────────────────────────────────────

class TestMe:
    """GET /auth/me"""

    @pytest.mark.asyncio
    async def test_returns_user_dict_with_admin_flag(self):
        from app.api.auth import read_users_me

        user_dict = {"user_id": "42", "username": "testuser"}

        with patch("app.api.auth.check_is_admin", new_callable=AsyncMock) as mock_admin:
            mock_admin.return_value = False
            result = await read_users_me(current_user=user_dict)

        assert result["user_id"] == "42"
        assert result["username"] == "testuser"
        assert result["is_admin"] is False

    @pytest.mark.asyncio
    async def test_admin_flag_true_for_admin_user(self):
        from app.api.auth import read_users_me

        user_dict = {"user_id": "1", "username": "admin"}

        with patch("app.api.auth.check_is_admin", new_callable=AsyncMock) as mock_admin:
            mock_admin.return_value = True
            result = await read_users_me(current_user=user_dict)

        assert result["is_admin"] is True

    @pytest.mark.asyncio
    async def test_check_is_admin_exception_defaults_to_false(self):
        """If check_is_admin raises, is_admin must default to False (not crash)."""
        from app.api.auth import read_users_me

        user_dict = {"user_id": "99", "username": "unknown"}

        with patch("app.api.auth.check_is_admin", new_callable=AsyncMock) as mock_admin:
            mock_admin.side_effect = Exception("DB unavailable")
            result = await read_users_me(current_user=user_dict)

        assert result["is_admin"] is False


# ── TestLogout ─────────────────────────────────────────────────────────────────

class TestLogout:
    """POST /auth/logout"""

    @pytest.mark.asyncio
    async def test_redis_session_deleted(self):
        """Valid Authorization header token → Redis session key is deleted."""
        from app.api.auth import logout

        redis = _make_redis()
        token = "my_api_token"

        await logout(
            response=_make_response(),
            current_user={"user_id": "42"},
            db=_make_db(),
            redis=redis,
            authorization=token,
        )

        redis.delete.assert_called_once_with(f"session:{token}")

    @pytest.mark.asyncio
    async def test_user_token_db_record_deleted(self):
        """Logout hashes the token and deletes the matching UserToken row."""
        from app.api.auth import logout

        db = _make_db()
        token = "my_api_token"
        expected_hash = hashlib.sha256(token.encode()).hexdigest()

        await logout(
            response=_make_response(),
            current_user={"user_id": "42"},
            db=db,
            redis=_make_redis(),
            authorization=token,
        )

        # db.execute must have been called with a delete statement
        db.execute.assert_called()
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_cookie_cleared_in_response(self):
        from app.api.auth import logout

        response = _make_response()

        await logout(
            response=response,
            current_user={"user_id": "42"},
            db=_make_db(),
            redis=_make_redis(),
            authorization="some_token",
        )

        response.delete_cookie.assert_called_once_with("session_id")

    @pytest.mark.asyncio
    async def test_no_token_still_returns_message(self):
        """No Authorization header — logout still succeeds and clears cookie."""
        from app.api.auth import logout

        response = _make_response()

        result = await logout(
            response=response,
            current_user={"user_id": "42"},
            db=_make_db(),
            redis=_make_redis(),
            authorization=None,
        )

        assert result == {"message": "Logged out"}
        response.delete_cookie.assert_called_once_with("session_id")

    @pytest.mark.asyncio
    async def test_returns_logged_out_message(self):
        from app.api.auth import logout

        result = await logout(
            response=_make_response(),
            current_user={"user_id": "42"},
            db=_make_db(),
            redis=_make_redis(),
            authorization="some_token",
        )

        assert result == {"message": "Logged out"}


# ── TestLogoutAll ──────────────────────────────────────────────────────────────

class TestLogoutAll:
    """POST /auth/logout-all"""

    @pytest.mark.asyncio
    async def test_all_db_tokens_deleted(self):
        """All UserToken rows for the user are removed from DB."""
        from app.api.auth import logout_all

        db = _make_db()

        await logout_all(
            current_user={"user_id": "42"},
            db=db,
            redis=_make_redis(),
        )

        db.execute.assert_called()
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_redis_revocation_marker_set(self):
        """Redis `user:revoked_at:{user_id}` key is set via setex."""
        from app.api.auth import logout_all

        redis = _make_redis()

        await logout_all(
            current_user={"user_id": "55"},
            db=_make_db(),
            redis=redis,
        )

        redis.setex.assert_called_once()
        key, ttl, value = redis.setex.call_args[0]
        assert key == "user:revoked_at:55"

    @pytest.mark.asyncio
    async def test_revocation_marker_has_30_day_ttl(self):
        """The revocation marker TTL is exactly 30 days (2_592_000 seconds)."""
        from app.api.auth import logout_all

        redis = _make_redis()

        await logout_all(
            current_user={"user_id": "55"},
            db=_make_db(),
            redis=redis,
        )

        _key, ttl, _value = redis.setex.call_args[0]
        assert ttl == 60 * 60 * 24 * 30

    @pytest.mark.asyncio
    async def test_revocation_marker_value_is_numeric_timestamp(self):
        """The revocation marker stores a numeric timestamp string."""
        from app.api.auth import logout_all

        redis = _make_redis()

        await logout_all(
            current_user={"user_id": "55"},
            db=_make_db(),
            redis=redis,
        )

        _key, _ttl, value = redis.setex.call_args[0]
        # Must be parseable as a float (Unix timestamp)
        assert float(value) > 0

    @pytest.mark.asyncio
    async def test_returns_logged_out_all_devices_message(self):
        from app.api.auth import logout_all

        result = await logout_all(
            current_user={"user_id": "42"},
            db=_make_db(),
            redis=_make_redis(),
        )

        assert result == {"message": "Logged out from all devices"}


# ── TestDiscordConfig ──────────────────────────────────────────────────────────

class TestDiscordConfig:
    """GET /auth/discord-config"""

    @pytest.mark.asyncio
    async def test_returns_client_id_and_redirect_uri(self):
        from app.api.auth import get_discord_config

        with patch.object(settings, "DISCORD_CLIENT_ID", "public_client_id"), \
             patch.object(settings, "DISCORD_REDIRECT_URI", "http://localhost:8000/callback"):
            result = await get_discord_config()

        assert result["client_id"] == "public_client_id"
        assert result["redirect_uri"] == "http://localhost:8000/callback"

    @pytest.mark.asyncio
    async def test_returns_none_when_unconfigured(self):
        """When not configured, values are None — endpoint still responds (no auth required)."""
        from app.api.auth import get_discord_config

        with patch.object(settings, "DISCORD_CLIENT_ID", None), \
             patch.object(settings, "DISCORD_REDIRECT_URI", None):
            result = await get_discord_config()

        assert result["client_id"] is None
        assert result["redirect_uri"] is None

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """Public endpoint — must return 200 without an Authorization header."""
        from main import app
        from app.core.config import settings as _settings

        response = await client.get(f"{_settings.API_V1_STR}/auth/discord-config")
        assert response.status_code == 200
