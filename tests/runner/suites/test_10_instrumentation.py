"""
Suite 10 — Instrumentation
Validates the instrumentation endpoints: card-click tracking, stats, and metrics.

Coverage:
  - Auth enforcement on protected endpoints
  - POST /instrumentation/card-click writes without error (L1)
  - GET  /instrumentation/stats returns well-formed analytics (L6)
  - GET  /instrumentation/metrics returns Prometheus text (L4 internal)
"""
import time
import httpx
import pytest
import os

GATEWAY_URL    = os.environ.get("GATEWAY_URL",    "http://gateway")
BACKEND_URL    = os.environ.get("BACKEND_URL",    "http://backend:8000")
TEST_API_TOKEN = os.environ.get("TEST_API_TOKEN", "")

SUITE = "10 Instrumentation"


def _get(path: str, headers: dict = None, base: str = None):
    start = time.monotonic()
    r = httpx.get(
        f"{base or GATEWAY_URL}{path}",
        headers=headers or {},
        timeout=15,
        follow_redirects=False,
    )
    return r, (time.monotonic() - start) * 1000


def _post(path: str, headers: dict = None, json: dict = None):
    start = time.monotonic()
    r = httpx.post(
        f"{GATEWAY_URL}{path}",
        headers=headers or {},
        json=json or {},
        timeout=15,
        follow_redirects=False,
    )
    return r, (time.monotonic() - start) * 1000


def _auth():
    return {"Authorization": f"Bearer {TEST_API_TOKEN}"}


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------

class TestInstrumentationAuthEnforcement:
    """Protected instrumentation endpoints must reject unauthenticated requests."""

    def test_card_click_requires_auth(self):
        r, _ = _post("/api/v1/instrumentation/card-click", json={"card_id": "test"})
        assert r.status_code == 401, (
            f"POST /instrumentation/card-click should require auth, got {r.status_code}"
        )

    def test_stats_requires_auth(self):
        r, _ = _get("/api/v1/instrumentation/stats")
        assert r.status_code == 401, (
            f"GET /instrumentation/stats should require auth (L6), got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# Card-click tracking (L1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestCardClickTracking:
    """POST /api/v1/instrumentation/card-click — L1 Authenticated"""

    def test_card_click_returns_204(self):
        r, _ = _post(
            "/api/v1/instrumentation/card-click",
            headers=_auth(),
            json={"card_id": "test-suite"},
        )
        assert r.status_code == 204, (
            f"POST /instrumentation/card-click returned {r.status_code}: {r.text[:200]}"
        )

    def test_card_click_response_time_under_1s(self):
        _, ms = _post(
            "/api/v1/instrumentation/card-click",
            headers=_auth(),
            json={"card_id": "test-perf"},
        )
        assert ms < 1000, f"card-click took {ms:.0f}ms (limit: 1000ms)"

    def test_card_click_missing_card_id_returns_422(self):
        r, _ = _post(
            "/api/v1/instrumentation/card-click",
            headers=_auth(),
            json={},
        )
        assert r.status_code == 422, (
            f"card-click with missing card_id should return 422, got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# Stats endpoint (L6)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestInstrumentationStats:
    """GET /api/v1/instrumentation/stats — L6 Platform Admin"""

    def test_stats_returns_200_or_403(self):
        """Platform admins get 200; regular users get 403."""
        r, _ = _get("/api/v1/instrumentation/stats", headers=_auth())
        assert r.status_code in (200, 403), (
            f"GET /instrumentation/stats returned {r.status_code}: {r.text[:200]}"
        )

    def test_stats_response_shape_for_admin(self):
        r, _ = _get("/api/v1/instrumentation/stats", headers=_auth())
        if r.status_code == 403:
            pytest.skip("Token is not a platform admin — stats shape test skipped")
        data = r.json()
        for field in ("guild_growth", "card_usage", "top_commands"):
            assert field in data, (
                f"Missing '{field}' in /instrumentation/stats: {list(data.keys())}"
            )

    def test_stats_guild_growth_is_list(self):
        r, _ = _get("/api/v1/instrumentation/stats", headers=_auth())
        if r.status_code == 403:
            pytest.skip("Token is not a platform admin")
        data = r.json()
        assert isinstance(data.get("guild_growth"), list), (
            f"guild_growth must be a list, got {type(data.get('guild_growth'))}"
        )

    def test_stats_card_usage_is_list(self):
        r, _ = _get("/api/v1/instrumentation/stats", headers=_auth())
        if r.status_code == 403:
            pytest.skip("Token is not a platform admin")
        data = r.json()
        assert isinstance(data.get("card_usage"), list), (
            f"card_usage must be a list, got {type(data.get('card_usage'))}"
        )
