#!/usr/bin/env python3
"""
plugin_uninstall.py — Removes an installed plugin from the Baseline project.

Reverses every action performed by plugin_install.py:
  - Deletes cog, api, migration, and frontend files
  - Removes the router block from backend/main.py
  - Removes model classes from backend/app/models.py
  - Removes the plugin entry from backend/migration_inventory.json
  - Removes the nav card from frontend/app/page.tsx
  - Removes translation namespaces from en.ts and es.ts

Database tables created by the plugin are NOT dropped automatically.
If the migration was already applied, use the DB Management page to check
status. Drop tables manually if needed before re-installing.

Usage:
    python scripts/plugin_uninstall.py plugins/<plugin_name>
    python scripts/plugin_uninstall.py plugins/<plugin_name> --dry-run
"""

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

DRY_RUN = "--dry-run" in sys.argv
ROOT    = Path(__file__).resolve().parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    prefix = "[DRY-RUN] " if DRY_RUN else ""
    print(f"  {prefix}{msg}")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def remove_file(path: Path):
    log(f"DELETE {_rel(path)}")
    if not DRY_RUN:
        if path.exists():
            path.unlink()
        else:
            print(f"  [SKIP]  {_rel(path)} — not found")


def remove_dir(path: Path):
    log(f"RMDIR  {_rel(path)}")
    if not DRY_RUN:
        if path.exists():
            shutil.rmtree(path)
        else:
            print(f"  [SKIP]  {_rel(path)} — not found")


def patch_file(path: Path, pattern: str, replacement: str, description: str, flags: int = 0) -> bool:
    log(f"PATCH  {_rel(path)} — {description}")
    if DRY_RUN:
        return True
    src = path.read_text()
    new_src = re.sub(pattern, replacement, src, count=1, flags=flags)
    if new_src == src:
        print(f"  [SKIP]  Pattern not found in {path.name} — already removed or never installed")
        return False
    path.write_text(new_src)
    return True


# ── Removal steps ─────────────────────────────────────────────────────────────

def remove_cog(plugin_name: str):
    remove_file(ROOT / f"bot/cogs/{plugin_name}.py")


def remove_api(plugin_name: str):
    remove_file(ROOT / f"backend/app/api/{plugin_name}.py")
    _unpatch_main_py(plugin_name)
    remove_from_installed_plugins(plugin_name)


def _unpatch_main_py(plugin_name: str):
    # The installer prepended this block before the "# Setup wizard" anchor:
    #   \n# Plugin: <name>\n<import line>\n<include line>\n\n
    # Removing it restores main.py to its pre-install state.
    pattern = rf"\n# Plugin: {re.escape(plugin_name)}\n[^\n]+\n[^\n]+\n\n"
    patch_file(
        ROOT / "backend/main.py",
        pattern,
        "",
        f"remove {plugin_name} router block from main.py",
    )


def remove_models(plugin_name: str):
    target = ROOT / "backend/app/models.py"
    marker = f"\n\n# ── Plugin: {plugin_name} "
    log(f"PATCH  backend/app/models.py — remove {plugin_name} model block")
    if DRY_RUN:
        return
    src = target.read_text()
    idx = src.find(marker)
    if idx == -1:
        print(f"  [SKIP]  Plugin model block not found in models.py — already removed or never installed")
        return
    target.write_text(src[:idx])


def remove_migration(plugin_name: str):
    versions_dir = ROOT / "backend/alembic/versions"
    matches = list(versions_dir.glob(f"*_{plugin_name}.py"))
    if not matches:
        print(f"  [SKIP]  No migration file matching *_{plugin_name}.py found")
        return
    for f in matches:
        remove_file(f)


def remove_from_installed_plugins(plugin_name: str):
    registry_path = ROOT / "backend/installed_plugins.json"
    log(f"WRITE  backend/installed_plugins.json — remove {plugin_name} entry")
    if DRY_RUN:
        return
    if not registry_path.exists():
        print(f"  [SKIP]  backend/installed_plugins.json not found")
        return
    plugins = json.loads(registry_path.read_text())
    before = len(plugins)
    plugins = [p for p in plugins if p.get("name") != plugin_name]
    if len(plugins) == before:
        print(f"  [SKIP]  {plugin_name} not found in installed_plugins.json")
    else:
        registry_path.write_text(json.dumps(plugins, indent=2, ensure_ascii=False) + "\n")


def remove_from_inventory(plugin_name: str):
    inventory_path = ROOT / "backend/migration_inventory.json"
    log(f"WRITE  backend/migration_inventory.json — remove {plugin_name} entry")
    if DRY_RUN:
        return
    inventory = json.loads(inventory_path.read_text())
    before = len(inventory.get("plugin_migrations", []))
    inventory["plugin_migrations"] = [
        e for e in inventory.get("plugin_migrations", [])
        if e.get("plugin") != plugin_name
    ]
    if len(inventory["plugin_migrations"]) == before:
        print(f"  [SKIP]  {plugin_name} not found in migration_inventory.json")
    else:
        inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n")


