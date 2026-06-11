#!/usr/bin/env bash
# =============================================================================
# uninstall_plugin.sh — Remove an installed plugin from the project
#
# Usage:
#   ./uninstall_plugin.sh <plugin_name>            # remove plugins/<plugin_name>
#   ./uninstall_plugin.sh <plugin_name> --dry-run  # preview without writing files
#
# Example:
#   ./uninstall_plugin.sh ticketnode
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Arguments ─────────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo -e "Usage: ${BOLD}./uninstall_plugin.sh <plugin_name> [--dry-run]${RESET}"
    echo
    echo "Available plugins:"
    for d in "$SCRIPT_DIR/plugins"/*/; do
        name="$(basename "$d")"
        [[ "$name" == _* ]] && continue
        [[ -f "$d/plugin.json" ]] && echo -e "  ${CYAN}${name}${RESET}"
    done
    echo
    exit 1
fi

PLUGIN_NAME="$1"
shift
EXTRA_ARGS=("$@")

PLUGIN_DIR="$SCRIPT_DIR/plugins/$PLUGIN_NAME"

if [[ ! -d "$PLUGIN_DIR" ]]; then
    echo -e "${RED}ERROR:${RESET} Plugin staging folder not found: plugins/${PLUGIN_NAME}"
    echo "The staging folder must exist (for plugin.json) to know what to remove."
    exit 1
fi

# ── Find Python ───────────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3 python3.12 python3.11 python3.10 python; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo -e "${RED}ERROR:${RESET} Python 3.8+ is required but was not found."
    exit 1
fi

# ── Run uninstaller ───────────────────────────────────────────────────────────
echo
echo -e "${BOLD}Uninstalling plugin:${RESET} ${CYAN}${PLUGIN_NAME}${RESET}"
echo

"$PYTHON" "$SCRIPT_DIR/scripts/plugin_uninstall.py" "plugins/$PLUGIN_NAME" "${EXTRA_ARGS[@]}"

STATUS=$?
if [[ $STATUS -eq 0 ]] && [[ ! " ${EXTRA_ARGS[*]} " =~ " --dry-run " ]]; then
    echo
    echo -e "${GREEN}Restart services to apply:${RESET}"
    echo -e "  docker compose restart backend bot frontend"
    echo
    echo -e "${YELLOW}To reinstall:${RESET}"
    echo -e "  ./install_plugin.sh ${PLUGIN_NAME}"
    echo
fi
exit $STATUS
