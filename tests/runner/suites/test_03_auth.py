"""
Suite 03 — Authentication
Tests the auth flow and session management endpoints.
Note: Full OAuth flow requires Discord interaction, so we test:
  - Endpoints that reject unauthenticated requests
  - Discord config endpoint (public)
  - Token-based auth (if TEST_API_TOKEN is provided)
  - Logout endpoints
  - Bot token authentication
"""
import time
import httpx
import pytest
import os

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
TEST_API_TOKEN = os.environ.get("TEST_API_TOKEN", "")
SUITE = "03 Authentication"


def _get(path: str, headers: dict = None, base: str = None):
    url = (base or GATEWAY_URL) + path
    start = time.monotonic()
    r = httpx.get(url, timeout=10, follow_redirects=False, headers=headers or {})
    return r, (time.monotonic() - start) * 1000


def _post(path: str, headers: dict = None, base: str = None, json: dict = None):
    url = (base or GATEWAY_URL) + path
    start = time.monotonic()
    r = httpx.post(url, timeout=10, follow_redirects=False,
                   headers=headers or {}, json=json)
    return r, (time.monotonic() - start) * 1000


class TestUnauthenticatedRejection:
    """All protected endpoints must return 401 without a token."""

    def test_me_requires_auth(self):
        r, _ = _get("/api/v1/auth/me")
        assert r.status_code == 401, (
            f"GET /auth/me should return 401 without auth, got {r.status_code}"
        )

    def test_guilds_requires_auth(self):
        r, _ = _get("/api/v1/guilds")
        assert r.status_code == 401, (
            f"GET /guilds should return 401 without auth, got {r.status_code}"
        )

    def test_logout_requires_auth(self):
        r, _ = _post("/api/v1/auth/logout")
        assert r.status_code == 401, (
            f"POST /auth/logout should return 401 without auth, got {r.status_code}"
        )

    def test_logout_all_requires_auth(self):
        r, _ = _post("/api/v1/auth/logout-all")
        assert r.status_code == 401, (
            f"POST /auth/logout-all should return 401 without auth, got {r.status_code}"
        )

    def test_platform_settings_requires_auth(self):
        r, _ = _get("/api/v1/platform/settings")
        assert r.status_code == 401, (
            f"GET /platform/settings should require auth, got {r.status_code}"
        )

    def test_shards_requires_auth(self):
        r, _ = _get("/api/v1/shards")
        assert r.status_code == 401, (
            f"GET /shards should require auth, got {r.status_code}"
        )


class TestPublicEndpoints:
    """Public endpoints must work without authentication."""

    def test_discord_config_is_public(self):
        r, _ = _get("/api/v1/auth/discord-config")
        assert r.status_code == 200, (
            f"GET /auth/discord-config should be public, got {r.status_code}"
        )

    def test_discord_config_returns_client_id(self):
        r, _ = _get("/api/v1/auth/discord-config")
        data = r.json()
        assert "client_id" in data, f"Missing client_id in discord-config: {data}"

    def test_discord_config_no_secrets(self):
        """Config endpoint must never return the client secret."""
        r, _ = _get("/api/v1/auth/discord-config")
        body = r.text.lower()
        assert "secret" not in body or "client_secret" not in body, (
            "Discord client_secret leaked in /auth/discord-config response"
        )

    def test_login_redirect(self):
        """Login endpoint should redirect to Discord.
        Tested against the backend directly to avoid nginx auth rate limiting.
        """
        r, _ = _get("/api/v1/auth/discord/login", base=BACKEND_URL)
        assert r.status_code in (302, 307), (
            f"Login should redirect (302/307), got {r.status_code}"
        )
        location = r.headers.get("location", "")
        assert "discord.com" in location, (
            f"Login redirect should go to discord.com, got: {location}"
        )


class TestInvalidTokenRejection:
    """Invalid/garbage tokens must be rejected."""

    def test_garbage_bearer_token_rejected(self):
        # Hit backend directly — rapid test execution exhausts nginx auth rate
        # limit (3r/s burst=5) returning 503 before the backend sees the request.
        r, _ = _get("/api/v1/auth/me",
                    headers={"Authorization": "Bearer not-a-real-token"},
                    base=BACKEND_URL)
        assert r.status_code == 401, (
            f"Garbage bearer token should return 401, got {r.status_code}"
        )

    def test_wrong_scheme_rejected(self):
        r, _ = _get("/api/v1/auth/me",
                    headers={"Authorization": "Basic dXNlcjpwYXNz"},
                    base=BACKEND_URL)
        assert r.status_code == 401, (
            f"Basic auth scheme should return 401, got {r.status_code}"
        )


@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestAuthenticatedEndpoints:
    """Tests requiring a valid API token (set TEST_API_TOKEN env var)."""

    def test_me_returns_user(self):
        # Hit backend directly to avoid nginx auth rate limiting (3r/s burst=5).
        r, _ = _get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
                    base=BACKEND_URL)
        assert r.status_code == 200, f"GET /auth/me failed: {r.status_code} {r.text}"
        data = r.json()
        assert "user_id" in data, f"Missing user_id in /auth/me response: {data}"

    def test_me_response_shape(self):
        """Backwards compat: /auth/me response must include required fields."""
        r, _ = _get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
                    base=BACKEND_URL)
        data = r.json()
        required = ["user_id", "username"]
        for field in required:
            assert field in data, f"Missing required field '{field}' in /auth/me: {data}"

    def test_authenticated_guilds_accessible(self):
        r, _ = _get("/api/v1/guilds",
                    headers={"Authorization": f"Bearer {TEST_API_TOKEN}"})
        assert r.status_code == 200, (
            f"GET /guilds with valid token failed: {r.status_code} {r.text}"
        )
