#!/bin/bash
# MatchJobAssistant — start backend + frontend as one process group (honcho).
# Requires the dev DB: docker compose -f docker/docker-compose.dev-db.yml up -d
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then cp .env.example .env; fi

# Everything runs inside backend/venv — never the system Python (PEP 668).
VENV_DIR=backend/venv
if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi
VENV_PY="$VENV_DIR/bin/python"

if ! "$VENV_PY" -c "import honcho" >/dev/null 2>&1; then
  "$VENV_PY" -m pip install --disable-pip-version-check -q honcho
fi
if ! "$VENV_PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  "$VENV_PY" -m pip install --disable-pip-version-check -q -r backend/requirements.txt
fi

exec "$VENV_DIR/bin/honcho" start -f Procfile.dev "$@"
