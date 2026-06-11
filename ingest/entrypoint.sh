#!/bin/sh
# Apply migrations, then seed the vendored World Cup 2026 data. Idempotent.
set -e

echo "==> alembic upgrade head"
alembic upgrade head

echo "==> python seed.py"
python seed.py

echo "==> done"
