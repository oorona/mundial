#!/usr/bin/env bash
# =============================================================================
# setup_database.sh — Create the application database user and schema
#
# Run this ONCE before starting the full stack for the first time.
#
# Schema isolation:
#   The schema name always equals the database username.
#   ALL application objects (tables, views, sequences, etc.) live inside
#   that schema.  The public schema is off-limits for the app user.
#
#   This means multiple bots can share the same postgres cluster safely:
#     bot_a  →  database: bot_a,  schema: bot_a,  user: bot_a
#     bot_b  →  database: bot_b,  schema: bot_b,  user: bot_b
#   Their objects never mix, and neither can write to the other's schema.
#
# Usage:
#   ./setup_database.sh                        # interactive — prompts for all values
#   ./setup_database.sh --container mypostgres # use a specific container name
#
# Options:
#   --container  Docker container name running postgres  (prompted if omitted; default: postgres)
#   --user       DB username (and schema name)           (prompted if omitted)
#   --password   DB password                             (prompted if omitted — avoids shell history)
#   --db         Database name                           (prompted if omitted; default: same as --user)
#
# The postgres superuser password is read from secrets/postgres_password.txt.
#
# The credentials you choose here are what you enter in the Setup Wizard.
# The wizard will test the connection and run Alembic migrations to create
# all tables inside the dedicated schema.
# =============================================================================

set -euo pipefail

# ── Resolve script directory so the path to secrets/ is always correct ────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_FILE="${SCRIPT_DIR}/secrets/postgres_password.txt"

# ── Defaults ──────────────────────────────────────────────────────────────────
PG_CONTAINER=""
APP_USER=""
APP_PASSWORD=""
APP_DB=""

# ── Parse arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --container) PG_CONTAINER="$2"; shift 2 ;;
    --user)      APP_USER="$2";     shift 2 ;;
    --password)  APP_PASSWORD="$2"; shift 2 ;;
    --db)        APP_DB="$2";       shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Read postgres superuser password from the Docker secret file ──────────────
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo ""
  echo "ERROR: Superuser password file not found: ${SECRETS_FILE}"
  echo ""
  echo "  Create it first:"
  echo "    echo 'your-superuser-password' > secrets/postgres_password.txt"
  echo "    chmod 600 secrets/postgres_password.txt"
  echo ""
  exit 1
fi
PG_SUPERUSER_PASSWORD="$(< "$SECRETS_FILE")"
if [[ -z "$PG_SUPERUSER_PASSWORD" ]]; then
  echo "ERROR: secrets/postgres_password.txt is empty."
  exit 1
fi

# ── Prompt for any missing parameters ────────────────────────────────────────
if [[ -z "$PG_CONTAINER" ]]; then
  echo ""
  read -rp "Postgres container name [postgres]: " PG_CONTAINER
  PG_CONTAINER="${PG_CONTAINER:-postgres}"
fi

if [[ -z "$APP_USER" ]]; then
  echo ""
  read -rp "Database username: " APP_USER
  if [[ -z "$APP_USER" ]]; then
    echo "ERROR: Username cannot be empty."
    exit 1
  fi
fi

# Schema name is always the same as the username — not configurable.
APP_SCHEMA="$APP_USER"

if [[ -z "$APP_DB" ]]; then
  echo ""
  read -rp "Database name [${APP_USER}]: " APP_DB
  APP_DB="${APP_DB:-$APP_USER}"
else
  APP_DB="${APP_DB:-$APP_USER}"
fi

if [[ -z "$APP_PASSWORD" ]]; then
  echo ""
  read -rsp "Password for database user '${APP_USER}': " APP_PASSWORD
  echo ""
  read -rsp "Confirm password: " APP_PASSWORD_CONFIRM
  echo ""
  if [[ "$APP_PASSWORD" != "$APP_PASSWORD_CONFIRM" ]]; then
    echo "ERROR: Passwords do not match."
    exit 1
  fi
fi

if [[ -z "$APP_PASSWORD" ]]; then
  echo "ERROR: Password cannot be empty."
  exit 1
fi

# ── Verify the container is running ──────────────────────────────────────────
echo ""
echo "Checking container '${PG_CONTAINER}'..."
if ! docker inspect --format '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null | grep -q "true"; then
  echo ""
  echo "  ERROR: container '${PG_CONTAINER}' is not running."
  echo "  Check with: docker ps"
  echo ""
  exit 1
fi
echo "  Container is running."

PSQL="docker exec -i -e PGPASSWORD=${PG_SUPERUSER_PASSWORD} ${PG_CONTAINER} psql -U postgres"

# ── Step 1: Create the role and database ──────────────────────────────────────
echo ""
echo "Creating role '${APP_USER}' and database '${APP_DB}'..."

$PSQL -v ON_ERROR_STOP=1 <<-EOSQL
  -- Create the application role (idempotent)
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_USER}') THEN
      CREATE ROLE "${APP_USER}" WITH LOGIN PASSWORD '${APP_PASSWORD}';
      RAISE NOTICE 'Role "${APP_USER}" created.';
    ELSE
      ALTER ROLE "${APP_USER}" WITH PASSWORD '${APP_PASSWORD}';
      RAISE NOTICE 'Role "${APP_USER}" already exists — password updated.';
    END IF;
  END
  \$\$;

  -- Create the database (idempotent)
  SELECT 'CREATE DATABASE "${APP_DB}" OWNER "${APP_USER}"'
  WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${APP_DB}')
  \gexec
EOSQL

# ── Step 2: Configure schema isolation ────────────────────────────────────────
echo "Configuring schema isolation (schema: '${APP_SCHEMA}')..."

$PSQL -d "$APP_DB" -v ON_ERROR_STOP=1 <<-EOSQL

  -- Create the dedicated schema owned by the app user
  CREATE SCHEMA IF NOT EXISTS "${APP_SCHEMA}" AUTHORIZATION "${APP_USER}";

  -- search_path = schema only.  The connection never sees public.
  ALTER ROLE "${APP_USER}" IN DATABASE "${APP_DB}"
    SET search_path = "${APP_SCHEMA}";

  -- Full ownership of the schema
  GRANT ALL ON SCHEMA "${APP_SCHEMA}" TO "${APP_USER}";

  -- Revoke the app user's ability to create anything in public
  REVOKE CREATE ON SCHEMA public FROM "${APP_USER}";

EOSQL

echo "  Done."

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Database ready."
echo ""
echo "  Enter these credentials in the Setup Wizard:"
echo ""
echo "    Host:     ${PG_CONTAINER}   (Docker container/service name)"
echo "    Port:     5432"
echo "    User:     ${APP_USER}"
echo "    Password: ${APP_PASSWORD}"
echo "    Database: ${APP_DB}"
echo "    Schema:   ${APP_SCHEMA}   (same as username — auto-set)"
echo ""
echo "  All application objects will be created in the"
echo "  '${APP_SCHEMA}' schema.  Public schema is off-limits."
echo ""
echo "  Next step:"
echo "    docker compose up"
echo "═══════════════════════════════════════════════════════════"
echo ""
