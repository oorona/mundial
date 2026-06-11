#!/usr/bin/env python3
"""
plugin_install.py — Installs a validated plugin into the Baseline project.

Runs the validator first. Aborts on any ERROR.

Usage:
    python scripts/plugin_install.py plugins/<plugin_name>
    python scripts/plugin_install.py plugins/<plugin_name> --dry-run
    python scripts/plugin_install.py plugins/<plugin_name> --force   # skip validator
"""

import itertools
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
FORCE = "--force" in sys.argv
ROOT = Path(__file__).resolve().parent.parent

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    prefix = "[DRY-RUN] " if DRY_RUN else ""
    print(f"  {prefix}{msg}")


def copy_file(src: Path, dst: Path):
    log(f"COPY   {_rel(src)} → {_rel(dst)}")
    if not DRY_RUN:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def patch_file(path: Path, old: str, new: str, description: str) -> bool:
    log(f"PATCH  {_rel(path)} — {description}")
    if DRY_RUN:
        return True
    src = path.read_text()
    if old not in src:
        print(f"  [WARN] Patch anchor not found in {path.name} — manual step required")
        return False
    path.write_text(src.replace(old, new, 1))
    return True


def append_to_file(path: Path, content: str, description: str):
    log(f"APPEND {_rel(path)} — {description}")
    if not DRY_RUN:
        with path.open("a") as f:
            f.write(content)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# ── Validation step ───────────────────────────────────────────────────────────

def run_validator(plugin_dir: Path) -> bool:
    if FORCE:
        print("[!] --force: skipping validator\n")
        return True
    print("Running validator...\n")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/plugin_validate.py"), str(plugin_dir)],
    )
    return result.returncode == 0


# ── Install steps ─────────────────────────────────────────────────────────────

def install_cog(plugin_dir: Path, plugin_name: str):
    src = plugin_dir / "cog.py"
    dst = ROOT / f"bot/cogs/{plugin_name}.py"
    copy_file(src, dst)


def install_api(plugin_dir: Path, plugin_name: str, router_prefix: str, router_tag: str, audit_exempt_paths=None):
    src = plugin_dir / "api.py"
    dst = ROOT / f"backend/app/api/{plugin_name}.py"
    copy_file(src, dst)
    _register_plugin_router(plugin_name, router_prefix, router_tag, audit_exempt_paths)


def _register_plugin_router(plugin_name: str, prefix: str, tag: str, audit_exempt_paths=None):
    """Register the plugin in installed_plugins.json.

    main.py auto-discovers routers from this file at startup via plugin_loader.py.
    main.py is never modified by plugin installs — this is the entire registration.

    ``audit_exempt_paths`` (if any) are persisted so the GuildAuditMiddleware can
    skip automatic audit logging for high-frequency mutating routes.
    """
    registry_path = ROOT / "backend/installed_plugins.json"
    log(f"WRITE  backend/installed_plugins.json — register {plugin_name} router")

    if DRY_RUN:
        return

    plugins: list[dict] = []
    if registry_path.exists():
        try:
            plugins = json.loads(registry_path.read_text())
        except Exception:
            plugins = []

    # Replace any existing entry for this plugin (re-install scenario)
    plugins = [p for p in plugins if p.get("name") != plugin_name]
    entry = {"name": plugin_name, "prefix": prefix, "tag": tag}
    if audit_exempt_paths:
        entry["audit_exempt_paths"] = audit_exempt_paths
    plugins.append(entry)

    registry_path.write_text(json.dumps(plugins, indent=2, ensure_ascii=False) + "\n")


def install_models(plugin_dir: Path, plugin_name: str):
    src = plugin_dir / "models.py"
    target = ROOT / "backend/app/models.py"
    content = src.read_text().strip()

    # Keep all content including imports. Aliased imports (import X as Y) and
    # imports of plugin-specific names must not be stripped — doing so breaks
    # any code that references those names. Python handles duplicate imports fine.
    separator = f"\n\n# ── Plugin: {plugin_name} {'─' * max(0, 40 - len(plugin_name))}\n"
    append_to_file(target, separator + content + "\n", f"append {plugin_name} models")


