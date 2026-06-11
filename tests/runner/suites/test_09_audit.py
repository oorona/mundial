"""
Suite 09 — Audit Log Contract
Verifies that every guild mutation endpoint writes an AuditLog entry.

Framework rule: every backend endpoint that modifies settings MUST write
an AuditLog entry (CLAUDE.md Golden Rule #5).

Endpoints under test (all require TEST_API_TOKEN + TEST_GUILD_ID):
  PUT  /api/v1/guilds/{id}/settings              → action: UPDATE_SETTINGS
  POST /api/v1/guilds/{id}/authorized-users      → action: ADD_AUTHORIZED_USER
  DEL  /api/v1/guilds/{id}/authorized-users/{id} → action: REMOVE_AUTHORIZED_USER
  POST /api/v1/guilds/{id}/authorized-roles      → action: ADD_AUTHORIZED_ROLE
  DEL  /api/v1/guilds/{id}/authorized-roles/{id} → action: REMOVE_AUTHORIZED_ROLE

All tests are skipped unless both TEST_API_TOKEN and TEST_GUILD_ID are set.
TEST_USER_ID (a Discord user ID that can be added/removed) is optional — only
the authorized-user add/remove tests need it.
"""
import time
import httpx
import pytest
import os

GATEWAY_URL    = os.environ.get("GATEWAY_URL",    "http://gateway")
BACKEND_URL    = os.environ.get("BACKEND_URL",    "http://backend:8000")
TEST_API_TOKEN = os.environ.get("TEST_API_TOKEN", "")
TEST_GUILD_ID  = os.environ.get("TEST_GUILD_ID",  "")
TEST_USER_ID   = os.environ.get("TEST_USER_ID",   "")   # Discord user ID to add/remove in tests
TEST_ROLE_ID   = os.environ.get("TEST_ROLE_ID",   "")   # Discord role ID to add/remove in tests

SUITE = "09 Audit Log"

NEEDS_AUTH_AND_GUILD = pytest.mark.skipif(
    not TEST_API_TOKEN or not TEST_GUILD_ID,
    reason="TEST_API_TOKEN and TEST_GUILD_ID required",
)


def _get(path: str, *, base: str = None):
    r = httpx.get(
        f"{base or GATEWAY_URL}{path}",
        headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
        timeout=15,
        follow_redirects=False,
    )
    return r


def _post(path: str, json: dict = None):
    r = httpx.post(
        f"{GATEWAY_URL}{path}",
        headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
        json=json or {},
        timeout=15,
        follow_redirects=False,
    )
    return r


def _put(path: str, json: dict = None):
    r = httpx.put(
        f"{GATEWAY_URL}{path}",
        headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
        json=json or {},
        timeout=15,
        follow_redirects=False,
    )
    return r


def _delete(path: str):
    r = httpx.delete(
        f"{GATEWAY_URL}{path}",
        headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
        timeout=15,
        follow_redirects=False,
    )
    return r


def _get_audit_logs(guild_id: str) -> list:
    """Return the current audit log entries for a guild."""
    r = _get(f"/api/v1/guilds/{guild_id}/audit-logs")
    if r.status_code == 200:
        return r.json()
    return []


def _latest_action(guild_id: str) -> str | None:
    logs = _get_audit_logs(guild_id)
    return logs[0]["action"] if logs else None


# ---------------------------------------------------------------------------
# Audit log endpoint contract
# ---------------------------------------------------------------------------

@NEEDS_AUTH_AND_GUILD
class TestAuditLogEndpointContract:
    """GET /api/v1/guilds/{id}/audit-logs returns a well-formed list."""

    def test_returns_200_or_403(self):
        r = _get(f"/api/v1/guilds/{TEST_GUILD_ID}/audit-logs")
        assert r.status_code in (200, 403), (
            f"audit-logs returned unexpected status {r.status_code}: {r.text[:200]}"
        )

    def test_returns_list_when_accessible(self):
        r = _get(f"/api/v1/guilds/{TEST_GUILD_ID}/audit-logs")
        if r.status_code == 403:
            pytest.skip("Token does not have audit-log access on this guild")
        assert isinstance(r.json(), list), (
            f"audit-logs must return a list, got: {type(r.json())}"
        )

    def test_entry_shape_when_logs_exist(self):
        r = _get(f"/api/v1/guilds/{TEST_GUILD_ID}/audit-logs")
        if r.status_code == 403:
            pytest.skip("Token does not have audit-log access on this guild")
        logs = r.json()
        if not logs:
            pytest.skip("No audit log entries yet — run mutation tests first")
        entry = logs[0]
        for field in ("id", "guild_id", "user_id", "action", "created_at"):
            assert field in entry, (
                f"AuditLog entry missing '{field}': {list(entry.keys())}"
            )


