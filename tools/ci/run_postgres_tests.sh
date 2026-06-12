#!/usr/bin/env bash
# Run the Postgres-backed platform test subset.
#
# Convention: tests that require a real PostgreSQL server are marked with
#   @pytest.mark.postgres
# (marker registered in the repo-root pytest.ini). CI runs this script in the
# migrations-postgres job after `alembic upgrade head` against postgres:16,
# with QYM_DATABASE_URL pointing at that server.
#
# pytest exits with code 5 when no tests are collected; until the first
# postgres-marked test lands that is expected and treated as success.
set -uo pipefail

pytest tests/platform -m postgres -q
status=$?

if [ "$status" -eq 5 ]; then
    echo "No postgres-marked tests collected yet; treating as success."
    exit 0
fi
exit "$status"
