"""
Suite 07 — Database Layer
Validates schema isolation, migration tracking, and the database management API.

All database management endpoints are Level 5 (Platform Admin only).

Coverage:
  - Auth enforcement:  every endpoint returns 401 without a token
  - Schema isolation:  /validate confirms all tables are in the app schema,
                       never in public, and alembic_version is in the right place
  - Migration status:  /migrations returns a well-formed changelog with version data
  - DB info:           /info returns version fields and connected status
  - Connection test:   /test-connection confirms postgres + redis are reachable
  - Error handling:    upgrade-to with an unknown version returns 404
"""
import time
import httpx
import pytest
import os

GATEWAY_URL  = os.environ.get("GATEWAY_URL",  "http://gateway")
BACKEND_URL  = os.environ.get("BACKEND_URL",  "http://backend:8000")
TEST_API_TOKEN = os.environ.get("TEST_API_TOKEN", "")

SUITE = "07 Database Layer"

_BASE = f"{GATEWAY_URL}/api/v1/database"


def _get(path: str, headers: dict = None):
    start = time.monotonic()
    r = httpx.get(
        f"{_BASE}{path}",
        timeout=30,
        follow_redirects=False,
        headers=headers or {},
    )
    return r, (time.monotonic() - start) * 1000


def _post(path: str, headers: dict = None, json: dict = None):
    start = time.monotonic()
    r = httpx.post(
        f"{_BASE}{path}",
        timeout=30,
        follow_redirects=False,
        headers=headers or {},
        json=json or {},
    )
    return r, (time.monotonic() - start) * 1000


def _auth():
    """Return Authorization header dict (skips automatically if no token)."""
    return {"Authorization": f"Bearer {TEST_API_TOKEN}"}


# ---------------------------------------------------------------------------
# 1 — Auth enforcement (no token required to run these)
# ---------------------------------------------------------------------------