# ---------------------------------------------------------------------------
# Settings mutation audit
# ---------------------------------------------------------------------------

@NEEDS_AUTH_AND_GUILD
class TestSettingsMutationAudit:
    """PUT /guild/{id}/settings must write an AuditLog entry."""

    def test_settings_update_writes_audit_entry(self):
        # Read current settings first
        r_get = _get(f"/api/v1/guilds/{TEST_GUILD_ID}/settings")
        if r_get.status_code == 403:
            pytest.skip("Token does not have settings access on this guild")
        assert r_get.status_code == 200, f"GET settings failed: {r_get.status_code}"

        current = r_get.json().get("settings", {})

        # Make a no-op write (round-trip the existing settings)
        r_put = _put(
            f"/api/v1/guilds/{TEST_GUILD_ID}/settings",
            json={"settings": current},
        )
        if r_put.status_code == 403:
            pytest.skip("Token does not have settings write access on this guild")
        assert r_put.status_code == 200, (
            f"PUT settings failed: {r_put.status_code} {r_put.text[:200]}"
        )

        # Audit log must record the action
        logs = _get_audit_logs(TEST_GUILD_ID)
        assert logs, "No audit log entries after settings update"
        actions = [e["action"] for e in logs]
        assert "UPDATE_SETTINGS" in actions, (
            f"Expected 'UPDATE_SETTINGS' in audit log. Found: {actions[:5]}"
        )

    def test_settings_update_response_shape(self):
        """PUT /settings must return guild_id, settings, and updated_at."""
        r_get = _get(f"/api/v1/guilds/{TEST_GUILD_ID}/settings")
        if r_get.status_code in (403, 404):
            pytest.skip("Token does not have settings access")
        current = r_get.json().get("settings", {})

        r_put = _put(
            f"/api/v1/guilds/{TEST_GUILD_ID}/settings",
            json={"settings": current},
        )
        if r_put.status_code == 403:
            pytest.skip("Token does not have settings write access")
        data = r_put.json()
        for field in ("guild_id", "settings", "updated_at"):
            assert field in data, (
                f"PUT /settings response missing '{field}': {list(data.keys())}"
            )


# ---------------------------------------------------------------------------
# Authorized-user mutation audit
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not TEST_API_TOKEN or not TEST_GUILD_ID or not TEST_USER_ID,
    reason="TEST_API_TOKEN, TEST_GUILD_ID, and TEST_USER_ID required",
)
class TestAuthorizedUserMutationAudit:
    """
    POST/DELETE /guilds/{id}/authorized-users must write AuditLog entries.
    Requires TEST_USER_ID — a Discord user ID to add then remove.
    """

    def test_add_user_writes_audit_entry(self):
        r = _post(
            f"/api/v1/guilds/{TEST_GUILD_ID}/authorized-users",
            json={"user_id": TEST_USER_ID, "permission_level": "user"},
        )
        if r.status_code == 403:
            pytest.skip("Token does not have permission to add authorized users")
        assert r.status_code in (200, 201, 409), (
            f"POST authorized-users returned {r.status_code}: {r.text[:200]}"
        )
        if r.status_code == 409:
            pytest.skip("User already authorized — add test not applicable")

        logs = _get_audit_logs(TEST_GUILD_ID)
        actions = [e["action"] for e in logs]
        assert any("AUTHORIZED" in a or "ADD" in a for a in actions), (
            f"No ADD_AUTHORIZED_USER action in audit log after adding user. "
            f"Recent actions: {actions[:5]}"
        )

    def test_remove_user_writes_audit_entry(self):
        # Ensure user exists first
        _post(
            f"/api/v1/guilds/{TEST_GUILD_ID}/authorized-users",
            json={"user_id": TEST_USER_ID, "permission_level": "user"},
        )

        r = _delete(f"/api/v1/guilds/{TEST_GUILD_ID}/authorized-users/{TEST_USER_ID}")
        if r.status_code == 403:
            pytest.skip("Token does not have permission to remove authorized users")
        if r.status_code == 400:
            pytest.skip("TEST_USER_ID is the guild owner — cannot be removed (use a non-owner user ID)")
        assert r.status_code in (200, 204, 404), (
            f"DELETE authorized-users returned {r.status_code}: {r.text[:200]}"
        )
        if r.status_code == 404:
            pytest.skip("User was not authorized — remove test not applicable")

        logs = _get_audit_logs(TEST_GUILD_ID)
        actions = [e["action"] for e in logs]
        assert any("REMOVE" in a or "DELETE" in a for a in actions), (
            f"No REMOVE_AUTHORIZED_USER action in audit log after removing user. "
            f"Recent actions: {actions[:5]}"
        )


