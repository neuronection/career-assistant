#!/bin/sh
set -e

echo "Waiting for the database..."
python -c '
import os, socket, sys, time
from urllib.parse import urlparse
u = urlparse(os.environ.get("DATABASE_URL", ""))
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

echo "Running database migrations..."
alembic upgrade head

echo "Starting Career Assistant on ${API_HOST:-0.0.0.0}:${API_PORT:-8100}"
exec uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8100}"
