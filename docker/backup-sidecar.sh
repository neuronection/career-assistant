#!/bin/sh
# Backup sidecar loop (profile `backup`): one pg_dump per interval into the
# ./backups bind mount, each run recorded as a row in `backup_runs`
# (ADR-0063 §2 — a failed or stale backup is a query, not a log line).
#
# This sidecar is same-host by design (non-DR when used alone). The
# off-host upload belongs to scripts/backup.sh, which writes the same
# ledger and uploads to S3/Azure/rclone.
set -eu

INTERVAL="${BACKUP_INTERVAL_HOURS:-24}"
KEEP="${BACKUP_KEEP:-14}"
PSQL="psql -U ${POSTGRES_USER:?POSTGRES_USER required} -d ${POSTGRES_DB:?POSTGRES_DB required} -v ON_ERROR_STOP=1 -qAt"

ledger() {
  # Ledger writes are best-effort: a pre-0016 schema must not break the
  # dumps (the SQL failure is visible in `docker compose logs backup`).
  echo "$1" | $PSQL >/dev/null 2>&1 || \
    echo "backup-sidecar: backup_runs write failed (schema older than 0016?)" >&2
}

while :; do
  ts="$(date -u +%Y%m%d-%H%M%S)"
  target="/backups/db-${ts}.dump"
  run_id="$($PSQL -c "INSERT INTO backup_runs (id, started_at, status) VALUES (gen_random_uuid(), now(), 'running') RETURNING id" 2>/dev/null)" \
    || run_id=""
  ledger_dirty=0
  if [ -n "$run_id" ]; then ledger_dirty=1; fi

  echo "backup-sidecar: dumping to ${target}"
  status="ok"
  error_class=""
  if ! pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$target"; then
    status="failed"
    error_class="pg_dump"
    rm -f "$target"
  fi

  if [ "$ledger_dirty" = "1" ]; then
    bytes="$(stat -c%s "$target" 2>/dev/null || echo 0)"
    checksum="$(sha256sum "$target" 2>/dev/null | awk '{print $1}')"
    ledger "UPDATE backup_runs SET status='${status}', finished_at=now(), \
bytes=${bytes}, checksum='${checksum}', destination='${target}', error_class='${error_class}' WHERE id='${run_id}'"
  fi
  [ "$status" = "ok" ] || echo "backup-sidecar: dump FAILED (${error_class})" >&2

  find /backups -name 'db-*.dump' -type f | sort | head -n -"$KEEP" | xargs -r rm --
  sleep "$((INTERVAL * 3600))"
done
