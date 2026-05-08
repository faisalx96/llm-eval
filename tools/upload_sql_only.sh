#!/usr/bin/env bash
# Pipe a local CSV file into the platform container and ingest it as a run
# with the SQL-only output treatment.
#
# Usage:
#   tools/upload_sql_only.sh PATH_TO_CSV [extra args forwarded to the script]
#
# Examples:
#   tools/upload_sql_only.sh ./results/foo.csv                  # dry-run
#   tools/upload_sql_only.sh ./results/foo.csv --commit
#   tools/upload_sql_only.sh ./results/foo.csv --project-slug insightor \
#       --owner-email faisalx96@yahoo.com --commit
#
# The container `docker-api-1` must be running. See:
#   docker compose -f docker/docker-compose.yml ps

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 PATH_TO_CSV [extra args]" >&2
  exit 2
fi

CSV_PATH="$1"
shift

if [[ ! -f "$CSV_PATH" ]]; then
  echo "error: CSV not found: $CSV_PATH" >&2
  exit 2
fi

CONTAINER="${QYM_API_CONTAINER:-docker-api-1}"

exec docker exec -i "$CONTAINER" \
  python -m qym_platform.tools.upload_csv_sql_only "$@" \
  < "$CSV_PATH"
