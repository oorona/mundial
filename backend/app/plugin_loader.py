"""
plugin_loader.py — Auto-discovers and registers plugin routers.

main.py calls load_plugin_routers(app, api_prefix) once at startup.
It reads backend/installed_plugins.json and imports each plugin's router
dynamically.  Missing or broken plugin files are logged as warnings and
skipped — they never crash the framework.
"""

import importlib
import json
import logging
from pathlib import Path

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_REGISTRY = Path(__file__).resolve().parent.parent / "installed_plugins.json"


def load_plugin_routers(app: FastAPI, api_prefix: str) -> None:
    """Import every installed plugin router and mount it on *app*.

    Safe to call even when the registry file does not exist (e.g., on a fresh
    install with no plugins).  Each entry in the registry is loaded
    independently — one broken plugin never prevents the others from loading.
    """
    if not _REGISTRY.exists():
        return

    try:
        plugins: list[dict] = json.loads(_REGISTRY.read_text())
    except Exception as exc:
        logger.warning("plugin_loader: could not read %s — %s", _REGISTRY, exc)
        return

    for entry in plugins:
        name = entry.get("name")
        prefix = entry.get("prefix", "/guilds")
        tag = entry.get("tag", name)

        if not name:
            logger.warning("plugin_loader: skipping entry with no 'name': %s", entry)
            continue

        module_path = f"app.api.{name}"
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            logger.warning(
                "plugin_loader: plugin '%s' not found (%s) — skipping", name, exc
            )
            continue
        except Exception as exc:
            logger.warning(
                "plugin_loader: failed to import plugin '%s' (%s) — skipping", name, exc
            )
            continue

        router = getattr(module, "router", None)
        if router is None:
            logger.warning(
                "plugin_loader: module '%s' has no 'router' attribute — skipping", module_path
            )
            continue

        app.include_router(router, prefix=f"{api_prefix}{prefix}", tags=[tag])
        logger.info("plugin_loader: registered plugin '%s' at %s%s", name, api_prefix, prefix)