def remove_frontend(plugin_name: str):
    remove_dir(ROOT / f"frontend/app/dashboard/[guildId]/{plugin_name}")


def remove_pages(manifest: dict[str, Any]):
    """Remove frontend pages — handles both single-page (navigation) and multi-page (pages) formats."""
    plugin_name = manifest["name"]
    pages_def = manifest.get("pages")
    if pages_def:
        for page in pages_def:
            install_path = page.get("path", plugin_name)
            remove_dir(ROOT / f"frontend/app/dashboard/[guildId]/{install_path}")
            page_id = page.get("id", plugin_name)
            icon = page.get("navigation", {}).get("icon")
            remove_nav_card(page_id, icon=icon)
    else:
        remove_frontend(plugin_name)
        nav_icon = manifest.get("navigation", {}).get("icon")
        remove_nav_card(plugin_name, icon=nav_icon)


def remove_nav_card(plugin_name: str, icon: str | None = None):
    # The installer inserted the card block before the anchor comment.
    # Pattern matches the card object (opening { through closing },) then
    # captures the anchor so we can keep it.
    pattern = (
        rf"\n    \{{\n      id: '{re.escape(plugin_name)}'.*?    \}},\n"
        rf"    (// Plugins[^\n]*)"
    )
    page_tsx = ROOT / "frontend/app/page.tsx"
    patch_file(
        page_tsx,
        pattern,
        r"\n    \1",
        f"remove {plugin_name} nav card from page.tsx",
        flags=re.DOTALL,
    )

    # Remove the plugin's icon from the lucide-react import if it is no
    # longer referenced anywhere else in the file.
    if icon and not DRY_RUN:
        src = page_tsx.read_text()
        lucide_re = re.compile(r"(import \{)([^}]+)(\} from 'lucide-react';)")
        m = lucide_re.search(src)
        if m:
            imports = [i.strip() for i in m.group(2).split(",") if i.strip()]
            if icon in imports:
                # Check if icon is referenced outside the import line itself
                rest = src[:m.start()] + src[m.end():]
                if not re.search(rf"\b{re.escape(icon)}\b", rest):
                    imports.remove(icon)
                    new_import = f"{m.group(1)} {', '.join(imports)} {m.group(3)}"
                    page_tsx.write_text(src.replace(m.group(0), new_import, 1))
                    log(f"PATCH  frontend/app/page.tsx — remove {icon} from lucide-react imports")


def remove_translations(plugin_name: str):
    for lang in ("en", "es"):
        target = ROOT / f"frontend/lib/i18n/translations/{lang}.ts"
        log(f"PATCH  translations/{lang}.ts — remove {plugin_name} namespace")
        if DRY_RUN:
            continue
        src = target.read_text()
        # The installer injected the block just before the closing brace.
        # en.ts uses `} as const;`, es.ts uses `};` — match both.
        pattern = (
            rf"\n\n  // ── Plugin: {re.escape(plugin_name)}[^\n]*\n"
            rf".*?(?=\n\}}(?: as const)?;)"
        )
        new_src = re.sub(pattern, "", src, count=1, flags=re.DOTALL)
        if new_src == src:
            print(f"  [SKIP]  {plugin_name} namespace not found in translations/{lang}.ts")
        else:
            target.write_text(new_src)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python scripts/plugin_uninstall.py plugins/<plugin_name> [--dry-run]")
        sys.exit(1)

    plugin_dir = Path(args[0])
    if not plugin_dir.is_absolute():
        plugin_dir = ROOT / plugin_dir

    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        print(f"ERROR: plugin.json not found in {plugin_dir}")
        print("The plugin staging folder must still exist to know what to remove.")
        sys.exit(1)

    manifest    = json.loads(manifest_path.read_text())
    plugin_name = manifest["name"]
    components  = manifest.get("components", {})

    print(f"\nUninstalling plugin '{plugin_name}'...\n{'=' * 50}")

    if components.get("cog"):
        remove_cog(plugin_name)

    if components.get("api"):
        remove_api(plugin_name)

    if components.get("models"):
        remove_models(plugin_name)

    if components.get("migration"):
        remove_migration(plugin_name)
        remove_from_inventory(plugin_name)

    if components.get("frontend"):
        remove_pages(manifest)

    if components.get("translations"):
        remove_translations(plugin_name)

    print(f"\n{'=' * 50}")
    if DRY_RUN:
        print("Dry-run complete — no files were modified.")
    else:
        print(f"Plugin '{plugin_name}' removed from project files.")
        if components.get("migration"):
            print(
                "\n  [!]  Database tables are NOT dropped automatically.\n"
                "       If the migration was applied, check the DB Management page.\n"
                "       Drop tables manually before re-installing if needed."
            )


if __name__ == "__main__":
    main()
