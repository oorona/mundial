#!/usr/bin/env bash
# remove_plugin.sh — Uninstall a plugin from the Baseline framework
#
# Usage:
#   ./remove_plugin.sh <plugin_name>
#   ./remove_plugin.sh <plugin_name> --dry-run
#
# What this does:
#   1. Removes backend/app/api/<name>.py
#   2. Removes bot/cogs/<name>.py
#   3. Removes frontend/app/dashboard/[guildId]/<name>/page.tsx
#   4. Removes the plugin entry from backend/installed_plugins.json
#   5. Removes the plugin entry from backend/migration_inventory.json (if present)
#   6. Prints a reminder to remove i18n strings and nav card manually
#
# What this does NOT do (requires manual cleanup):
#   - Drop database tables (use the DB Management page)
#   - Remove i18n translation keys (search for the plugin namespace in en.ts / es.ts)
#   - Remove the nav card from frontend/app/page.tsx

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/scripts/plugin_remove.py" "$@"