def install_migration(plugin_dir: Path, plugin_name: str):
    src = plugin_dir / "migration.py"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = ROOT / f"backend/alembic/versions/{ts}_{plugin_name}.py"
    copy_file(src, dst)
    if not DRY_RUN:
        _patch_migration_branch(dst, plugin_name)
    _register_plugin_in_inventory(src, plugin_name, plugin_dir)


def _patch_migration_branch(migration_path: Path, plugin_name: str):
    """Convert a plugin migration to an independent Alembic branch.

    Plugin migrations must NOT chain off the framework — they create their own
    tables and have no dependency on the framework's migration chain.  Setting
    down_revision = None and assigning a branch label keeps plugin and framework
    branches completely separate.  `alembic upgrade <revision>` works for both;
    `alembic upgrade heads` applies all branches at once.
    """
    src = migration_path.read_text()

    # Set down_revision = None (remove any link to the framework chain)
    src = re.sub(
        r"(down_revision\s*(?::\s*\S+\s*)?)=\s*(?:None|['\"][^'\"]*['\"])",
        r"\1= None",
        src, count=1,
    )

    # Set branch_labels to the plugin's named branch
    branch_value = f"['{plugin_name}']"
    if re.search(r"branch_labels\s*=", src):
        src = re.sub(
            r"branch_labels\s*=\s*(?:None|\[.*?\])",
            f"branch_labels = {branch_value}",
            src, count=1,
        )
    else:
        # Insert after the revision line
        src = re.sub(
            r"(revision\s*(?::\s*\S+\s*)?=\s*['\"][^'\"]+['\"])",
            f"\\1\nbranch_labels = {branch_value}",
            src, count=1,
        )

    migration_path.write_text(src)
    log(f"PATCH  {_rel(migration_path)} — set independent branch (down_revision=None, branch_labels={branch_value})")


def _register_plugin_in_inventory(migration_src: Path, plugin_name: str, plugin_dir: Path):
    """Write the plugin migration entry into backend/migration_inventory.json."""
    import re as _re

    # Extract revision ID from the migration file
    migration_text = migration_src.read_text()
    m = _re.search(r"^revision(?:\s*:\s*str)?\s*=\s*['\"]([a-f0-9]+)['\"]", migration_text, _re.MULTILINE)
    if not m:
        print(f"  [WARN] Could not find revision ID in migration.py — add to migration_inventory.json manually")
        return

    revision_id    = m.group(1)
    plugin_version = plugin_dir and json.loads((plugin_dir / "plugin.json").read_text()).get("version", "1.0.0")
    description    = plugin_dir and json.loads((plugin_dir / "plugin.json").read_text()).get("description", f"{plugin_name} plugin tables")

    inventory_path = ROOT / "backend/migration_inventory.json"
    log(f"WRITE  backend/migration_inventory.json — register {plugin_name} plugin migration")

    if DRY_RUN:
        return

    inventory = json.loads(inventory_path.read_text())

    # Replace any existing entry for this plugin (re-install scenario)
    inventory["plugin_migrations"] = [
        e for e in inventory.get("plugin_migrations", [])
        if e.get("plugin") != plugin_name
    ]
    inventory["plugin_migrations"].append({
        "plugin":        plugin_name,
        "version":       plugin_version,
        "description":   description,
        "revisions":     [revision_id],
        "head_revision": revision_id,
    })

    inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n")


def install_frontend(plugin_dir: Path, plugin_name: str):
    src = plugin_dir / "page.tsx"
    dst = ROOT / f"frontend/app/dashboard/[guildId]/{plugin_name}/page.tsx"
    copy_file(src, dst)


def install_nav_card(manifest: dict):
    """Single-page (legacy) nav card insertion — used when plugin.json has no 'pages' array."""
    nav = manifest.get("navigation", {})
    if not nav.get("enabled", False):
        return
    plugin_name = manifest["name"]
    perm = manifest.get("permission_level", 3)
    _insert_nav_card(
        card_id=plugin_name,
        install_path=plugin_name,
        perm=perm,
        nav=nav,
    )