class TestDatabaseAuthEnforcement:
    """All database management endpoints must reject unauthenticated requests."""

    def test_info_requires_auth(self):
        r, _ = _get("/info")
        assert r.status_code == 401, (
            f"GET /database/info should require auth (L5), got {r.status_code}"
        )

    def test_migrations_requires_auth(self):
        r, _ = _get("/migrations")
        assert r.status_code == 401, (
            f"GET /database/migrations should require auth (L5), got {r.status_code}"
        )

    def test_validate_requires_auth(self):
        r, _ = _get("/validate")
        assert r.status_code == 401, (
            f"GET /database/validate should require auth (L5), got {r.status_code}"
        )

    def test_test_connection_requires_auth(self):
        r, _ = _post("/test-connection")
        assert r.status_code == 401, (
            f"POST /database/test-connection should require auth (L5), got {r.status_code}"
        )

    def test_upgrade_requires_auth(self):
        r, _ = _post("/migrations/upgrade")
        assert r.status_code == 401, (
            f"POST /database/migrations/upgrade should require auth (L5), got {r.status_code}"
        )

    def test_upgrade_to_requires_auth(self):
        r, _ = _post("/migrations/upgrade-to", json={"target_version": "1.0.0"})
        assert r.status_code == 401, (
            f"POST /database/migrations/upgrade-to should require auth (L5), got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# 2 — Database info (authenticated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestDatabaseInfo:
    """GET /database/info returns version and connection status."""

    def test_info_returns_200(self):
        r, _ = _get("/info", _auth())
        assert r.status_code == 200, (
            f"GET /database/info returned {r.status_code}: {r.text[:200]}"
        )

    def test_info_has_framework_version(self):
        r, _ = _get("/info", _auth())
        data = r.json()
        assert "framework_version" in data, f"Missing 'framework_version': {data}"
        assert isinstance(data["framework_version"], str)
        assert data["framework_version"], "framework_version must not be empty"

    def test_info_has_required_db_revision(self):
        r, _ = _get("/info", _auth())
        data = r.json()
        assert "required_db_revision" in data, f"Missing 'required_db_revision': {data}"

    def test_info_postgres_connected(self):
        r, _ = _get("/info", _auth())
        data = r.json()
        assert "postgres" in data, f"Missing 'postgres' key: {data}"
        pg = data["postgres"]
        assert pg.get("status") == "connected", (
            f"Postgres is not connected: {pg}"
        )

    def test_info_redis_connected(self):
        r, _ = _get("/info", _auth())
        data = r.json()
        assert "redis" in data, f"Missing 'redis' key: {data}"
        redis = data["redis"]
        assert redis.get("status") == "connected", (
            f"Redis is not connected: {redis}"
        )

    def test_info_schema_match_is_bool(self):
        r, _ = _get("/info", _auth())
        data = r.json()
        assert "schema_match" in data, f"Missing 'schema_match': {data}"
        assert isinstance(data["schema_match"], bool)

    def test_info_schema_matches_when_up_to_date(self):
        """schema_match must be True on a fully migrated deployment."""
        r, _ = _get("/info", _auth())
        data = r.json()
        assert data.get("schema_match") is True, (
            f"schema_match is False — DB revision ({data.get('current_db_revision')}) "
            f"does not match required ({data.get('required_db_revision')}). "
            f"Run: docker compose -f docker-compose.yml -f docker-compose.test.yml "
            f"run --rm test-runner  after applying migrations."
        )

    def test_info_has_revision_history(self):
        """revision_history must be present — the frontend Overview tab uses it to
        render the Framework ↔ DB Version History panel.  A missing key causes a
        client-side crash (Object.entries(undefined) throws TypeError)."""
        r, _ = _get("/info", _auth())
        data = r.json()
        assert "revision_history" in data, (
            f"Missing 'revision_history' in /database/info response: {list(data.keys())}"
        )
        rh = data["revision_history"]
        assert isinstance(rh, dict), f"revision_history must be a dict, got {type(rh)}"
        assert len(rh) >= 1, "revision_history must contain at least one version entry"
        # Values should be revision strings (non-empty)
        for version, revision in rh.items():
            assert isinstance(version, str) and version, f"Invalid version key: {version!r}"
            assert isinstance(revision, str) and revision, (
                f"revision_history[{version!r}] is empty or not a string: {revision!r}"
            )

    def test_info_has_plugin_migrations(self):
        """plugin_migrations must be present and be a list.
        Empty on a baseline deployment with no plugin installed."""
        r, _ = _get("/info", _auth())
        data = r.json()
        assert "plugin_migrations" in data, (
            f"Missing 'plugin_migrations' in /database/info response: {list(data.keys())}"
        )
        assert isinstance(data["plugin_migrations"], list), (
            f"plugin_migrations must be a list, got {type(data['plugin_migrations'])}"
        )


# ---------------------------------------------------------------------------
# 3 — Migration changelog (authenticated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestDatabaseMigrations:
    """GET /database/migrations returns a well-formed changelog."""

    def test_migrations_returns_200(self):
        r, _ = _get("/migrations", _auth())
        assert r.status_code == 200, (
            f"GET /database/migrations returned {r.status_code}: {r.text[:200]}"
        )

    def test_migrations_has_changelog(self):
        r, _ = _get("/migrations", _auth())
        data = r.json()
        assert "changelog" in data, f"Missing 'changelog': {data}"
        assert isinstance(data["changelog"], list)
        assert len(data["changelog"]) >= 1, "changelog must have at least one version entry"

    def test_migrations_changelog_entry_shape(self):
        r, _ = _get("/migrations", _auth())
        data = r.json()
        entry = data["changelog"][0]
        for field in ("version", "description", "revisions", "head_revision",
                      "is_current", "already_applied"):
            assert field in entry, (
                f"changelog entry missing field '{field}': {entry}"
            )

    def test_migrations_has_framework_version(self):
        r, _ = _get("/migrations", _auth())
        data = r.json()
        assert "framework_version" in data, f"Missing 'framework_version': {data}"

    def test_migrations_has_schema_up_to_date(self):
        r, _ = _get("/migrations", _auth())
        data = r.json()
        assert "schema_up_to_date" in data, f"Missing 'schema_up_to_date': {data}"
        assert isinstance(data["schema_up_to_date"], bool)

    def test_migrations_does_not_have_stale_field_history(self):
        """'history' was a wrong field name that caused .map() crash — must not appear."""
        r, _ = _get("/migrations", _auth())
        assert "history" not in r.json(), (
            "'history' must not be in /database/migrations (correct field is 'changelog')"
        )

    def test_migrations_does_not_have_stale_field_needs_upgrade(self):
        """'needs_upgrade' was a wrong field name — must not appear."""
        r, _ = _get("/migrations", _auth())
        assert "needs_upgrade" not in r.json(), (
            "'needs_upgrade' must not be in /database/migrations (correct field is 'schema_up_to_date')"
        )

    def test_migrations_schema_up_to_date_on_fresh_deployment(self):
        """After a complete migration, schema_up_to_date must be True."""
        r, _ = _get("/migrations", _auth())
        data = r.json()
        assert data.get("schema_up_to_date") is True, (
            f"schema_up_to_date is False — pending versions: {data.get('pending_versions')}"
        )

    def test_migrations_no_pending_on_fresh_deployment(self):
        r, _ = _get("/migrations", _auth())
        data = r.json()
        pending = data.get("pending_versions", [])
        assert len(pending) == 0, (
            f"Unexpected pending migrations: {[v['version'] for v in pending]}"
        )

    def test_migrations_initial_version_present(self):
        r, _ = _get("/migrations", _auth())
        data = r.json()
        versions = [e["version"] for e in data["changelog"]]
        assert "1.0.0" in versions, (
            f"Initial version '1.0.0' not in changelog: {versions}"
        )

    def test_migrations_has_plugin_migrations(self):
        """plugin_migrations must be present and be a list.
        Empty on a baseline deployment with no plugin installed.
        When a plugin is installed, each entry must have the required shape."""
        r, _ = _get("/migrations", _auth())
        data = r.json()
        assert "plugin_migrations" in data, (
            f"Missing 'plugin_migrations' in /database/migrations response: {list(data.keys())}"
        )
        assert isinstance(data["plugin_migrations"], list), (
            f"plugin_migrations must be a list, got {type(data['plugin_migrations'])}"
        )
        for entry in data["plugin_migrations"]:
            for field in ("plugin", "version", "description", "revisions",
                          "head_revision", "already_applied"):
                assert field in entry, (
                    f"plugin_migrations entry missing field '{field}': {entry}"
                )


# ---------------------------------------------------------------------------
# 4 — Schema isolation via /validate (authenticated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestSchemaIsolation:
    """
    GET /database/validate runs the backend's built-in schema validation suite.

    This is the definitive test that:
    - All expected tables exist in the app schema (not public)
    - Required columns are present with correct nullability
    - alembic_version is tracked inside the app schema
    - The live DB revision matches the framework requirement
    """

    def test_validate_returns_200(self):
        r, _ = _get("/validate", _auth())
        assert r.status_code == 200, (
            f"GET /database/validate returned {r.status_code}: {r.text[:200]}"
        )

    def test_validate_response_shape(self):
        r, _ = _get("/validate", _auth())
        data = r.json()
        for field in ("passed", "total_checks", "passed_count", "failed_count", "results"):
            assert field in data, f"validate response missing '{field}': {data}"

    def test_validate_all_checks_pass(self):
        r, _ = _get("/validate", _auth())
        data = r.json()
        assert data.get("passed") is True, (
            f"Schema validation failed — {data.get('failed_count')} check(s) failed.\n"
            + "\n".join(
                f"  ✗ {c['check']}: {c['detail']}"
                for c in data.get("results", [])
                if not c.get("passed")
            )
        )

    def test_validate_core_tables_present(self):
        """Core framework tables must all be found in the app schema."""
        r, _ = _get("/validate", _auth())
        data = r.json()
        table_checks = {
            c["check"].replace("Table: ", ""): c["passed"]
            for c in data.get("results", [])
            if c["check"].startswith("Table:")
        }
        required = ["users", "guilds", "guild_settings", "authorized_users",
                    "authorized_roles", "audit_logs", "user_tokens", "alembic_version"]
        missing = [t for t in required if not table_checks.get(t)]
        assert not missing, (
            f"Core tables missing from app schema: {missing}"
        )

    def test_validate_alembic_version_in_app_schema(self):
        """alembic_version must be tracked inside the app schema, not public."""
        r, _ = _get("/validate", _auth())
        data = r.json()
        alembic_check = next(
            (c for c in data.get("results", []) if c["check"] == "Table: alembic_version"),
            None,
        )
        assert alembic_check is not None, "alembic_version table check not found in validate results"
        assert alembic_check["passed"], (
            f"alembic_version not found in app schema: {alembic_check['detail']}"
        )

    def test_validate_schema_version_check_passes(self):
        """The Alembic revision check must pass (DB at correct version)."""
        r, _ = _get("/validate", _auth())
        data = r.json()
        version_check = next(
            (c for c in data.get("results", []) if "schema version" in c["check"].lower()),
            None,
        )
        assert version_check is not None, "Alembic schema version check not found in results"
        assert version_check["passed"], (
            f"Schema version mismatch: {version_check['detail']}"
        )

    def test_validate_no_public_schema_tables(self):
        """
        The validate endpoint runs in the app schema context (search_path).
        If it finds all expected tables, they are confirmed to be in the app schema.
        A schema isolation failure would show up as missing tables.
        This test confirms total_checks > 0 (inspection succeeded) and passed == True.
        """
        r, _ = _get("/validate", _auth())
        data = r.json()
        assert data.get("total_checks", 0) > 0, "Validation ran zero checks — schema inspection failed"
        assert data.get("passed") is True, (
            "Schema isolation failure: some tables may be in public instead of the app schema"
        )


# ---------------------------------------------------------------------------
# 5 — Connection test (authenticated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestConnectionTest:
    """POST /database/test-connection confirms live connectivity."""

    def test_connection_returns_200(self):
        r, _ = _post("/test-connection", _auth())
        assert r.status_code == 200, (
            f"POST /database/test-connection returned {r.status_code}: {r.text[:200]}"
        )

    def test_connection_postgres_ok(self):
        r, _ = _post("/test-connection", _auth())
        data = r.json()
        assert data.get("postgres", {}).get("ok") is True, (
            f"Postgres connection test failed: {data.get('postgres')}"
        )

    def test_connection_redis_ok(self):
        r, _ = _post("/test-connection", _auth())
        data = r.json()
        assert data.get("redis", {}).get("ok") is True, (
            f"Redis connection test failed: {data.get('redis')}"
        )

    def test_connection_all_ok(self):
        r, _ = _post("/test-connection", _auth())
        data = r.json()
        assert data.get("all_ok") is True, (
            f"Not all connections healthy: {data}"
        )


# ---------------------------------------------------------------------------
# 6 — Error handling (authenticated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestDatabaseErrorHandling:
    """Edge cases and error responses from the database management API."""

    def test_upgrade_to_unknown_version_returns_404(self):
        """upgrade-to with a version not in MIGRATION_CHANGELOG must return 404."""
        r, _ = _post(
            "/migrations/upgrade-to",
            headers=_auth(),
            json={"target_version": "99.99.99"},
        )
        assert r.status_code == 404, (
            f"upgrade-to unknown version should return 404, got {r.status_code}: {r.text[:200]}"
        )

    def test_upgrade_to_missing_body_returns_422(self):
        """upgrade-to with no body must return 422 (validation error)."""
        r, _ = _post("/migrations/upgrade-to", headers=_auth(), json={})
        assert r.status_code == 422, (
            f"upgrade-to with empty body should return 422, got {r.status_code}"
        )
