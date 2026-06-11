#!/bin/bash
set -e

# This script runs once when the postgres data volume is first created.
# It creates the application user and database for the baseline platform.
#
# Required env vars:
#   POSTGRES_USER      — postgres superuser (set by docker-compose)
#   BASELINE_PASSWORD  — password for the 'baseline' app user (set by docker-compose)

if [ -z "$BASELINE_PASSWORD" ]; then
  echo "ERROR: BASELINE_PASSWORD must be set (configure POSTGRES_APP_PASSWORD in .env)"
  exit 1
fi

echo "Creating baseline app user, database, and schema..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL

  -- Create application user
  CREATE USER baseline WITH PASSWORD '${BASELINE_PASSWORD}';

  -- Create application database owned by app user
  CREATE DATABASE baseline OWNER baseline;

  -- Connect into the new database to configure schema
  \c baseline;

  -- Create schema owned by baseline user
  CREATE SCHEMA IF NOT EXISTS baseline AUTHORIZATION baseline;

  -- Set search_path so SQLAlchemy defaults to schema baseline
  ALTER ROLE baseline IN DATABASE baseline
      SET search_path = baseline, public;

EOSQL

echo "Baseline DB, user, and schema created."
