#!/bin/bash
# Wrapper script to read postgres password from secret file and set as env var for init scripts

if [ -f "/run/secrets/postgres_password" ]; then
  export BASELINE_PASSWORD=$(cat /run/secrets/postgres_password)
fi

# Execute the original docker entrypoint
exec docker-entrypoint.sh "$@"
