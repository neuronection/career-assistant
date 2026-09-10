#!/usr/bin/env bash
# Restore a Career Assistant instance backup produced by scripts/backup.sh.
# Usage: scripts/restore.sh <archive.tar.gz>
# WARNING: replaces the current database contents and uploads volume.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE="${1:?Usage: scripts/restore.sh <archive.tar.gz>}"

if [[ ! -f "$ARCHIVE" ]]; then
  echo "No such archive: $ARCHIVE" >&2
  exit 1
fi

if [[ -f "$ROOT/docker/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/docker/.env"
  set +a
fi
POSTGRES_DB="${POSTGRES_DB:-career}"
POSTGRES_USER="${POSTGRES_USER:-career}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD (env or docker/.env)}"
COMPOSE="docker compose -f $ROOT/docker/docker-compose.prod.yml"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar xzf "$ARCHIVE" -C "$WORK"

echo "==> Restoring database (drops existing rows)"
"$COMPOSE" exec -T db \
  env PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" --clean --if-exists < "$WORK/database.dump"

echo "==> Restoring uploads volume"
docker run --rm -v career-assistant_uploads_data:/data -v "$WORK":/in:ro alpine \
  sh -c "rm -rf /data/* && tar xzf /in/uploads.tar.gz -C /data"

echo "==> Done. Restart the app to re-run migrations if needed:"
echo "    $COMPOSE up -d"
