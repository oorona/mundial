#!/usr/bin/env python3
"""
plugin_validate.py — Validates a staged plugin against all Baseline framework contracts.

Usage:
    python scripts/plugin_validate.py plugins/<plugin_name>
    python scripts/plugin_validate.py plugins/<plugin_name> --strict

Exit codes:
    0 — validation passed (ready to install)
    1 — one or more ERRORs (must fix before install)
"""

import ast
import json
import re
import sys
from pathlib import Path

ERRORS: list[str] = []
WARNINGS: list[str] = []
STRICT = "--strict" in sys.argv


def err(msg: str):
    ERRORS.append(f"  [ERROR] {msg}")


def warn(msg: str):
    if STRICT:
        ERRORS.append(f"  [ERROR] {msg}  (--strict)")
    else:
        WARNINGS.append(f"  [WARN]  {msg}")


def ok(msg: str):
    print(f"  [OK]    {msg}")


# ── Manifest ─────────────────────────────────────────────────────────────────

def validate_manifest(plugin_dir: Path) -> dict:
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        err("plugin.json not found — every plugin must have a manifest")
        return {}

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        err(f"plugin.json is not valid JSON: {e}")
        return {}

    for field in ("name", "version", "description", "components"):
        if field not in manifest:
            err(f"plugin.json missing required field: '{field}'")

    if "display_name" not in manifest:
        warn("plugin.json missing 'display_name' — used in UI and docs")

    name = manifest.get("name", "")
    if name and not re.match(r"^[a-z][a-z0-9_]*$", name):
        err(f"plugin name '{name}' must be snake_case lowercase (e.g. my_plugin)")

    # Folder name must match the declared name
    if name and plugin_dir.name != name:
        err(
            f"Plugin folder name '{plugin_dir.name}' does not match "
            f"plugin.json 'name' field '{name}' — they must be identical"
        )
    elif name:
        ok(f"Folder name matches plugin name: '{name}'")

    # Version must be semver (MAJOR.MINOR.PATCH)
    version = manifest.get("version", "")
    if version and not re.match(r"^\d+\.\d+\.\d+$", version):
        err(
            f"version '{version}' is not valid semver — use MAJOR.MINOR.PATCH format (e.g. 1.0.0)"
        )
    elif version:
        ok(f"Version: {version}")

    perm = manifest.get("permission_level")
    if perm is not None and perm not in range(6):
        err(f"permission_level must be 0–5, got {perm}")
    elif perm is None:
        warn("permission_level not set — defaults to 3 (AUTHORIZED) at install time")

    # Navigation / pages section consistency
    pages_def = manifest.get("pages")
    nav = manifest.get("navigation", {})
    if pages_def is not None:
        if not isinstance(pages_def, list) or len(pages_def) == 0:
            err("'pages' must be a non-empty list of page definition objects")
        else:
            if not manifest.get("components", {}).get("frontend"):
                err("'pages' declared but 'frontend' component is not set to true")
            for i, page in enumerate(pages_def):
                pid = page.get("id", f"<index {i}>")
                if not page.get("id"):
                    err(f"pages[{i}] missing required 'id' field")
                if not page.get("source"):
                    err(f"pages[{i}] (id='{pid}') missing required 'source' field (e.g. 'page.tsx')")
                if not page.get("path"):
                    err(f"pages[{i}] (id='{pid}') missing required 'path' field (install path under dashboard/[guildId]/)")
                perm = page.get("permission_level")
                if perm is None:
                    warn(f"pages[{i}] (id='{pid}') has no permission_level — defaults to plugin-level permission_level")
                elif perm not in range(6):
                    err(f"pages[{i}] (id='{pid}') permission_level must be 0–5, got {perm}")
                page_nav = page.get("navigation", {})
                if page_nav.get("enabled", True) and not page_nav.get("icon"):
                    warn(f"pages[{i}] (id='{pid}') navigation.icon not set — installer will default to 'Settings'")
    elif nav.get("enabled"):
        if not manifest.get("components", {}).get("frontend"):
            err("navigation.enabled is true but 'frontend' component is not declared")
        if not nav.get("icon"):
            warn("navigation.icon not set — installer will default to 'Settings'")
        if manifest.get("permission_level") is None:
            warn("navigation.enabled requires permission_level to be set for the dashboard card")

    # Router section consistency
    if manifest.get("components", {}).get("api") and "router" not in manifest:
        warn("'api' component declared but no 'router' section in plugin.json — installer defaults to prefix='/guilds'")

    # Activity / public page groups (Gap A + public site surface).
    # Same shape as 'pages' (source + path) but installed into different route
    # groups: activity_pages → app/activity/<path>, public_pages → app/(public)/p/[slug]/<path>.
    for group_key in ("activity_pages", "public_pages"):
        group = manifest.get(group_key)
        if group is None:
            continue
        if not isinstance(group, list) or len(group) == 0:
            err(f"'{group_key}' must be a non-empty list of page objects")
            continue
        if not manifest.get("components", {}).get("frontend"):
            err(f"'{group_key}' declared but 'frontend' component is not set to true")
        for i, page in enumerate(group):
            if not page.get("source"):
                err(f"{group_key}[{i}] missing required 'source' field (e.g. 'activity.tsx')")
            if not page.get("path"):
                err(f"{group_key}[{i}] missing required 'path' field (install path segment)")

    # Worker flag (Gap D) — declares the plugin runs a tasks.loop worker cog
    # that uses bot.services.db.
    if "worker" in manifest and not isinstance(manifest["worker"], bool):
        err("'worker' must be a boolean")

    # Capabilities hint (documentation only, e.g. ["sse"]).
    if "capabilities" in manifest and not isinstance(manifest["capabilities"], list):
        err("'capabilities' must be a list of strings (e.g. [\"sse\"])")

    # Audit-exempt paths (Gap C) — high-frequency mutating routes excluded from
    # automatic audit logging.
    router_section = manifest.get("router", {})
    aep = router_section.get("audit_exempt_paths") if isinstance(router_section, dict) else None
    if aep is not None:
        if not isinstance(aep, list) or not all(isinstance(x, str) for x in aep):
            err("router.audit_exempt_paths must be a list of route-path strings (e.g. [\"/{guild_id}/place\"])")
        else:
            ok(f"router.audit_exempt_paths declared: {aep}")

    valid_components = {"cog", "api", "models", "migration", "frontend", "translations", "prompts"}
    for key in manifest.get("components", {}):
        if key not in valid_components:
            warn(f"Unknown component key '{key}' in plugin.json — valid: {valid_components}")

    # Prompts section consistency
    if manifest.get("components", {}).get("prompts"):
        _validate_prompts(manifest, plugin_dir)

    ok("plugin.json is valid")
    return manifest


