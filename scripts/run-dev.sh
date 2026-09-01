#!/bin/bash
# Career Assistant — development entrypoint (uniform family interface).
#
# Bootstraps the dev environment (venv, backend + frontend deps, .env) and
# then starts the whole dev group under honcho via Procfile.dev:
# backend :8100 (uvicorn --reload) + frontend :3100 (vite). A single Ctrl+C
# stops everything; if any process dies honcho exits loud.
#
# Requires the dev DB: docker compose -f docker/docker-compose.dev-db.yml up -d
#
# Usage:
#   ./scripts/run-dev.sh                  # bootstrap + start the honcho group
#   ./scripts/run-dev.sh --force          # free backend/frontend ports first
#   ./scripts/run-dev.sh --force-stop     # stop all career dev processes, exit
#   ./scripts/run-dev.sh --no-bootstrap   # skip venv/deps bootstrap, just start
#   ./scripts/run-dev.sh backend          # extra args pass through to honcho
#   ./scripts/run-dev.sh -h | --help      # print this help and exit
#
# Everything runs inside backend/venv — never the system Python (PEP 668).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
cd "$SCRIPT_DIR/.."
# shellcheck source=lib/dev-common.sh
source scripts/lib/dev-common.sh

VENV_DIR=backend/venv
BACKEND_PORT=8100
FRONTEND_PORT=3100
DB_PORT=5433

NO_BOOTSTRAP=false
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --force-stop)
      dc_pkill "honcho start -f Procfile.dev"
      dc_pkill "uvicorn app.main:app"
      dc_pkill "vite.*--port $FRONTEND_PORT"
      dc_kill_port "$BACKEND_PORT"
      dc_kill_port "$FRONTEND_PORT"
      dc_ok "All Career Assistant dev processes stopped."
      exit 0
      ;;
    --force)
      dc_kill_port "$BACKEND_PORT"
      dc_kill_port "$FRONTEND_PORT"
      ;;
    --no-bootstrap) NO_BOOTSTRAP=true ;;
    -h|--help) dc_help "$SCRIPT_PATH" ;;
    *) break ;;
  esac
  shift
done

if [[ ! -f .env ]]; then
  cp .env.example .env
  dc_warn "created .env from .env.example — review it before first run"
fi

if [[ "$NO_BOOTSTRAP" = false ]]; then
  dc_step "preparing backend environment"
  dc_ensure_venv "$VENV_DIR" backend/requirements.txt
  dc_ensure_node_deps frontend npm
fi
export PATH="$PWD/$VENV_DIR/bin:$PATH"

dc_check_port_free "$BACKEND_PORT" "backend"
dc_check_port_free "$FRONTEND_PORT" "frontend"
if ! dc_port_in_use "$DB_PORT"; then
  dc_warn "Postgres (port $DB_PORT) is not running; the backend will fail to connect."
  dc_warn "Start it via: docker compose -f docker/docker-compose.dev-db.yml up -d"
fi

dc_info "Starting Career Assistant dev group (backend :$BACKEND_PORT, frontend :$FRONTEND_PORT)"
dc_info "Press Ctrl+C to stop all services."
dc_exec_honcho Procfile.dev "$@"
