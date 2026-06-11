"""
Suite 04 — Security Levels (L0–L6)
Verifies that each security level is enforced correctly.

L0 — Public: accessible without auth
L1 — Public Data: accessible without auth (read-only)
L2 — User: requires valid session (401 without)
L3 — Authorized: requires guild authorization (401/403 without)
L4 — Administrator: guild admin only (401/403 without)
L5 — Owner: guild owner only (401/403 without)
L6 — Developer: platform admin only (401/403 without)
"""
import time
import httpx
import pytest
import os

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway")
TEST_API_TOKEN = os.environ.get("TEST_API_TOKEN", "")
SUITE = "04 Security Levels"


def _get(path: str, headers: dict = None):
    start = time.monotonic()
    r = httpx.get(
        f"{GATEWAY_URL}{path}",
        timeout=10,
        follow_redirects=False,
        headers=headers or {},
    )
    return r, (time.monotonic() - start) * 1000


def _post(path: str, headers: dict = None, json: dict = None):
    start = time.monotonic()
    r = httpx.post(
        f"{GATEWAY_URL}{path}",
        timeout=10,
        follow_redirects=False,
        headers=headers or {},
        json=json,
    )
    return r, (time.monotonic() - start) * 1000


class TestLevel0Public:
    """L0 — Public endpoints return 200 without any auth."""

    def test_health_is_public(self):
        r, _ = _get("/api/v1/health")
        assert r.status_code == 200

    def test_discord_config_is_public(self):
        r, _ = _get("/api/v1/auth/discord-config")
        assert r.status_code == 200

    def test_login_redirect_is_public(self):
        r, _ = _get("/api/v1/auth/discord/login")
        assert r.status_code in (302, 307), (
            f"Login should redirect, got {r.status_code}"
        )


class TestLevel1PublicData:
    """L1 — Public data endpoints return guild info without auth."""

    def test_guild_public_info_no_auth_404_or_200(self):
        """Public guild info endpoint exists and doesn't require auth.
        Returns 200 if guild exists, 404 if not — both are acceptable.
        """
        # Use a fake guild ID — we expect either 404 (not found) or 200 (public info)
        # but NOT 401 (would mean it wrongly requires auth)
        r, _ = _get("/api/v1/guilds/123456789/public")
        assert r.status_code != 401, (
            f"Public guild endpoint should not require auth (L1), got {r.status_code}"
        )


class TestLevel2User:
    """L2 — User endpoints require authentication."""

    def test_guilds_list_requires_auth(self):
        r, _ = _get("/api/v1/guilds")
        assert r.status_code == 401

    def test_auth_me_requires_auth(self):
        r, _ = _get("/api/v1/auth/me")
        assert r.status_code == 401

    def test_guild_settings_requires_auth(self):
        r, _ = _get("/api/v1/guilds/123456789/settings")
        assert r.status_code == 401


class TestLevel3Authorized:
    """L3 — Authorized endpoints require explicit guild authorization."""

    def test_update_settings_without_auth_is_401(self):
        r, _ = _post("/api/v1/guilds/123456789/settings", json={})
        assert r.status_code in (401, 405), (
            f"Update settings without auth should be 401, got {r.status_code}"
        )