# File names that are valid within a context folder.
# The CONTEXT folder encodes PURPOSE (e.g. "ticket_intake").
# The FILE NAME encodes ROLE in the LLM call.
# Do NOT put purpose in the file name (wrong: "agent_system", "welcome", "ticket_user").
_VALID_FILE_NAMES = {"system_prompt", "user_prompt", "assistant_prompt", "injection", "context"}


def _validate_prompts(manifest: dict, plugin_dir: Path):
    """Validate the 'prompts' array in plugin.json when components.prompts = true.

    Each entry in "prompts" is a context — a named purpose folder such as
    "ticket_intake" or "faq_answers". Each context contains a "files" list
    whose names must come from _VALID_FILE_NAMES (system_prompt, user_prompt, …).

    Common mistake: encoding purpose in the file name instead of the folder.
      WRONG: files named "agent_system", "welcome", "injection_user" (flat, descriptive)
      RIGHT: context="ticket_agent" with files named "system_prompt", "user_prompt"
    """
    contexts = manifest.get("prompts")
    if not isinstance(contexts, list) or len(contexts) == 0:
        err("components.prompts = true but 'prompts' array is missing or empty in plugin.json")
        return

    seen_contexts: set[str] = set()
    for i, ctx in enumerate(contexts):
        ctx_name = ctx.get("context", f"<index {i}>")

        if not ctx.get("context"):
            err(f"prompts[{i}] missing required 'context' field (the folder name, e.g. 'ticket_intake')")
        elif not re.match(r"^[a-z][a-z0-9_]*$", ctx["context"]):
            err(f"prompts[{i}] context '{ctx['context']}' must be snake_case lowercase (e.g. 'ticket_intake')")
        elif ctx["context"] in seen_contexts:
            err(f"prompts[{i}] duplicate context name '{ctx['context']}'")
        else:
            seen_contexts.add(ctx["context"])

        if not ctx.get("label"):
            warn(f"prompts[{i}] (context='{ctx_name}') missing 'label' — will display raw context name in dashboard")

        files = ctx.get("files", [])
        if not isinstance(files, list) or len(files) == 0:
            err(f"prompts[{i}] (context='{ctx_name}') 'files' must be a non-empty list")
            continue

        seen_file_names: set[str] = set()
        for j, file_entry in enumerate(files):
            fname = file_entry.get("name", f"<index {j}>")

            if not file_entry.get("name"):
                err(f"prompts[{i}].files[{j}] missing required 'name' field")
                continue
            if not re.match(r"^[a-z][a-z0-9_]*$", file_entry["name"]):
                err(f"prompts[{i}].files[{j}] name '{file_entry['name']}' must be snake_case lowercase")
            elif file_entry["name"] not in _VALID_FILE_NAMES:
                err(
                    f"prompts[{i}].files[{j}] invalid file name '{file_entry['name']}' — "
                    f"must be one of: {sorted(_VALID_FILE_NAMES)}. "
                    f"The context folder ('{ctx_name}') is where purpose goes; "
                    f"the file name is the role in the LLM call. "
                    f"Wrong: 'agent_system', 'welcome', 'ticket_user'. "
                    f"Right: context='ticket_agent', file='system_prompt'."
                )
            elif file_entry["name"] in seen_file_names:
                err(f"prompts[{i}].files[{j}] duplicate file name '{file_entry['name']}' in context '{ctx_name}'")
            else:
                seen_file_names.add(file_entry["name"])

            if not file_entry.get("label"):
                warn(f"prompts[{i}].files[{j}] (name='{fname}') missing 'label'")

            # Check that a source .txt or inline "default" string is available
            src_txt = plugin_dir / "prompts" / ctx.get("context", "") / f"{file_entry.get('name', '')}.txt"
            has_default_str = "default" in file_entry and isinstance(file_entry["default"], str)

            if not src_txt.exists() and not has_default_str:
                warn(
                    f"prompts[{i}].files[{j}] (context='{ctx_name}', name='{fname}') "
                    f"has no prompts/{ctx.get('context', '?')}/{fname}.txt "
                    f"and no 'default' string — file will be created empty at install time"
                )
            elif src_txt.exists():
                ok(f"prompts[{i}].files[{j}] context='{ctx_name}' name='{fname}' — source file found")
            else:
                ok(f"prompts[{i}].files[{j}] context='{ctx_name}' name='{fname}' — default string in plugin.json")


