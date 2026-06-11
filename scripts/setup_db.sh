#!/usr/bin/env bash
# setup_db.sh — Create the `mundial` database, role, and dedicated schema on the
# shared PostgreSQL, then run migrations + seed via the one-shot ingest container.
#
# Usage:
#   ./scripts/setup_db.sh
#
# Environment variables (with defaults):
#   PG_CONTAINER  — shared PostgreSQL container name (default: postgres)
#   ADMIN_USER    — superuser to connect as (default: postgres)
#   NEW_DB        — database to create (default: mundial)
#   NEW_USER      — role to create (default: mundial)
#   NEW_SCHEMA    — schema holding all tables (default: mundial)
#   NEW_PASSWORD  — password for the new role (REQUIRED, or read from secrets/db_password.txt)
#   INGEST_SERVICE — compose service for the one-shot ingest (default: ingest)

set -euo pipefail

PG_CONTAINER="${PG_CONTAINER:-postgres}"
ADMIN_USER="${ADMIN_USER:-postgres}"
NEW_DB="${NEW_DB:-mundial}"
NEW_USER="${NEW_USER:-mundial}"
NEW_SCHEMA="${NEW_SCHEMA:-mundial}"
INGEST_SERVICE="${INGEST_SERVICE:-ingest}"

# Read password from env, secrets file, or prompt.
if [ -z "${NEW_PASSWORD:-}" ]; then
    SECRETS_FILE="$(dirname "$0")/../secrets/db_password.txt"
    if [ -f "$SECRETS_FILE" ]; then
        NEW_PASSWORD="$(tr -d '[:space:]' < "$SECRETS_FILE")"
        echo "Read password from $SECRETS_FILE"
    else
        echo -n "Enter password for user '$NEW_USER': "
        read -rs NEW_PASSWORD
        echo
    fi
fi

if [ -z "$NEW_PASSWORD" ]; then
    echo "ERROR: No password provided. Set NEW_PASSWORD or create secrets/db_password.txt"
    exit 1
fi

run_psql() {
    local db="$1"; shift
    docker exec -i "$PG_CONTAINER" psql -U "$ADMIN_USER" -d "$db" "$@"
}

echo "==> Creating role '$NEW_USER' and database '$NEW_DB' in container '$PG_CONTAINER'"

run_psql postgres <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${NEW_USER}') THEN
        CREATE ROLE ${NEW_USER} WITH LOGIN PASSWORD '${NEW_PASSWORD}';
        RAISE NOTICE 'Role ${NEW_USER} created';
    ELSE
        ALTER ROLE ${NEW_USER} WITH PASSWORD '${NEW_PASSWORD}';
        RAISE NOTICE 'Role ${NEW_USER} exists, password updated';
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${NEW_DB} OWNER ${NEW_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${NEW_DB}')
\gexec

ALTER DATABASE ${NEW_DB} OWNER TO ${NEW_USER};
SQL

echo "==> Creating dedicated schema '$NEW_SCHEMA' and setting search_path"

run_psql "$NEW_DB" <<SQL
CREATE SCHEMA IF NOT EXISTS ${NEW_SCHEMA} AUTHORIZATION ${NEW_USER};

-- Make unqualified objects resolve to the app schema for this role+db.
ALTER ROLE ${NEW_USER} IN DATABASE ${NEW_DB} SET search_path TO ${NEW_SCHEMA}, public;

GRANT ALL ON SCHEMA ${NEW_SCHEMA} TO ${NEW_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${NEW_USER} IN SCHEMA ${NEW_SCHEMA} GRANT ALL ON TABLES TO ${NEW_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${NEW_USER} IN SCHEMA ${NEW_SCHEMA} GRANT ALL ON SEQUENCES TO ${NEW_USER};

-- Lock down public: the app creates nothing there.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM ${NEW_USER};
GRANT USAGE ON SCHEMA public TO ${NEW_USER};
SQL

echo "==> Running migrations + seed via 'docker compose run --rm ${INGEST_SERVICE}'"
cd "$(dirname "$0")/.."
docker compose run --rm "$INGEST_SERVICE"

echo "==> Done. Tables in schema '${NEW_SCHEMA}':"
run_psql "$NEW_DB" -c "SELECT tablename FROM pg_tables WHERE schemaname = '${NEW_SCHEMA}' ORDER BY tablename;"