def install_pages(plugin_dir: Path, manifest: dict):
    """Install frontend pages — handles both single-page (navigation) and multi-page (pages) formats.

    Single-page (legacy):  plugin.json has a top-level "navigation" object.
    Multi-page:            plugin.json has a "pages" array where each entry describes
                           one page file, its install path, permission level, and nav card.
    """
    pages_def = manifest.get("pages")
    if pages_def:
        for page in pages_def:
            source_name = page.get("source", "page.tsx")
            src = plugin_dir / source_name
            if not src.exists():
                print(f"  [SKIP]  {source_name} not found — skipping page '{page.get('id', '?')}'")
                continue
            install_path = page.get("path", manifest["name"])
            dst = ROOT / f"frontend/app/dashboard/[guildId]/{install_path}/page.tsx"
            copy_file(src, dst)

            nav = page.get("navigation", {})
            if nav.get("enabled", True):
                page_id = page.get("id", manifest["name"])
                perm = page.get("permission_level", manifest.get("permission_level", 3))
                _insert_nav_card(
                    card_id=page_id,
                    install_path=install_path,
                    perm=perm,
                    nav=nav,
                )
    else:
        # Legacy single-page format
        install_frontend(plugin_dir, manifest["name"])
        install_nav_card(manifest)


def install_activity_pages(plugin_dir: Path, manifest: dict):
    """Install Discord Activity pages into the /activity route group (Gap A).

    Each activity_pages entry copies its source to
    frontend/app/activity/<path>/page.tsx — outside dashboard/, no withPermission,
    served full-bleed with the frame-ancestors CSP from next.config.
    """
    for page in manifest.get("activity_pages", []) or []:
        source_name = page.get("source")
        if not source_name:
            continue
        src = plugin_dir / source_name
        if not src.exists():
            print(f"  [SKIP]  {source_name} not found — skipping activity page")
            continue
        install_path = page.get("path", manifest["name"])
        dst = ROOT / f"frontend/app/activity/{install_path}/page.tsx"
        copy_file(src, dst)


def install_public_pages(plugin_dir: Path, manifest: dict):
    """Install public per-server site pages into the (public) route group.

    Each public_pages entry copies its source to
    frontend/app/(public)/p/[slug]/<path>/page.tsx — Level 0, no login, served
    under the configurable public prefix (default /p/<slug>/<path>).
    """
    for page in manifest.get("public_pages", []) or []:
        source_name = page.get("source")
        if not source_name:
            continue
        src = plugin_dir / source_name
        if not src.exists():
            print(f"  [SKIP]  {source_name} not found — skipping public page")
            continue
        install_path = page.get("path", manifest["name"])
        dst = ROOT / f"frontend/app/(public)/p/[slug]/{install_path}/page.tsx"
        copy_file(src, dst)


def _insert_nav_card(card_id: str, install_path: str, perm: int, nav: dict):
    """Shared logic: patch page.tsx anchor with one nav card entry and ensure icon is imported."""
    perm_names = {
        0: "PUBLIC", 1: "PUBLIC_DATA", 2: "USER",
        3: "AUTHORIZED", 4: "OWNER", 5: "DEVELOPER",
    }
    perm_name = perm_names.get(perm, str(perm))
    is_admin = perm >= 4
    camel = _to_camel_case(card_id)
    icon = nav.get("icon", "Settings")
    color = nav.get("color", "text-blue-500")
    bg = nav.get("bg_color", "bg-blue-500/10")
    border = nav.get("border_color", "group-hover:border-blue-500/50")

    card_block = (
        f"    {{\n"
        f"      id: '{card_id}',\n"
        f"      title: t('{camel}.title'),\n"
        f"      description: t('{camel}.description'),\n"
        f"      icon: {icon},\n"
        f"      href: `/dashboard/${{activeGuildId}}/{install_path}`,\n"
        f"      level: PermissionLevel.{perm_name},\n"
        f"      color: '{color}',\n"
        f"      bgColor: '{bg}',\n"
        f"      borderColor: '{border}',\n"
        f"      isAdminOnly: {'true' if is_admin else 'false'},\n"
        f"    }},\n"
        f"    // Plugins — titles come from plugin definitions; descriptions are translated"
    )

    page_tsx = ROOT / "frontend/app/page.tsx"
    anchor = "    // Plugins — titles come from plugin definitions; descriptions are translated"
    patched = patch_file(page_tsx, anchor, card_block, f"insert nav card for {card_id}")
    if not patched:
        print(
            f"  [!]  Could not auto-insert nav card — add manually to frontend/app/page.tsx:\n"
            f"       icon import: import {{ {icon} }} from 'lucide-react'\n"
            f"       card: {card_block.split(chr(10))[0].strip()} ..."
        )
        return

    # Ensure the icon is imported from lucide-react
    if not DRY_RUN:
        src = page_tsx.read_text()
        lucide_re = re.compile(r"(import \{)([^}]+)(\} from 'lucide-react';)")
        m = lucide_re.search(src)
        if m:
            imports = [i.strip() for i in m.group(2).split(",") if i.strip()]
            if icon not in imports:
                imports_sorted = sorted(imports + [icon])
                new_import = f"{m.group(1)} {', '.join(imports_sorted)} {m.group(3)}"
                page_tsx.write_text(src.replace(m.group(0), new_import, 1))
                log(f"PATCH  frontend/app/page.tsx — add {icon} to lucide-react imports")


