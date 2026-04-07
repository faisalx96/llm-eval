#!/bin/sh
set -eu

echo "Running migrations..."
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head

echo "Starting API..."
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn qym_platform.main:app --host 0.0.0.0 --port 8000 --root-path "${QYM_ROOT_PATH:-}"
