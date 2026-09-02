#!/bin/bash
# Career Assistant — development entrypoint (uniform family interface).
#
# Bootstraps the dev environment (venv, backend + frontend deps, .env) and
# then starts the whole dev group under honcho via Procfile.dev:
# backend :8100 (uvicorn --reload) + frontend :3100 (vite). A single Ctrl+C
# stops everything; if any process dies honcho exits loud.
#
# Starts the dev DB (docker compose) automatically if it is not running, and
# applies backend Alembic migrations before startup (unless --no-migrate).
#
# Usage:
#   ./scripts/run-dev.sh                  # bootstrap + start the honcho group
#   ./scripts/run-dev.sh --force          # free backend/frontend ports first
#   ./scripts/run-dev.sh --force-stop     # stop all career dev processes, exit
#   ./scripts/run-dev.sh --reset [--yes]
#                                         # wipe the dev DB volume, re-migrate
#                                         # and re-seed before starting;
#                                         # destructive — confirmation prompt,
#                                         # --yes to skip it
#   ./scripts/run-dev.sh --no-bootstrap   # skip venv/deps bootstrap, just start
#   ./scripts/run-dev.sh --no-migrate     # skip the alembic upgrade step
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

DEV_DB_COMPOSE="docker/docker-compose.dev-db.yml"

RESET=0
RESET_ARGS=()
NO_BOOTSTRAP=false
NO_MIGRATE=false
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
    --reset) RESET=1 ;;
    --yes) RESET_ARGS+=(--yes) ;;
    --no-bootstrap) NO_BOOTSTRAP=true ;;
    --no-migrate) NO_MIGRATE=true ;;
    -h|--help) dc_help "$SCRIPT_PATH" ;;
    *) break ;;
  esac
  shift
done

if [[ "$RESET" -eq 0 && ${#RESET_ARGS[@]} -gt 0 ]]; then
  dc_die "--yes only makes sense together with --reset"
fi

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

dc_start_dev_db() {
  if dc_port_in_use "$DB_PORT"; then
    return 0
  fi
  dc_step "starting dev DB (postgres :$DB_PORT, redis :6380)"
  docker compose -f "$DEV_DB_COMPOSE" up -d
  for _ in $(seq 1 30); do
    if docker ps --filter "name=career-postgres" --filter "health=healthy" --format '{{.Names}}' | grep -q career-postgres; then
      dc_ok "Dev DB is healthy."
      return 0
    fi
    sleep 1
  done
  dc_die "dev DB did not become healthy within 30s — check: docker compose -f $DEV_DB_COMPOSE logs postgres"
}

dc_migrate() {
  if [[ "$NO_MIGRATE" = true ]]; then
    dc_warn "skipping alembic upgrade (--no-migrate)"
    return 0
  fi
  dc_step "applying backend migrations"
  (cd backend && PYTHONPATH="$(pwd)" alembic upgrade head) || dc_die "alembic upgrade failed — see output above"
}

dc_reset_db() {
  dc_kill_port "$BACKEND_PORT"
  dc_kill_port "$FRONTEND_PORT"
  if [[ ${RESET_ARGS[*]} != *--yes* ]]; then
    dc_warn "This will DELETE the dev database volume (career_postgres_data) and all local dev data."
    read -r -p "Type 'reset' to continue: " reply
    [[ "$reply" == "reset" ]] || dc_die "aborted"
  fi
  dc_step "stopping dev DB containers and removing volumes"
  docker compose -f "$DEV_DB_COMPOSE" down -v
}

if [[ "$RESET" -eq 1 ]]; then
  dc_reset_db
fi

dc_start_dev_db
dc_migrate

dc_step "seeding taxonomy + starter job catalog (idempotent)"
bash scripts/seed.sh || dc_die "seeding failed — see output above"

dc_check_port_free "$BACKEND_PORT" "backend"
dc_check_port_free "$FRONTEND_PORT" "frontend"

dc_info "Starting Career Assistant dev group (backend :$BACKEND_PORT, frontend :$FRONTEND_PORT)"
dc_info "Press Ctrl+C to stop all services."
dc_exec_honcho Procfile.dev "$@"