def install_prompts(plugin_dir: Path, plugin_name: str, manifest: dict):
    """Install plugin prompt files into the shared data volume.

    Layout after install:
      data/prompts/{plugin_name}/
        manifest.json                 ← context + file metadata for the framework
        {context_name}/
          system_prompt.txt           ← copied from plugins/{name}/prompts/{context}/
          user_prompt.txt             ← or written from the "default" string in plugin.json

    Each entry in the plugin.json "prompts" array represents one context folder.
    Existing .txt files are preserved (user edits are never overwritten on re-install).
    """
    contexts = manifest.get("prompts", [])
    if not contexts:
        print(f"  [WARN]  components.prompts = true but 'prompts' array is empty in plugin.json — nothing to install")
        return

    dest_plugin_dir = ROOT / "data" / "prompts" / plugin_name
    manifest_out = {
        "plugin_name": plugin_name,
        "display_name": manifest.get("display_name", plugin_name),
        "contexts": contexts,
    }

    log(f"WRITE  data/prompts/{plugin_name}/manifest.json — {len(contexts)} context(s)")
    if not DRY_RUN:
        dest_plugin_dir.mkdir(parents=True, exist_ok=True)
        (dest_plugin_dir / "manifest.json").write_text(
            json.dumps(manifest_out, indent=2, ensure_ascii=False) + "\n"
        )

    for ctx in contexts:
        ctx_name = ctx.get("context")
        if not ctx_name:
            print(f"  [WARN]  Prompt context entry missing 'context' key — skipped: {ctx}")
            continue

        dest_ctx_dir = dest_plugin_dir / ctx_name

        for file_entry in ctx.get("files", []):
            file_name = file_entry.get("name")
            if not file_name:
                print(f"  [WARN]  File entry in context '{ctx_name}' missing 'name' — skipped")
                continue

            dest_file = dest_ctx_dir / f"{file_name}.txt"

            if dest_file.exists() and not DRY_RUN:
                log(f"SKIP   data/prompts/{plugin_name}/{ctx_name}/{file_name}.txt — already exists (preserved)")
                continue

            src_file = plugin_dir / "prompts" / ctx_name / f"{file_name}.txt"
            if src_file.exists():
                copy_file(src_file, dest_file)
            else:
                # No source file — write the inline "default" string
                default_content = file_entry.get("default", "")
                log(f"WRITE  data/prompts/{plugin_name}/{ctx_name}/{file_name}.txt — from plugin.json default")
                if not DRY_RUN:
                    dest_ctx_dir.mkdir(parents=True, exist_ok=True)
                    dest_file.write_text(default_content)


