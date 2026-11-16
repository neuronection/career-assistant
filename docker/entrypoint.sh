#!/bin/sh
# Entrypoint modes (ADR-0062 §3 / plan 64 §1.1): Compose picks the command,
# the image never guesses. Unknown mode fails closed.
#   migrate — one-shot provisioning as the owner role (app role + grants,
#             `vector` extension, Alembic, checkpoint schema, vector
#             spaces, re-grant), then exit. One container, no serving.
#   serve   — the web process. NEVER runs migrations or any DDL: the
#             schema was provisioned by the migrate job, which the
#             compose app service awaits (`service_completed_successfully`).
# Desktop (`python -m careerassistant`) does not use this entrypoint and
# keeps its local boot migrations, schedulers and SQLite checkpointer.
set -e

MODE="${1:-serve}"
case "$MODE" in
  migrate|serve) ;;
  *)
    echo "entrypoint: unknown mode '$MODE' — expected 'migrate' or 'serve'" >&2
    exit 2
    ;;
esac

echo "Waiting for the database..."
python -c '
import os, socket, sys, time
from urllib.parse import urlparse
u = urlparse(os.environ.get("CAREER_DATABASE_URL", ""))
host, port = u.hostname or "localhost", u.port or 5432
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    try:
        socket.create_connection((host, port), timeout=2).close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit(f"database not reachable at {host}:{port}")
'

cd /app/backend

if [ "$MODE" = "migrate" ]; then
  echo "Running one-shot provisioning (owner): roles, extensions, migrations, checkpoints, vector spaces..."
  python -m careerassistant migrate
  echo "Provisioning complete."
  exit 0
fi

echo "Preflight datastore check (read-only)..."
python -m careerassistant preflight

echo "Starting Career Assistant on ${CAREER_API_HOST:-0.0.0.0}:${CAREER_API_PORT:-8100} (serve: no migrations)"
exec uvicorn app.main:app --host "${CAREER_API_HOST:-0.0.0.0}" --port "${CAREER_API_PORT:-8100}"
