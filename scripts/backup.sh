#!/usr/bin/env bash
# Career Assistant instance backup (Docker deployment): Postgres dump +
# uploads, one run row in the `backup_runs` ledger (ADR-0063 §2), optional
# age encryption, and an off-host upload (S3 / Azure / rclone) for T1.
#
# Usage: scripts/backup.sh [output-dir]
#
# Environment (docker/.env or the shell):
#   BACKUP_REMOTE          off-host destination (empty = local-only, which
#                          is non-DR and must be labelled so):
#                            s3://bucket/prefix        → aws s3 cp (or rclone)
#                            https://acct.blob.../ctr  → azcopy copy
#                            remote:path  (any rclone target, has a `:`)
#   BACKUP_AGE_RECIPIENT   age public key — encrypts the archive before the
#                          upload (career: encrypt when the destination is
#                          shared; ADR-0063 §3)
#   AWS_PROFILE / AWS_* / RCLONE_CONFIG / AZCOPY_*  pass through to the tool
#
# Reads docker/.env (does not override real env vars).
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

POSTGRES_DB="${POSTGRES_DB:-neuronection_career}"
POSTGRES_USER="${POSTGRES_USER:-neuronection_career_owner}"
POSTGRES_PASSWORD="${CAREER_DB_OWNER_PASSWORD:-${POSTGRES_PASSWORD:?Set CAREER_DB_OWNER_PASSWORD (env or docker/.env)}}"
COMPOSE_FILE="${CAREER_COMPOSE_FILE:-docker/docker-compose.prod.yml}"
[[ "$COMPOSE_FILE" = /* ]] || COMPOSE_FILE="$ROOT/$COMPOSE_FILE"
COMPOSE=(docker compose -f "$COMPOSE_FILE")

STAMP="$(date -u +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> Dumping database"
"${COMPOSE[@]}" exec -T db \
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
BYTES="$(stat -c%s "$ARCHIVE" 2>/dev/null || stat -f%z "$ARCHIVE")"
CHECKSUM="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"

# Ledger row (ADR-0063 §2): one row per run, best-effort — a pre-0016
# schema must never break the backup itself. The writer is this script,
# never the web app.
ledger() {
  "${COMPOSE[@]}" exec -T db \
    env PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -v ON_ERROR_STOP=1 -qAt -c "$1" 2>/dev/null || true
}
RUN_ID="$(ledger "INSERT INTO backup_runs (id, started_at, status) VALUES (gen_random_uuid(), now(), 'running') RETURNING id")"

status_finish() { # status error-class
  if [[ -n "$RUN_ID" ]]; then
    ledger "UPDATE backup_runs SET status='$1', finished_at=now(), bytes=$BYTES, \
checksum='$CHECKSUM', destination='$2', error_class='${3:-}' WHERE id='$RUN_ID'"
  fi
}

# Optional encryption BEFORE the upload (ADR-0063 §3: encrypt when the
# destination is shared; the key must not travel with the archive).
UPLOADED="$ARCHIVE"
if [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
  echo "==> Encrypting (age)"
  command -v age >/dev/null 2>&1 || { echo "age is not installed" >&2; status_finish "failed" "archive" "age-missing"; exit 1; }
  UPLOADED="$ARCHIVE.age"
  age -r "$BACKUP_AGE_RECIPIENT" -o "$UPLOADED" "$ARCHIVE"
  BYTES="$(stat -c%s "$UPLOADED" 2>/dev/null || stat -f%z "$UPLOADED")"
fi

# Off-host upload (ADR-0063 §2): the uploader rides this script, on the
# same run as the dump. A failed upload is a failed execution.
REMOTE="${BACKUP_REMOTE:-}"
if [[ -z "$REMOTE" ]]; then
  echo "==> No BACKUP_REMOTE set: archive is local-only (label this install non-DR)"
else
  NAME="$(basename "$UPLOADED")"
  echo "==> Uploading to $REMOTE"
  case "$REMOTE" in
    s3://*)
      if command -v aws >/dev/null 2>&1; then
        aws s3 cp "$UPLOADED" "$REMOTE/$NAME"
      else
        rclone copy "$UPLOADED" "$REMOTE/$NAME"
      fi
      ;;
    https://*blob.core.windows.net/*|https://*.blob.core.windows.net/*|az://*|azure://*)
      command -v azcopy >/dev/null 2>&1 || { echo "azcopy is not installed" >&2; status_finish "failed" "upload" "azcopy-missing"; exit 1; }
      azcopy copy "$UPLOADED" "$REMOTE/$NAME"
      ;;
    rclone:*)
      rclone copy "$UPLOADED" "${REMOTE#rclone:}"
      ;;
    *:*)
      # Bare rclone target (remote:path — rclone remotes always carry `:`).
      rclone copy "$UPLOADED" "$REMOTE"
      ;;
    *)
      echo "Unsupported BACKUP_REMOTE scheme: $REMOTE (use s3://, azblob URL, az://, azure:// or rclone remote:path)" >&2
      status_finish "failed" "upload" "bad-remote"
      exit 1
      ;;
  esac
fi

status_finish "ok" "$UPLOADED"
echo "==> Done: $UPLOADED"
[[ -n "$REMOTE" ]] && echo "    Off-host: $REMOTE/$NAME"
[[ -z "$REMOTE" ]] && echo "    Retention is manual: keep at least the last N archives off-machine."
