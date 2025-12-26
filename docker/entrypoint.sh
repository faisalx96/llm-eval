#!/bin/sh
set -eu

echo "Running migrations..."
alembic -c llm_eval_platform/migrations/alembic.ini upgrade head

echo "Starting API..."
exec uvicorn llm_eval_platform.main:app --host 0.0.0.0 --port 8000


