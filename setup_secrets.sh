#!/usr/bin/env bash
# =============================================================================
# setup_secrets.sh — Generate all secrets needed before first launch
#
# Run this ONCE before your first `docker compose up`.
# Creates:
#   secrets/encryption_key       — AES-256 key for the settings vault
#   secrets/postgres_password.txt — Postgres superuser password (used by
#                                   setup_database.sh and docker-compose.yml)
#
# Usage:
#   ./setup_secrets.sh
#   ./setup_secrets.sh --force   # overwrite existing secrets (loses all settings!)
#
# After this script completes:
#   1. Run:  docker compose up -d postgres
#   2. Run:  ./setup_database.sh --container postgres --user <name> --db <name>
#   3. Run:  docker compose up
#   4. Open the app — you will be redirected to the Setup Wizard.
# =============================================================================

set -euo pipefail

FORCE=false
for arg in "$@"; do
  [[ "$arg" == "--force" ]] && FORCE=true
done

mkdir -p secrets
chmod 700 secrets

# ── Encryption key ────────────────────────────────────────────────────────────
KEY_FILE="secrets/encryption_key"

if [[ -f "$KEY_FILE" ]] && [[ "$FORCE" == false ]]; then
  echo ""
  echo "  secrets/encryption_key already exists — skipping."
  echo "  Use --force to regenerate (WARNING: invalidates any existing settings.enc)."
else
  if command -v openssl &>/dev/null; then
    openssl rand -hex 32 > "$KEY_FILE"
  else
    xxd -l 32 -p /dev/urandom | tr -d '\n' > "$KEY_FILE"
  fi
  chmod 600 "$KEY_FILE"
  echo ""
  echo "  ✓  secrets/encryption_key created."
fi

# ── Postgres superuser password ───────────────────────────────────────────────
PG_FILE="secrets/postgres_password.txt"

if [[ -f "$PG_FILE" ]] && [[ "$FORCE" == false ]]; then
  echo "  ✓  secrets/postgres_password.txt already exists — skipping."
else
  echo ""
  echo "  Set a password for the Postgres superuser (the 'postgres' user inside"
  echo "  the Docker container). This is used by setup_database.sh to create your"
  echo "  app database user. It must match POSTGRES_PASSWORD in docker-compose.yml."
  echo ""
  read -rsp "  Postgres superuser password: " PG_PASS
  echo ""
  read -rsp "  Confirm password: " PG_PASS_CONFIRM
  echo ""
  if [[ "$PG_PASS" != "$PG_PASS_CONFIRM" ]]; then
    echo "  ERROR: Passwords do not match."
    exit 1
  fi
  if [[ -z "$PG_PASS" ]]; then
    echo "  ERROR: Password cannot be empty."
    exit 1
  fi
  echo "$PG_PASS" > "$PG_FILE"
  chmod 600 "$PG_FILE"
  echo "  ✓  secrets/postgres_password.txt created."
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Secrets ready."
echo ""
echo "  KEEP THESE FILES SAFE:"
echo "    - Never commit them to git  (already in .gitignore)"
echo "    - Back them up securely — losing encryption_key means"
echo "      losing all encrypted settings and re-running the wizard"
echo ""
echo "  Next steps:"
echo "    docker compose up -d postgres"
echo "    ./setup_database.sh --container postgres --user <name> --db <name>"
echo "    docker compose up"
echo "═══════════════════════════════════════════════════════════"
echo ""