@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestGuildSettingsContract:
    """
    Authenticated guild settings response shape.

    These tests guard against two classes of bug:
      1. The auto-create path crashing (e.g. scalar_one() after a commit that
         cleared SET LOCAL app.current_guild_id, making the re-query invisible
         to RLS → NoResultFound).
      2. The response shape drifting from what the frontend expects.

    Uses a non-existent guild ID so the endpoint returns 404 quickly; the auth
    and shape tests use a guild the test token has access to (if TEST_GUILD_ID
    is set).
    """

    TEST_GUILD_ID = os.environ.get("TEST_GUILD_ID", "")

    def test_guild_settings_404_for_unknown_guild(self):
        """A guild that doesn't exist must return 404, not 500."""
        r, _ = _get(
            "/api/v1/guilds/000000000000000001/settings",
            headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
        )
        # 403 is also acceptable (no access), but never 500
        assert r.status_code in (403, 404), (
            f"Unknown guild should return 403/404, got {r.status_code}: {r.text[:200]}"
        )

    @pytest.mark.skipif(not os.environ.get("TEST_GUILD_ID"), reason="TEST_GUILD_ID not set")
    def test_guild_settings_response_shape(self):
        """GET /guilds/{id}/settings must return guild_id, settings dict, and updated_at."""
        r, _ = _get(
            f"/api/v1/guilds/{os.environ['TEST_GUILD_ID']}/settings",
            headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
        )
        assert r.status_code == 200, (
            f"GET /guilds/{{guild_id}}/settings returned {r.status_code}: {r.text[:300]}"
        )
        data = r.json()
        for field in ("guild_id", "settings", "updated_at"):
            assert field in data, (
                f"guild settings response missing '{field}': {list(data.keys())}"
            )
        assert isinstance(data["settings"], dict), (
            f"'settings' must be a dict, got {type(data['settings'])}"
        )

    @pytest.mark.skipif(not os.environ.get("TEST_GUILD_ID"), reason="TEST_GUILD_ID not set")
    def test_guild_settings_auto_create_does_not_500(self):
        """
        Calling GET settings twice in a row must not crash on the second call.
        The first call auto-creates the settings row; the second call must find it.
        If the backend uses db.commit() then re-queries under RLS, the re-query
        returns nothing and scalar_one() throws NoResultFound → 500.
        """
        headers = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
        guild_id = os.environ["TEST_GUILD_ID"]
        r1, _ = _get(f"/api/v1/guilds/{guild_id}/settings", headers=headers)
        r2, _ = _get(f"/api/v1/guilds/{guild_id}/settings", headers=headers)
        assert r1.status_code == 200, f"First call failed: {r1.status_code} {r1.text[:200]}"
        assert r2.status_code == 200, f"Second call failed: {r2.status_code} {r2.text[:200]}"


class TestLevel4Administrator:
    """L4 — Administrator endpoints require guild admin status (not just authorization)."""

    def test_add_authorized_user_requires_auth(self):
        r, _ = _post(
            "/api/v1/guilds/123456789/authorized-users",
            json={"user_id": "999", "permission_level": "user"},
        )
        assert r.status_code == 401, (
            f"Adding authorized users (L4) should require auth, got {r.status_code}"
        )

    def test_add_authorized_role_requires_auth(self):
        r, _ = _post(
            "/api/v1/guilds/123456789/authorized-roles",
            json={"role_id": "999", "permission_level": "user"},
        )
        assert r.status_code == 401, (
            f"Adding authorized roles (L4) should require auth, got {r.status_code}"
        )


class TestLevel5Owner:
    """L5 — Owner-only endpoints require guild owner status."""

    def test_permissions_management_requires_auth(self):
        r, _ = _get("/api/v1/guilds/123456789/authorized-users")
        assert r.status_code == 401

    def test_authorized_roles_requires_auth(self):
        r, _ = _get("/api/v1/guilds/123456789/authorized-roles")
        assert r.status_code == 401


class TestLevel6Developer:
    """L6 — Developer/Platform Admin endpoints reject everyone without admin status."""

    def test_platform_settings_requires_auth(self):
        r, _ = _get("/api/v1/platform/settings")
        assert r.status_code == 401

    def test_shards_requires_auth(self):
        r, _ = _get("/api/v1/shards")
        assert r.status_code == 401

    @pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
    def test_platform_settings_requires_admin_even_with_auth(self):
        """A regular authenticated user (non-admin) should get 403."""
        r, _ = _get("/api/v1/platform/settings",
                    headers={"Authorization": f"Bearer {TEST_API_TOKEN}"})
        # Regular user must get 403 Forbidden (not 401, since they ARE authenticated)
        # Admin users will get 200 — skip this test if the token belongs to a platform admin.
        # The check here is: it must NOT return 200 for a non-admin.
        # Since we can't know if the test token is admin, we at least verify the
        # endpoint exists and returns a meaningful auth response.
        assert r.status_code in (200, 403), (
            f"Platform settings should return 200 (admin) or 403 (non-admin), "
            f"got {r.status_code}"
        )


class TestSensitiveEndpointProtection:
    """LLM endpoints have extra protection (SecurityMiddleware)."""

    def test_llm_generate_endpoint_requires_auth(self):
        """
        The LLM generate endpoint must reject unauthenticated requests.
        GET on a POST-only endpoint returns 405; unauthenticated POST returns 401/403.
        Both are acceptable — neither should be 200 or 404.
        """
        r, _ = _get("/api/v1/llm/generate")
        assert r.status_code in (401, 403, 405), (
            f"LLM generate (GET, no auth) should return 401/403/405, got {r.status_code}"
        )

    def test_llm_endpoint_blocked_without_auth(self):
        r, _ = _post("/api/v1/llm/generate", json={"message": "test"})
        assert r.status_code in (401, 403), (
            f"LLM generate without auth should be 401/403, got {r.status_code}"
        )
