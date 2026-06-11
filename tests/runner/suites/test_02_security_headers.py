"""
Suite 02 — Security Headers
Validates that the gateway returns the required security headers on all responses.
"""
import time
import httpx
import pytest
import os

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway")
SUITE = "02 Security Headers"


def _get(path: str, **kwargs):
    start = time.monotonic()
    r = httpx.get(f"{GATEWAY_URL}{path}", timeout=10, follow_redirects=False, **kwargs)
    return r, (time.monotonic() - start) * 1000


class TestSecurityHeaders:

    def test_x_frame_options(self):
        r, _ = _get("/api/v1/health")
        assert r.headers.get("x-frame-options", "").upper() == "DENY", (
            f"X-Frame-Options should be DENY, got: {r.headers.get('x-frame-options')}"
        )

    def test_x_content_type_options(self):
        r, _ = _get("/api/v1/health")
        assert r.headers.get("x-content-type-options", "").lower() == "nosniff", (
            f"X-Content-Type-Options should be nosniff, got: "
            f"{r.headers.get('x-content-type-options')}"
        )

    def test_x_xss_protection(self):
        r, _ = _get("/api/v1/health")
        val = r.headers.get("x-xss-protection", "")
        assert "1" in val, (
            f"X-XSS-Protection should contain '1', got: {val}"
        )

    def test_referrer_policy(self):
        r, _ = _get("/api/v1/health")
        val = r.headers.get("referrer-policy", "")
        assert val != "", "Referrer-Policy header is missing"

    def test_strict_transport_security(self):
        r, _ = _get("/api/v1/health")
        hsts = r.headers.get("strict-transport-security", "")
        assert "max-age" in hsts, (
            f"HSTS header missing or malformed: {hsts}"
        )

    def test_content_security_policy_present(self):
        r, _ = _get("/api/v1/health")
        csp = r.headers.get("content-security-policy", "")
        assert csp != "", "Content-Security-Policy header is missing"

    def test_csp_has_default_src(self):
        r, _ = _get("/api/v1/health")
        csp = r.headers.get("content-security-policy", "")
        assert "default-src" in csp, f"CSP missing default-src: {csp}"

    def test_no_nginx_version_in_server(self):
        r, _ = _get("/api/v1/health")
        server = r.headers.get("server", "")
        assert "/" not in server, (
            f"Server header exposes version info: {server}"
        )
