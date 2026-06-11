"""
Shared fixtures for the Baseline framework live test suite.

IMPORTANT — Setup Wizard Guard
───────────────────────────────
The entire test suite is guarded by a setup-wizard check.  If the platform
has not been configured (GET /api/v1/setup/state → setup_complete: false),
every test is skipped with a clear message rather than producing a wall of
cryptic failures.

Run the setup wizard at /setup before executing the test suite for the first time.
"""
import os
import pytest
import httpx

# ─── Target URLs ──────────────────────────────────────────────────────────────
# Override via environment variables when running outside Docker.
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

# Optional: a valid API token to use for authenticated test calls.
# Generate one by logging in via the browser, then set this env var.
TEST_API_TOKEN = os.environ.get("TEST_API_TOKEN", "")

# ─── Setup Wizard Guard ────────────────────────────────────────────────────────
# Checked once at session start.  None = not yet checked.
_WIZARD_COMPLETE: bool | None = None


def _check_wizard_complete() -> bool:
    """
    Hit the setup/state endpoint and return True only when setup_complete is True.
    Returns False on any network error (tests will be skipped with a clear message).
    """
    try:
        r = httpx.get(
            f"{GATEWAY_URL}/api/v1/setup/state",
            timeout=10,
            follow_redirects=False,
        )
        if r.status_code == 200:
            return bool(r.json().get("setup_complete", False))
        # 503 is the wizard-mode gate returning "Platform not configured"
        return False
    except Exception:
        return False


def pytest_runtest_setup(item):
    """
    Called before every test.  Skips the test (not fails it) when the setup
    wizard has not been completed, so the output clearly says "skipped" rather
    than producing hundreds of confusing failures.
    """
    global _WIZARD_COMPLETE
    if _WIZARD_COMPLETE is None:
        _WIZARD_COMPLETE = _check_wizard_complete()
    if not _WIZARD_COMPLETE:
        pytest.skip(
            "Setup wizard not completed — run the setup wizard at /setup first "
            "(GET /api/v1/setup/state returns setup_complete: false)"
        )


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def gateway_url():
    return GATEWAY_URL

@pytest.fixture(scope="session")
def backend_url():
    return BACKEND_URL

@pytest.fixture(scope="session")
def api_token():
    return TEST_API_TOKEN

@pytest.fixture(scope="session")
def auth_headers():
    """Authorization headers for authenticated requests."""
    if TEST_API_TOKEN:
        return {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    return {}

@pytest.fixture(scope="session")
def gateway_headers():
    """Headers that simulate a request coming from the nginx gateway."""
    return {"X-Gateway-Request": "true"}

@pytest.fixture(scope="session")
def client():
    """Synchronous httpx client hitting the gateway."""
    with httpx.Client(base_url=GATEWAY_URL, timeout=30.0, follow_redirects=False) as c:
        yield c

@pytest.fixture(scope="session")
def backend_client():
    """Synchronous httpx client hitting the backend directly (intranet)."""
    with httpx.Client(base_url=BACKEND_URL, timeout=30.0, follow_redirects=False) as c:
        yield c
