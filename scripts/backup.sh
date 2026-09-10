#!/usr/bin/env bash
# Career Assistant instance backup (Docker deployment): Postgres dump + uploads.
# Usage: scripts/backup.sh [output-dir]
# Reads docker/.env (or environment) for POSTGRES_* settings. Output:
#   <output-dir>/career-assistant-YYYYMMDD-HHMMSS.tar.gz
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/backups}"
mkdir -p "$OUT_DIR"

# Load docker/.env if present (does not override real env vars).
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

STAMP="$(date -u +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> Dumping database"
"$COMPOSE" exec -T db \
  env PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" \
  > "$WORK/database.dump"

echo "==> Archiving uploads volume"
docker run --rm -v career-assistant_uploads_data:/data:ro -v "$WORK":/out alpine \
  tar czf /out/uploads.tar.gz -C /data .

cat > "$WORK/manifest.json" <<EOF
{
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "contents": ["database.dump (pg_dump custom format)", "uploads.tar.gz"],
  "postgres_db": "$POSTGRES_DB",
  "app_version": "see /health"
}
EOF

ARCHIVE="$OUT_DIR/career-assistant-$STAMP.tar.gz"
tar czf "$ARCHIVE" -C "$WORK" .
echo "==> Done: $ARCHIVE"
echo "    Retention is manual: keep at least the last N archives off-machine."