# ---------------------------------------------------------------------------
# Authorized-role mutation audit
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not TEST_API_TOKEN or not TEST_GUILD_ID or not TEST_ROLE_ID,
    reason="TEST_API_TOKEN, TEST_GUILD_ID, and TEST_ROLE_ID required",
)
class TestAuthorizedRoleMutationAudit:
    """
    POST/DELETE /guilds/{id}/authorized-roles must write AuditLog entries.
    Requires TEST_ROLE_ID — a Discord role ID in the test guild.
    """

    def test_add_role_writes_audit_entry(self):
        r = _post(
            f"/api/v1/guilds/{TEST_GUILD_ID}/authorized-roles",
            json={"role_id": TEST_ROLE_ID, "permission_level": "user"},
        )
        if r.status_code == 403:
            pytest.skip("Token does not have permission to add authorized roles")
        assert r.status_code in (200, 201, 409), (
            f"POST authorized-roles returned {r.status_code}: {r.text[:200]}"
        )
        if r.status_code == 409:
            pytest.skip("Role already authorized — add test not applicable")

        logs = _get_audit_logs(TEST_GUILD_ID)
        actions = [e["action"] for e in logs]
        assert any("ROLE" in a for a in actions), (
            f"No role-related action in audit log after adding role. "
            f"Recent actions: {actions[:5]}"
        )

    def test_remove_role_writes_audit_entry(self):
        _post(
            f"/api/v1/guilds/{TEST_GUILD_ID}/authorized-roles",
            json={"role_id": TEST_ROLE_ID, "permission_level": "user"},
        )

        r = _delete(f"/api/v1/guilds/{TEST_GUILD_ID}/authorized-roles/{TEST_ROLE_ID}")
        if r.status_code == 403:
            pytest.skip("Token does not have permission to remove authorized roles")
        assert r.status_code in (200, 204, 404), (
            f"DELETE authorized-roles returned {r.status_code}: {r.text[:200]}"
        )
        if r.status_code == 404:
            pytest.skip("Role was not authorized — remove test not applicable")

        logs = _get_audit_logs(TEST_GUILD_ID)
        actions = [e["action"] for e in logs]
        assert any("ROLE" in a and ("REMOVE" in a or "DELETE" in a) for a in actions), (
            f"No remove-role action in audit log after removing role. "
            f"Recent actions: {actions[:5]}"
        )


# ---------------------------------------------------------------------------
# Audit log integrity
# ---------------------------------------------------------------------------

@NEEDS_AUTH_AND_GUILD
class TestAuditLogIntegrity:
    """Structural guarantees about every audit log entry."""

    def test_audit_log_entries_have_guild_id(self):
        r = _get(f"/api/v1/guilds/{TEST_GUILD_ID}/audit-logs")
        if r.status_code == 403:
            pytest.skip("Token does not have audit-log access")
        logs = r.json()
        if not logs:
            pytest.skip("No audit log entries to validate")
        for entry in logs[:10]:
            assert str(entry.get("guild_id")) == str(TEST_GUILD_ID), (
                f"AuditLog entry has wrong guild_id: {entry.get('guild_id')} "
                f"(expected {TEST_GUILD_ID})"
            )

    def test_audit_log_entries_have_timestamp(self):
        r = _get(f"/api/v1/guilds/{TEST_GUILD_ID}/audit-logs")
        if r.status_code == 403:
            pytest.skip("Token does not have audit-log access")
        logs = r.json()
        if not logs:
            pytest.skip("No audit log entries to validate")
        for entry in logs[:10]:
            # AuditLog schema uses created_at (not timestamp)
            assert entry.get("created_at"), (
                f"AuditLog entry missing created_at: {entry}"
            )

    def test_rls_prevents_cross_guild_audit_log_access(self):
        """
        Audit logs must be scoped to the guild — a fake guild ID must not
        return entries from the real guild.
        """
        fake_guild_id = "111111111111111111"
        r = _get(f"/api/v1/guilds/{fake_guild_id}/audit-logs")
        # Should get 403 (no access) or 404 (guild not found) — never 200 with data
        if r.status_code == 200:
            logs = r.json()
            real_guild_logs = [
                e for e in logs
                if str(e.get("guild_id")) == str(TEST_GUILD_ID)
            ]
            assert not real_guild_logs, (
                f"RLS failure: real guild's audit logs visible through fake guild ID! "
                f"Leaked {len(real_guild_logs)} entries."
            )