def install_translations(plugin_dir: Path, plugin_name: str):
    marker = f"// ── Plugin: {plugin_name}"
    pending: list[tuple[Path, str]] = []  # (dst, patched_content) — built before any write

    for lang in ("en", "es"):
        src = plugin_dir / "translations" / f"{lang}.ts"
        if not src.exists():
            print(f"  [ERROR] translations/{lang}.ts not found in plugin — both en.ts and es.ts are required.")
            print(f"         Install aborted. Fix the plugin and re-run.")
            sys.exit(1)

        dst = ROOT / f"frontend/lib/i18n/translations/{lang}.ts"
        # Strip leading comment lines — they are guidance for the plugin developer,
        # not content that belongs in the project's translation files.
        raw_lines = src.read_text().strip().splitlines()
        code_lines = list(itertools.dropwhile(lambda l: l.strip().startswith("//"), raw_lines))
        snippet = "\n".join(code_lines).strip()
        log(f"MERGE  translations/{lang}.ts ← {plugin_name} namespace")

        if DRY_RUN:
            continue

        target_src = dst.read_text()

        if marker in target_src:
            print(f"  [SKIP] {lang}.ts already contains plugin namespace — remove manually to re-inject")
            continue

        injected = (
            f"\n\n  {marker} {'─' * max(0, 38 - len(plugin_name))}\n"
            f"  {snippet.rstrip(',')},\n"
        )
        # Match the final closing brace — en.ts uses `} as const;`, es.ts uses `};`
        closing = re.compile(r"\n\}( as const)?;")
        last_match = None
        for last_match in closing.finditer(target_src):
            pass
        if last_match is None:
            print(f"  [ERROR] Could not find closing '}}' anchor in {lang}.ts — merge failed.")
            print(f"         Install aborted. No files were written. Check the translation file structure.")
            sys.exit(1)
        suffix = last_match.group(1) or ""
        patched = (
            target_src[:last_match.start()]
            + injected
            + f"\n}}{suffix};"
            + target_src[last_match.end():]
        )

        pending.append((dst, patched))

    # All languages validated — now write atomically
    for dst, patched in pending:
        dst.write_text(patched)


# ── Post-install guidance ─────────────────────────────────────────────────────

def print_manual_steps(manifest: dict, components: dict):
    if components.get("migration"):
        print("\n  [!]  Plugin migration registered. After restarting services, open the")
        print("       DB Management page and apply the plugin migration from there.")


def _to_camel_case(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python scripts/plugin_install.py plugins/<plugin_name> [--dry-run] [--force]")
        sys.exit(1)

    plugin_dir = Path(args[0])
    if not plugin_dir.is_absolute():
        plugin_dir = ROOT / plugin_dir

    if not plugin_dir.is_dir():
        print(f"ERROR: '{plugin_dir}' is not a directory")
        sys.exit(1)

    if not run_validator(plugin_dir):
        print("\nInstall aborted — fix validation errors first.")
        sys.exit(1)

    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        print("ERROR: plugin.json not found")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    plugin_name = manifest["name"]
    components = manifest.get("components", {})
    router_cfg = manifest.get("router", {})
    router_prefix = router_cfg.get("prefix", "/guilds")
    router_tag = router_cfg.get("tag", plugin_name)
    router_audit_exempt = router_cfg.get("audit_exempt_paths", [])

    print(f"\nInstalling plugin '{plugin_name}'...\n{'=' * 50}")

    if components.get("cog") and (plugin_dir / "cog.py").exists():
        install_cog(plugin_dir, plugin_name)

    if components.get("api") and (plugin_dir / "api.py").exists():
        install_api(plugin_dir, plugin_name, router_prefix, router_tag, router_audit_exempt)

    if components.get("models") and (plugin_dir / "models.py").exists():
        install_models(plugin_dir, plugin_name)

    if components.get("migration") and (plugin_dir / "migration.py").exists():
        install_migration(plugin_dir, plugin_name)

    if components.get("frontend"):
        install_pages(plugin_dir, manifest)
        install_activity_pages(plugin_dir, manifest)
        install_public_pages(plugin_dir, manifest)

    if components.get("translations") and (plugin_dir / "translations").is_dir():
        install_translations(plugin_dir, plugin_name)

    if components.get("prompts"):
        install_prompts(plugin_dir, plugin_name, manifest)

    print(f"\n{'=' * 50}")
    if DRY_RUN:
        print("Dry-run complete — no files were modified.")
    else:
        print(f"Plugin '{plugin_name}' installed successfully.")
        print_manual_steps(manifest, components)


if __name__ == "__main__":
    main()
