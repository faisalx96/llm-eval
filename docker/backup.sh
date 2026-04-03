#!/bin/bash
set -euo pipefail

BACKUP_DIR="/backups"
mkdir -p "${BACKUP_DIR}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
INTERVAL="${BACKUP_INTERVAL_HOURS:-6}"

echo "[backup] Starting backup service (every ${INTERVAL}h, retain ${KEEP_DAYS} days)"

while true; do
  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
  FILENAME="${BACKUP_DIR}/qym_${TIMESTAMP}.sql.gz"

  echo "[backup] $(date -Iseconds) — dumping to ${FILENAME}"
  pg_dump --no-owner --no-acl --clean --if-exists | gzip > "${FILENAME}"

  SIZE=$(du -h "${FILENAME}" | cut -f1)
  echo "[backup] Done — ${SIZE}"

  # Prune old backups
  CUTOFF=$(date -d "-${KEEP_DAYS} days" +%s 2>/dev/null || date -v-${KEEP_DAYS}d +%s)
  PRUNED=0
  for f in "${BACKUP_DIR}"/qym_*.sql.gz; do
    [ -f "$f" ] || continue
    FILE_TS=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f")
    if [ "$FILE_TS" -lt "$CUTOFF" ]; then
      rm "$f"
      PRUNED=$((PRUNED + 1))
    fi
  done
  [ "$PRUNED" -gt 0 ] && echo "[backup] Pruned ${PRUNED} old backup(s)"

  TOTAL=$(ls -1 "${BACKUP_DIR}"/qym_*.sql.gz 2>/dev/null | wc -l)
  echo "[backup] ${TOTAL} backup(s) on disk. Next run in ${INTERVAL}h."

  sleep "$((INTERVAL * 3600))"
done
