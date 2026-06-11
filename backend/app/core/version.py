"""
Framework version and database migration tracking.

All version data lives in backend/migration_inventory.json — this module
is pure logic that reads from it.  Nothing here is hardcoded.

To release a new framework version:
  1. Create the Alembic migration(s): alembic revision --autogenerate -m "desc"
  2. Note the revision ID from the generated file.
  3. Append a new entry to framework_migrations in migration_inventory.json.
  4. Bump framework_version in migration_inventory.json.

To register a plugin migration:
  install_plugin.sh writes to migration_inventory.json automatically.
  The only manual step after that is: alembic upgrade head.
"""

import json
from pathlib import Path
from typing import Optional

# ── Load inventory ────────────────────────────────────────────────────────────

_INVENTORY_PATH = Path(__file__).resolve().parent.parent.parent / "migration_inventory.json"


def _load_inventory() -> dict:
    if not _INVENTORY_PATH.exists():
        raise FileNotFoundError(
            f"migration_inventory.json not found at {_INVENTORY_PATH}. "
            "This file must exist and be tracked in source control. "
            "If you are rebuilding the image, ensure it was committed before the build."
        )
    return json.loads(_INVENTORY_PATH.read_text())


_inv = _load_inventory()

# ── Public constants (same API as before — all consumers unchanged) ───────────

FRAMEWORK_VERSION: str          = _inv["framework_version"]
MIGRATION_CHANGELOG: list[dict] = _inv["framework_migrations"]
PLUGIN_MIGRATIONS: list[dict]   = _inv.get("plugin_migrations", [])

# Derived: version → head revision map
VERSION_REVISIONS: dict[str, str] = {
    e["version"]: e["head_revision"] for e in MIGRATION_CHANGELOG
}

# Derived: Alembic revision the current framework version requires
REQUIRED_DB_REVISION: str = VERSION_REVISIONS[FRAMEWORK_VERSION]


# ── Helper functions ──────────────────────────────────────────────────────────

def _version_key(v: str) -> tuple[int, ...]:
    """Return a comparable tuple from a semver string, e.g. "1.2.0" → (1, 2, 0)."""
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def get_version_order() -> list[str]:
    """Return all known framework versions in ascending semantic order."""
    return sorted(VERSION_REVISIONS.keys(), key=_version_key)


def get_app_version_for_revision(revision: Optional[str]) -> Optional[str]:
    """
    Return the framework version whose HEAD revision matches *revision*.

    If *revision* belongs to a plugin, returns FRAMEWORK_VERSION — plugin
    migrations always chain off the framework head, so all framework migrations
    are implicitly applied when a plugin revision is current.

    Returns None if *revision* is None or completely unrecognised.
    """
    if not revision:
        return None
    for version, rev in VERSION_REVISIONS.items():
        if rev == revision:
            return version
    # Plugin revision → framework is fully applied
    if is_plugin_revision(revision):
        return FRAMEWORK_VERSION
    return None


def get_changelog_entry(version: str) -> Optional[dict]:
    """Return the MIGRATION_CHANGELOG entry for *version*, or None."""
    for entry in MIGRATION_CHANGELOG:
        if entry["version"] == version:
            return entry
    return None


def get_plugin_migration(plugin_name: str) -> Optional[dict]:
    """Return the PLUGIN_MIGRATIONS entry for *plugin_name*, or None."""
    for entry in PLUGIN_MIGRATIONS:
        if entry.get("plugin") == plugin_name:
            return entry
    return None


def is_plugin_revision(revision: Optional[str]) -> bool:
    """Return True if *revision* belongs to a plugin (not the framework)."""
    if not revision:
        return False
    for entry in PLUGIN_MIGRATIONS:
        if revision in entry.get("revisions", []):
            return True
    return False


def get_upgrade_path(
    current_revision: Optional[str],
    target_version: Optional[str] = None,
) -> list[dict]:
    """
    Return an ordered list of changelog entries that need to be applied to
    bring the database from *current_revision* to *target_version*
    (defaults to FRAMEWORK_VERSION).

    Each returned entry is a MIGRATION_CHANGELOG dict augmented with
    ``"already_applied": bool``.
    """
    if target_version is None:
        target_version = FRAMEWORK_VERSION

    current_version = get_app_version_for_revision(current_revision)
    ordered         = get_version_order()
    path: list[dict] = []

    for entry in MIGRATION_CHANGELOG:
        v = entry["version"]
        if v not in ordered:
            continue

        already_applied = (
            current_version is not None
            and _version_key(v) <= _version_key(current_version)
        )
        is_above_target = _version_key(v) > _version_key(target_version)

        if is_above_target:
            break

        path.append({**entry, "already_applied": already_applied})

    return path
