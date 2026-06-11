#!/usr/bin/env bash
# =============================================================================
# Baseline Framework — New Bot Initialiser
# =============================================================================
# Run this script ONCE after cloning the repository to start a new bot project.
# It write-protects core framework files so accidental edits are caught
# immediately rather than silently breaking the framework contract.
#
# This script also removes all plugins from plugins/ (except _template and
# other _* scaffolding folders) so the project starts completely clean.
# Build your own plugins from _template.
#
# Usage:
#   chmod +x init.sh
#   ./init.sh
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo
echo -e "${BOLD}${CYAN}Baseline Framework — New Bot Initialiser${RESET}"
echo -e "${CYAN}==========================================${RESET}"
echo
read -rp "Continue? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Aborted.${RESET}"
    exit 0
fi
echo

# ── Write-protect core framework files ───────────────────────────────────────
# To intentionally edit a core file: chmod 644 <file>, edit, chmod 444 <file>.
echo -e "${BOLD}Write-protecting core framework files${RESET}"

protect_file() {
    local f="$1"
    if [ -f "$f" ]; then
        chmod 444 "$f"
        echo -e "  ${GREEN}✓${RESET}  protected  ${f#$SCRIPT_DIR/}"
    fi
}

protect_file "bot/core/bot.py"
protect_file "bot/core/loader.py"
protect_file "backend/app/api/auth.py"
protect_file "backend/app/api/deps.py"
protect_file "backend/app/db/guild_session.py"
protect_file "backend/app/db/session.py"
protect_file "frontend/lib/auth-context.tsx"
protect_file "frontend/app/layout.tsx"

if [ -d "backend/alembic/versions" ]; then
    find "backend/alembic/versions" -name "*.py" -exec chmod 444 {} \;
    echo -e "  ${GREEN}✓${RESET}  protected  backend/alembic/versions/*.py"
fi

# ── Remove all plugins ────────────────────────────────────────────────────────
echo
echo -e "${BOLD}Removing all plugins${RESET}"

for d in "$SCRIPT_DIR/plugins"/*/; do
    name="$(basename "$d")"
    [[ "$name" == _* ]] && continue          # keep _template and any _* folders
    [[ "$name" == "README.md" ]] && continue
    rm -rf "$d"
    echo -e "  ${GREEN}✓${RESET}  removed    plugins/${name}"
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}${GREEN}Done!${RESET}"
echo
echo -e "${BOLD}Next steps:${RESET}"
echo -e "  1.  Rename your bot — update ${CYAN}NEXT_PUBLIC_APP_NAME${RESET} in ${CYAN}.env${RESET}"
echo -e "      (or use the Setup Wizard after first launch)"
echo -e "  2.  Build features as plugins in ${CYAN}plugins/<name>/${RESET}"
echo -e "      cp -r plugins/_template plugins/<name>"
echo -e "      ./install_plugin.sh <name>"
echo -e "  3.  Read ${CYAN}docs/DEVELOPER_MANUAL.md${RESET} for the full guide"
echo
echo -e "  ${YELLOW}Note:${RESET} Core files are now write-protected (chmod 444)."
echo -e "        To patch one intentionally:"
echo -e "        ${CYAN}chmod 644 <file>${RESET}  →  edit  →  ${CYAN}chmod 444 <file>${RESET}"
echo
