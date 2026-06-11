#!/usr/bin/env bash
# =============================================================================
# install_plugin.sh — Validate and install a plugin into the project
#
# Usage:
#   ./install_plugin.sh <plugin_name>            # install plugins/<plugin_name>
#   ./install_plugin.sh <plugin_name> --dry-run  # preview without writing files
#   ./install_plugin.sh <plugin_name> --force    # skip validator
#
# Example:
#   ./install_plugin.sh event_logging
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Arguments ─────────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo -e "Usage: ${BOLD}./install_plugin.sh <plugin_name> [--dry-run] [--force]${RESET}"
    echo
    echo "Available plugins:"
    for d in "$SCRIPT_DIR/plugins"/*/; do
        name="$(basename "$d")"
        [[ "$name" == _* ]] && continue
        if [[ -f "$d/plugin.json" ]]; then
            desc="$(python3 -c "import json; d=json.load(open('$d/plugin.json')); print(d.get('description','')[:60])" 2>/dev/null || echo "")"
            echo -e "  ${CYAN}${name}${RESET}  ${desc}"
        fi
    done
    echo
    exit 1
fi

PLUGIN_NAME="$1"
shift
EXTRA_ARGS=("$@")

PLUGIN_DIR="$SCRIPT_DIR/plugins/$PLUGIN_NAME"

if [[ ! -d "$PLUGIN_DIR" ]]; then
    echo -e "${RED}ERROR:${RESET} Plugin folder not found: plugins/${PLUGIN_NAME}"
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

# ── Find Python ───────────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3 python3.12 python3.11 python3.10 python; do
    if command -v "$candidate" &>/dev/null; then
        version="$("$candidate" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null)"
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo -e "${RED}ERROR:${RESET} Python 3.8+ is required but was not found."
    echo
    echo "Install Python:"
    echo "  Debian/Ubuntu : sudo apt install python3"
    echo "  macOS         : brew install python3"
    echo "  Windows       : https://python.org/downloads"
    exit 1
fi

# ── Check for manual-install plugins ─────────────────────────────────────────
if [[ -f "$PLUGIN_DIR/plugin.json" ]]; then
    install_mode="$("$PYTHON" -c "import json; d=json.load(open('$PLUGIN_DIR/plugin.json')); print(d.get('install_mode','standard'))" 2>/dev/null || echo "standard")"
    if [[ "$install_mode" == "manual" ]]; then
        notes="$("$PYTHON" -c "import json; d=json.load(open('$PLUGIN_DIR/plugin.json')); print(d.get('install_notes','See plugin.json for instructions.'))" 2>/dev/null || echo "See plugin.json.")"
        echo -e "${YELLOW}This plugin requires manual installation.${RESET}"
        echo
        echo "$notes"
        echo
        exit 1
    fi
fi

# ── Run installer ─────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}Installing plugin:${RESET} ${CYAN}${PLUGIN_NAME}${RESET}"
echo

"$PYTHON" "$SCRIPT_DIR/scripts/plugin_install.py" "plugins/$PLUGIN_NAME" "${EXTRA_ARGS[@]}"

STATUS=$?
if [[ $STATUS -eq 0 ]] && [[ ! " ${EXTRA_ARGS[*]} " =~ " --dry-run " ]]; then
    echo
    echo -e "${GREEN}Restart services to apply:${RESET}"
    echo -e "  docker compose restart backend bot frontend"
    echo
fi
exit $STATUS
