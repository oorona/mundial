#!/usr/bin/env python3
"""
plugin_remove.py — Removes an installed plugin from the Baseline project.

Usage:
    python scripts/plugin_remove.py <plugin_name>
    python scripts/plugin_remove.py <plugin_name> --dry-run
"""

import json
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
ROOT = Path(__file__).resolve().parent.parent


def log(msg: str):
    prefix = "[DRY-RUN] " if DRY_RUN else ""
    print(f"  {prefix}{msg}")


def remove_file(path: Path):
    if path.exists():
        log(f"DELETE {path.relative_to(ROOT)}")
        if not DRY_RUN:
            path.unlink()
    else:
        log(f"SKIP   {path.relative_to(ROOT)} (not found)")


def remove_dir(path: Path):
    if path.exists() and path.is_dir():
        log(f"RMDIR  {path.relative_to(ROOT)}")
        if not DRY_RUN:
            import shutil
            shutil.rmtree(path)
    else:
        log(f"SKIP   {path.relative_to(ROOT)} (not found)")


def deregister_router(plugin_name: str):
    registry_path = ROOT / "backend/installed_plugins.json"
    if not registry_path.exists():
        log("SKIP   backend/installed_plugins.json (not found)")
        return

    plugins: list[dict] = json.loads(registry_path.read_text())
    before = len(plugins)
    plugins = [p for p in plugins if p.get("name") != plugin_name]

    if len(plugins) == before:
        log(f"SKIP   backend/installed_plugins.json — '{plugin_name}' not registered")
    else:
        log(f"WRITE  backend/installed_plugins.json — removed '{plugin_name}' entry")
        if not DRY_RUN:
            registry_path.write_text(json.dumps(plugins, indent=2, ensure_ascii=False) + "\n")


def deregister_migration(plugin_name: str):
    inventory_path = ROOT / "backend/migration_inventory.json"
    if not inventory_path.exists():
        return

    inventory = json.loads(inventory_path.read_text())
    before = len(inventory.get("plugin_migrations", []))
    inventory["plugin_migrations"] = [
        e for e in inventory.get("plugin_migrations", [])
        if e.get("plugin") != plugin_name
    ]
    after = len(inventory["plugin_migrations"])

    if after < before:
        log(f"WRITE  backend/migration_inventory.json — removed '{plugin_name}' migration entry")
        if not DRY_RUN:
            inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python scripts/plugin_remove.py <plugin_name> [--dry-run]")
        sys.exit(1)

    plugin_name = args[0]
    print(f"\nRemoving plugin '{plugin_name}'...\n{'=' * 50}")

    remove_file(ROOT / f"backend/app/api/{plugin_name}.py")
    remove_file(ROOT / f"bot/cogs/{plugin_name}.py")
    remove_dir(ROOT / f"frontend/app/dashboard/[guildId]/{plugin_name}")
    deregister_router(plugin_name)
    deregister_migration(plugin_name)

    print(f"\n{'=' * 50}")
    if DRY_RUN:
        print("Dry-run complete — no files were modified.")
    else:
        print(f"Plugin '{plugin_name}' removed.")
        print()
        print("  Manual cleanup still required:")
        print(f"    • Remove the '{plugin_name}' namespace from frontend/lib/i18n/translations/en.ts and es.ts")
        print(f"    • Remove the nav card for '{plugin_name}' from frontend/app/page.tsx (if present)")
        print(f"    • Drop any plugin database tables via the DB Management page (if applicable)")
        print(f"    • Restart the backend container for changes to take effect")


if __name__ == "__main__":
    main()