# ── Cog ──────────────────────────────────────────────────────────────────────

def validate_cog(cog_path: Path, is_worker: bool = False):
    print("\n[cog.py]")
    src = cog_path.read_text()

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        err(f"Syntax error in cog.py: {e}")
        return

    # Must inherit from commands.Cog
    cog_classes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(b, ast.Attribute) and b.attr == "Cog")
            or (isinstance(b, ast.Name) and b.id == "Cog")
            for b in node.bases
        )
    ]
    if not cog_classes:
        err("No class inheriting from commands.Cog found")
    else:
        ok(f"Cog class(es): {', '.join(c.name for c in cog_classes)}")

    # Every cog must describe its purpose. discord.py exposes the class docstring
    # as ``cog.description``; the web Cog Manager (Developer section) shows it next
    # to each loaded cog. Accept a class docstring or a ``description`` /
    # ``COG_DESCRIPTION`` class attribute.
    for c in cog_classes:
        has_doc = bool(ast.get_docstring(c))
        has_attr = any(
            isinstance(stmt, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id in ("description", "COG_DESCRIPTION")
                for t in stmt.targets
            )
            for stmt in c.body
        )
        if has_doc or has_attr:
            ok(f"Cog '{c.name}' has a description")
        else:
            err(
                f"Cog '{c.name}' has no description — add a one-line class docstring "
                f"(shown in the web Cog Manager) or a `description` class attribute"
            )

    # Every @app_commands.command() must have description=
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if _is_app_command(dec):
                    if not _decorator_has_kwarg(dec, "description"):
                        err(
                            f"@app_commands.command '{node.name}' (line {node.lineno}) "
                            f"is missing description= argument"
                        )
                    else:
                        ok(f"@app_commands.command '{node.name}' has description=")

    # Forbidden: direct LLM/HTTP client instantiation
    forbidden = [
        (r"openai\.OpenAI\s*\(", "Direct openai.OpenAI() — use bot.services.llm"),
        (r"anthropic\.Anthropic\s*\(", "Direct anthropic.Anthropic() — use bot.services.llm"),
        (r"genai\.configure\s*\(", "Direct google.generativeai — use bot.services.llm"),
        (r"aiohttp\.ClientSession\s*\(", "Direct aiohttp.ClientSession() — use bot.session"),
    ]
    for pattern, msg in forbidden:
        if re.search(pattern, src):
            err(msg)

    # LLM access pattern
    if re.search(r"\bbot\.llm_service\b|\bbot\.llm\b", src):
        err("LLM accessed as 'bot.llm_service' or 'bot.llm' — must be 'bot.services.llm'")
    if re.search(r"bot\.services\.llm", src):
        ok("LLM accessed via bot.services.llm")

    # Worker cogs (Gap D): direct DB access via bot.services.db is sanctioned
    # for tasks.loop jobs. The bot is a single-writer AutoShardedBot process.
    if re.search(r"\bservices\.db\b", src):
        if is_worker:
            ok("Worker DB session used via bot.services.db (manifest 'worker': true)")
        else:
            warn(
                "Cog uses bot.services.db but manifest 'worker' flag is not set — "
                "declare \"worker\": true so the DB access is explicit and intentional"
            )

    # SETTINGS_SCHEMA required if cog reads settings
    reads_settings = bool(re.search(r"guild_settings|get_settings|settings\.get\b", src))
    if reads_settings and "SETTINGS_SCHEMA" not in src:
        warn(
            "Cog appears to read guild settings but has no SETTINGS_SCHEMA — "
            "the dashboard Settings page won't render a form for it"
        )
    elif "SETTINGS_SCHEMA" in src:
        ok("SETTINGS_SCHEMA declared")
        _validate_settings_schema_in_cog(tree)

    # setup() entrypoint
    if "async def setup(" not in src:
        warn("No async def setup(bot) found — discord.py requires this to load the cog")
    else:
        ok("setup() entrypoint present")


