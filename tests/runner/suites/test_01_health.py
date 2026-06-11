"""
Suite 01 — Health & Connectivity
Tests that all services are reachable and returning healthy responses.
"""
import time
import pytest
import httpx
import os

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

SUITE = "01 Health & Connectivity"


def _get(url: str, **kwargs):
    """GET with timing. Returns (response, duration_ms)."""
    start = time.monotonic()
    r = httpx.get(url, timeout=10, follow_redirects=False, **kwargs)
    return r, (time.monotonic() - start) * 1000


class TestHealth:
    """Backend health endpoint is accessible through the gateway."""

    def test_gateway_health_200(self, client):
        r, ms = _get(f"{GATEWAY_URL}/api/v1/health")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_gateway_health_body(self, client):
        r, _ = _get(f"{GATEWAY_URL}/api/v1/health")
        data = r.json()
        assert "status" in data, f"Missing 'status' key in response: {data}"

    def test_gateway_health_response_time(self):
        """Health endpoint should respond within 2 seconds."""
        _, ms = _get(f"{GATEWAY_URL}/api/v1/health")
        assert ms < 2000, f"Health endpoint took {ms:.0f}ms (limit: 2000ms)"

    def test_backend_direct_health_200(self):
        """Backend is directly reachable from within Docker intranet."""
        r, _ = _get(f"{BACKEND_URL}/api/v1/health")
        assert r.status_code == 200, f"Backend direct health failed: {r.status_code}"

    def test_gateway_sets_server_header_hidden(self):
        """Nginx should hide its version (server_tokens off)."""
        r, _ = _get(f"{GATEWAY_URL}/api/v1/health")
        server = r.headers.get("server", "")
        assert "nginx/" not in server.lower(), (
            f"Nginx version exposed in Server header: {server}"
        )