def _is_app_command(decorator) -> bool:
    if isinstance(decorator, ast.Call):
        func = decorator.func
        if isinstance(func, ast.Attribute) and func.attr == "command":
            val = func.value
            if isinstance(val, ast.Attribute) and val.attr == "app_commands":
                return True
            if isinstance(val, ast.Name) and val.id == "app_commands":
                return True
    return False


def _decorator_has_kwarg(decorator, kwarg: str) -> bool:
    if isinstance(decorator, ast.Call):
        return any(kw.arg == kwarg for kw in decorator.keywords)
    return False


_VALID_FIELD_TYPES = {
    "boolean", "channel_select", "role_select", "multiselect", "text", "number",
    # Rich settings (Gap E): single hex color, ordered N-color palette,
    # single-choice enum. Extra keys (min/max/step/options/count) are allowed.
    "color", "color_list", "select",
}


def _validate_settings_schema_in_cog(tree: ast.AST):
    """Validate SETTINGS_SCHEMA structure and field types via AST."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Name) and t.id == "SETTINGS_SCHEMA"]
        if not targets:
            continue

        schema = node.value
        if not isinstance(schema, ast.Dict):
            warn("SETTINGS_SCHEMA is not a dict literal — cannot validate structure")
            return

        top_keys = {
            k.value for k in schema.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }

        for required in ("id", "label", "fields"):
            if required not in top_keys:
                err(
                    f"SETTINGS_SCHEMA missing required key '{required}' — "
                    "structure must be: {\"id\": \"...\", \"label\": \"...\", \"fields\": [...]}"
                )

        # Validate field types
        for key, value in zip(schema.keys, schema.values):
            if not (isinstance(key, ast.Constant) and key.value == "fields"):
                continue
            if not isinstance(value, ast.List):
                warn("SETTINGS_SCHEMA 'fields' should be a list of dicts")
                continue
            for item in value.elts:
                if not isinstance(item, ast.Dict):
                    continue
                for fk, fv in zip(item.keys, item.values):
                    if not (isinstance(fk, ast.Constant) and fk.value == "type"):
                        continue
                    if isinstance(fv, ast.Constant) and isinstance(fv.value, str):
                        ftype = fv.value
                        if ftype not in _VALID_FIELD_TYPES:
                            err(
                                f"SETTINGS_SCHEMA field type '{ftype}' is invalid. "
                                f"Valid types: {', '.join(sorted(_VALID_FIELD_TYPES))}"
                            )
        return  # only validate the first SETTINGS_SCHEMA found


# ── API Router ────────────────────────────────────────────────────────────────

def _is_audit_exempt(route_path: str, exempt_paths: list, router_prefix: str) -> bool:
    """A mutation route is audit-exempt when it is mounted outside /guilds/{id}/
    (the audit middleware never matches it) or its path matches a declared
    router.audit_exempt_paths prefix. Both sides use the literal {param} text,
    so a prefix comparison is exact."""
    if not router_prefix.startswith("/guilds"):
        return True
    for ep in (exempt_paths or []):
        if route_path == ep or route_path.startswith(ep.rstrip("/") + "/"):
            return True
    return False


def validate_api(api_path: Path, exempt_paths: list = None, router_prefix: str = "/guilds"):
    print("\n[api.py]")
    src = api_path.read_text()

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        err(f"Syntax error in api.py: {e}")
        return

    # router = APIRouter() must exist
    if not re.search(r"\brouter\s*=\s*APIRouter\s*\(", src):
        err("No 'router = APIRouter()' found")
    else:
        ok("APIRouter instance defined")

    # Guild-scoped routes must use get_guild_db
    guild_route_re = re.compile(
        r'@router\.(get|post|put|patch|delete)\s*\(\s*["\'][^"\']*\{guild_id\}'
    )
    guild_routes = guild_route_re.findall(src)
    if guild_routes:
        if "get_guild_db" not in src:
            err(
                f"Found {len(guild_routes)} guild-scoped route(s) containing {{guild_id}} "
                f"but 'get_guild_db' is not used — this bypasses Row-Level Security"
            )
        else:
            if "from app.db.guild_session import" not in src:
                warn("get_guild_db appears to be used but not imported from app.db.guild_session")
            ok(f"{len(guild_routes)} guild-scoped route(s) use get_guild_db")
    else:
        ok("No guild-scoped routes detected")

    # Mutation endpoints must reference AuditLog (the marker that acknowledges
    # automatic audit coverage) — UNLESS the route is audit-exempt: declared in
    # router.audit_exempt_paths, or mounted outside /guilds/{id}/ where the
    # GuildAuditMiddleware never matches. The exemption is explicit, not silent.
    mutation_fns = _find_mutation_functions(tree)
    for fn_name, start_line, route_path in mutation_fns:
        fn_src = _function_source(src, start_line) or ""

        # Auth check: a guild-scoped mutation must authenticate the caller.
        # get_guild_db only sets RLS scope — it does NOT authenticate, and
        # audit-exempt does NOT mean auth-exempt. Public {slug} routes (served
        # via get_public_guild_db) are intentionally unauthenticated → excluded.
        if "{guild_id}" in route_path and not re.search(r"get_current_user|get_activity_user", fn_src):
            warn(
                f"Mutation endpoint '{fn_name}' (line {start_line}) on a /{{guild_id}}/ route has no "
                f"auth dependency — add Depends(get_current_user) or Depends(get_activity_user). "
                f"get_guild_db only scopes RLS; it does not authenticate the caller"
            )

        if _is_audit_exempt(route_path, exempt_paths, router_prefix):
            ok(f"Mutation endpoint '{fn_name}' is audit-exempt ('{route_path}') — AuditLog not required")
            continue
        if "AuditLog" not in fn_src:
            err(
                f"Mutation endpoint '{fn_name}' (line {start_line}) has no AuditLog reference — "
                f"audit logging is automatic via GuildAuditMiddleware (keep the acknowledging "
                f"comment), or declare the route in router.audit_exempt_paths for high-frequency routes"
            )
        else:
            ok(f"Mutation endpoint '{fn_name}' acknowledges automatic AuditLog")

    if not mutation_fns:
        ok("No mutation endpoints detected")


def _find_mutation_functions(tree) -> list[tuple[str, int, str]]:
    """Return (function_name, lineno, route_path) for each router mutation."""
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in ("post", "put", "patch", "delete")
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id == "router"
                ):
                    route_path = ""
                    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                        route_path = dec.args[0].value
                    results.append((node.name, node.lineno, route_path))
    return results


def _function_source(src: str, start_line: int, lookahead: int = 60) -> str:
    lines = src.splitlines()
    return "\n".join(lines[start_line - 1 : start_line + lookahead])


# ── Frontend Page ─────────────────────────────────────────────────────────────

def validate_frontend(page_path: Path, page_kind: str = "dashboard"):
    """Validate a frontend page. *page_kind* selects the guard contract:

      - "dashboard": must export `withPermission(Page, PermissionLevel.X)`.
      - "activity":  Discord Activity (Embedded App SDK) page — exempt from
                     withPermission; must export `withActivityPage(Page)`. May
                     import @discord/embedded-app-sdk and use EventSource.
      - "public":    public site page (Level 0) — must export
                     `withPublicPage(Page)`; may use subscribeSSE/EventSource.
    """
    print("\n[page.tsx]")
    src = page_path.read_text()

    # Guard export depends on the page class.
    if page_kind == "activity":
        if not re.search(r"export default withActivityPage\s*\(", src):
            err(
                "Activity page must export withActivityPage(Page) — "
                "it is exempt from withPermission but needs the activity wrapper"
            )
        else:
            ok("withActivityPage export present (Activity page)")
    elif page_kind == "public":
        if not re.search(r"export default withPublicPage\s*\(", src):
            err(
                "Public page must export withPublicPage(Page) — "
                "Level 0 pages use the public wrapper, not withPermission"
            )
        else:
            ok("withPublicPage export present (public page)")
    else:
        # withPermission export
        if "withPermission" not in src:
            err(
                "Page is not wrapped with withPermission() — "
                "every dashboard page requires it (CLAUDE.md rule 3)"
            )
        else:
            ok("withPermission export present")

        # Check it's actually the default export
        if not re.search(r"export default withPermission\s*\(", src):
            warn(
                "withPermission found but may not be the default export — "
                "ensure: export default withPermission(PageComponent, PermissionLevel.X)"
            )

    # useTranslation hook
    if "useTranslation" not in src:
        err("No useTranslation() — all user-visible strings must use the i18n hook")
    else:
        ok("useTranslation() used")

    # Hardcoded hex in className/style attributes
    if re.search(r'(?:className|style)=["\'][^"\']*#[0-9a-fA-F]{3,8}', src):
        err("Hardcoded hex color in className/style — use Tailwind semantic tokens")
    elif re.search(r"#[0-9a-fA-F]{6}\b", src):
        warn("Hex color literal found (may be in a comment/string — verify it's not in JSX)")

    # Arbitrary Tailwind color values
    if re.search(r"(?:bg|text|border|ring|fill|stroke)-\[#[0-9a-fA-F]", src):
        err("Arbitrary Tailwind color values (e.g. bg-[#abc]) are forbidden — use semantic tokens")

    # rgb/rgba
    if re.search(r"\brgb[a]?\s*\(", src):
        err("Hardcoded rgb()/rgba() colors found — use Tailwind semantic tokens")

    if not ERRORS:
        ok("No hardcoded colors detected")

    # API call patterns — must use apiClient, not raw fetch/axios
    if re.search(r"""apiClient\.\w+\s*(?:<[^>]*>)?\s*\(\s*['\"`]/api/""", src):
        err(
            "apiClient path starts with /api/ — the base URL already includes /api/v1. "
            "Use paths relative to the base: apiClient.get('/guilds/${guildId}/...')"
        )

    if re.search(r"\bfetch\s*\(", src):
        err(
            "Raw fetch() call detected — use apiClient.get/post/put/delete() instead. "
            "Raw fetch bypasses the auth interceptor and will fail on 401/403."
        )
    if re.search(r"\baxios\s*\.\s*(get|post|put|delete|patch)\s*\(", src):
        err(
            "Direct axios call detected — use apiClient.get/post/put/delete() instead. "
            "Direct axios calls bypass the auth interceptor."
        )
    # Untyped apiClient generic calls — returns unknown, accessing properties will fail tsc
    if re.search(r"\bapiClient\.(get|post|put|delete)\s*\(", src):
        err(
            "Untyped apiClient call — TypeScript will infer 'unknown' and reject property access. "
            "Always provide a type parameter: apiClient.get<{ tickets: Ticket[] }>(...)"
        )

    # Bare 'use client' safety check
    if "'use client'" not in src and '"use client"' not in src:
        warn("No 'use client' directive — dashboard pages are almost always client components")


# ── Translations ──────────────────────────────────────────────────────────────

def validate_translations(translations_dir: Path, plugin_name: str):
    print("\n[translations/]")
    en_path = translations_dir / "en.ts"
    es_path = translations_dir / "es.ts"

    if not en_path.exists():
        err("translations/en.ts missing")
        return
    if not es_path.exists():
        err("translations/es.ts missing — must mirror en.ts exactly")
        return

    namespace = _to_camel_case(plugin_name)
    en_src = en_path.read_text()
    es_src = es_path.read_text()

    # Namespace key present in both
    if f"{namespace}:" not in en_src:
        warn(f"Plugin namespace '{namespace}:' not found in en.ts")
    else:
        ok(f"Namespace '{namespace}' in en.ts")

    if f"{namespace}:" not in es_src:
        warn(f"Plugin namespace '{namespace}:' not found in es.ts")
    else:
        ok(f"Namespace '{namespace}' in es.ts")

    # Compare leaf keys between the two files (simple heuristic)
    en_keys = set(re.findall(r"^\s{2,}(\w+)\s*:", en_src, re.MULTILINE))
    es_keys = set(re.findall(r"^\s{2,}(\w+)\s*:", es_src, re.MULTILINE))

    only_en = en_keys - es_keys
    only_es = es_keys - en_keys
    if only_en:
        warn(f"Keys in en.ts not found in es.ts: {sorted(only_en)}")
    if only_es:
        warn(f"Keys in es.ts not found in en.ts: {sorted(only_es)}")
    if not only_en and not only_es:
        ok("en.ts and es.ts keys match")

    # Check for hardcoded HTML or JSX leaking into translation values
    if re.search(r"<[a-zA-Z]", en_src):
        warn("HTML/JSX tags detected in en.ts translation values — use plain strings")


def _to_camel_case(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# ── Migration ────────────────────────────────────────────────────────────────

def _validate_migration(migration_path: Path):
    print("\n[migration.py]")
    src = migration_path.read_text()

    # revision ID must be present so the installer can register it
    if not re.search(r"^revision(?:\s*:\s*str)?\s*=\s*['\"][a-f0-9]+['\"]", src, re.MULTILINE):
        err("No revision ID found — migration.py must define: revision = 'abcdef123456'")
    else:
        ok("revision ID present")

    # CREATE TYPE without IF NOT EXISTS / DO $$ guard is not idempotent —
    # if the migration fails mid-run and is retried, the type already exists.
    unsafe = re.findall(r"CREATE\s+TYPE\s+\w+\s+AS\s+ENUM", src, re.IGNORECASE)
    safe   = re.findall(r"IF\s+NOT\s+EXISTS|DO\s+\$\$", src, re.IGNORECASE)
    if unsafe and not safe:
        err(
            f"Non-idempotent CREATE TYPE detected ({len(unsafe)} occurrence(s)). "
            "Wrap in a DO $$ BEGIN IF NOT EXISTS ... END $$; block so retries do not fail. "
            "See docs/integration/08-plugin-workflow.md for the safe pattern."
        )
    elif unsafe:
        ok("CREATE TYPE uses idempotent guard")


# ── Undeclared file detection ─────────────────────────────────────────────────

def check_undeclared_files(plugin_dir: Path, components: dict, manifest: dict):
    file_map = {
        "cog.py": "cog",
        "api.py": "api",
        "models.py": "models",
        "migration.py": "migration",
    }
    for filename, component_key in file_map.items():
        path = plugin_dir / filename
        if path.exists() and not components.get(component_key, False):
            warn(
                f"{filename} exists but '{component_key}' not declared in plugin.json components — "
                f"add it to components or remove the file"
            )

    # For single-page plugins: warn if page.tsx exists without frontend declared
    # For multi-page plugins: warn about any .tsx files not listed in a source
    # entry across pages / activity_pages / public_pages.
    if components.get("frontend"):
        declared_sources = set()
        for group_key in ("pages", "activity_pages", "public_pages"):
            for page in (manifest.get(group_key) or []):
                if isinstance(page, dict) and page.get("source"):
                    declared_sources.add(page["source"])
        if declared_sources:
            for tsx_file in plugin_dir.glob("*.tsx"):
                if tsx_file.name not in declared_sources:
                    warn(
                        f"{tsx_file.name} exists but is not listed in any pages/activity_pages/"
                        f"public_pages source entry — add it or remove the file"
                    )
    else:
        if (plugin_dir / "page.tsx").exists():
            warn("page.tsx exists but 'frontend' not declared in plugin.json components")
        for tsx_file in plugin_dir.glob("*.tsx"):
            if tsx_file.name != "page.tsx":
                warn(
                    f"{tsx_file.name} exists but 'frontend' is not declared — "
                    f"declare components.frontend and add a 'pages' array if this is a multi-page plugin"
                )

    trans_dir = plugin_dir / "translations"
    if trans_dir.is_dir() and not components.get("translations", False):
        warn("translations/ directory exists but 'translations' not declared in plugin.json")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python scripts/plugin_validate.py plugins/<plugin_name> [--strict]")
        sys.exit(1)

    plugin_dir = Path(args[0])
    if not plugin_dir.is_dir():
        print(f"ERROR: '{plugin_dir}' is not a directory")
        sys.exit(1)

    mode = " [STRICT]" if STRICT else ""
    print(f"Validating plugin: {plugin_dir.name}{mode}\n{'=' * 50}")

    print("\n[plugin.json]")
    manifest = validate_manifest(plugin_dir)
    components = manifest.get("components", {})
    plugin_name = manifest.get("name", plugin_dir.name)

    if components.get("cog"):
        p = plugin_dir / "cog.py"
        if p.exists():
            validate_cog(p, is_worker=bool(manifest.get("worker")))
        else:
            err("cog.py declared in components but file not found")

    if components.get("api"):
        p = plugin_dir / "api.py"
        if p.exists():
            router_section = manifest.get("router", {}) if isinstance(manifest.get("router"), dict) else {}
            validate_api(
                p,
                exempt_paths=router_section.get("audit_exempt_paths", []),
                router_prefix=router_section.get("prefix", "/guilds"),
            )
        else:
            err("api.py declared in components but file not found")

    if components.get("models"):
        p = plugin_dir / "models.py"
        if not p.exists():
            err("models.py declared in components but file not found")
        else:
            ok("models.py present")

    if components.get("migration"):
        p = plugin_dir / "migration.py"
        if not p.exists():
            err("migration.py declared in components but file not found")
        else:
            ok("migration.py present")
            _validate_migration(p)

    if components.get("frontend"):
        pages_def = manifest.get("pages")
        if pages_def and isinstance(pages_def, list):
            for i, page in enumerate(pages_def):
                source_name = page.get("source", "page.tsx")
                p = plugin_dir / source_name
                pid = page.get("id", f"index {i}")
                if p.exists():
                    print(f"\n[{source_name}]  (page id: '{pid}')")
                    validate_frontend(p)
                else:
                    err(f"pages[{i}] source '{source_name}' declared but file not found")
        else:
            p = plugin_dir / "page.tsx"
            if p.exists():
                validate_frontend(p)
            else:
                err("page.tsx declared in components but file not found")

        # Activity pages (Gap A) and public-site pages (Level 0) use different
        # guard contracts — validate them with the matching page_kind.
        for group_key, page_kind in (("activity_pages", "activity"), ("public_pages", "public")):
            for i, page in enumerate(manifest.get(group_key, []) or []):
                source_name = page.get("source", "")
                p = plugin_dir / source_name if source_name else None
                if p and p.exists():
                    print(f"\n[{source_name}]  ({page_kind} page)")
                    validate_frontend(p, page_kind=page_kind)
                elif source_name:
                    err(f"{group_key}[{i}] source '{source_name}' declared but file not found")

    if components.get("translations"):
        p = plugin_dir / "translations"
        if p.is_dir():
            validate_translations(p, plugin_name)
        else:
            err("translations/ declared in components but directory not found")

    check_undeclared_files(plugin_dir, components, manifest)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 50}")
    print(f"Results: {len(ERRORS)} error(s), {len(WARNINGS)} warning(s)\n")

    if WARNINGS:
        print("WARNINGS (install will proceed):")
        for w in WARNINGS:
            print(w)

    if ERRORS:
        print("\nERRORS (must fix before install):")
        for e in ERRORS:
            print(e)
        print("\nValidation FAILED")
        sys.exit(1)
    else:
        if WARNINGS:
            print()
        print("Validation PASSED — plugin is ready to install")
        sys.exit(0)


if __name__ == "__main__":
    main()
