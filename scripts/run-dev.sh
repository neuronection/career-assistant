#!/bin/bash
# Career Assistant — development entrypoint (uniform family interface).
#
# Desktop-first (ADR-0023): the default mode mirrors the shipped desktop
# app — the local SQLite profile (platform data dir, as bootstrapped by
# `python -m careerassistant`) + desktop identity (open auth, DIM owner;
# no login UI) — then backend :8100 (uvicorn --reload) + frontend :3100
# (vite) as one honcho group (Procfile.dev). A single Ctrl+C stops
# everything; if any process dies honcho exits loud. No Docker needed.
# Desktop dev binds loopback only (127.0.0.1) — the ungated open-auth API
# must never face the network; `--web` keeps the 0.0.0.0 LAN binding.
#
# ./scripts/run-dev.sh --web switches to server/web dev (the pre-0023
# behavior, unchanged): Postgres dev DB (docker compose, :5433) + server
# identity (login/register UI), alembic migrations + scripts/seed.sh.
#
# Usage:
#   ./scripts/run-dev.sh                  # desktop dev (SQLite, open auth)
#   ./scripts/run-dev.sh --web            # server dev (Postgres + auth)
#   ./scripts/run-dev.sh --force          # free backend/frontend ports first
#   ./scripts/run-dev.sh --force-stop     # stop all career dev processes, exit
#   ./scripts/run-dev.sh --reset [--yes]  # desktop: wipe the local SQLite
#                                         # profile (db + uploads; backups
#                                         # kept); --web: wipe the dev DB
#                                         # volume — destructive; confirmation
#                                         # prompt, --yes to skip it
#   ./scripts/run-dev.sh --no-bootstrap   # skip venv/deps bootstrap, just start
#   ./scripts/run-dev.sh --no-migrate     # skip schema setup: desktop skips
#                                         # the `careerassistant seed`
#                                         # bootstrap, web skips alembic
#                                         # (web seed still runs)
#   ./scripts/run-dev.sh --mock-ai        # opt in to the built-in mock AI
#                                         # provider (MOCK_AI=1) so AI features
#                                         # work offline; default is off (AI
#                                         # endpoints 503 until a real provider
#                                         # is configured in Settings)
#   ./scripts/run-dev.sh backend          # extra args pass through to honcho
#   ./scripts/run-dev.sh -h | --help      # print this help and exit
#
# Everything runs inside backend/venv — never the system Python (PEP 668).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
cd "$SCRIPT_DIR/.."
# shellcheck source=scripts/lib/dev-common.sh
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
WEB=false
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
    --web) WEB=true ;;
    --mock-ai)
      export MOCK_AI=1
      dc_warn "mock AI provider enabled (MOCK_AI=1) — scores/rationales are synthetic"
      ;;
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

if [[ "$WEB" = true ]]; then
  # Server/web dev — the pre-ADR-0023 behavior, unchanged. Explicit env
  # beats .env (pydantic: OS environment wins over env_file), so the mode
  # is deterministic regardless of what .env pins. Keeps the historical
  # LAN binding (device testing); the identity is server + authenticated.
  export CAREER_IDENTITY_MODE=server
  : "${DATABASE_URL:=postgresql+asyncpg://career:career_dev_pw@127.0.0.1:5433/career}"
  export DATABASE_URL
  export CA_DEV_HOST="${CA_DEV_HOST:-0.0.0.0}" CA_VITE_HOST="${CA_VITE_HOST:-0.0.0.0}"
  dc_info "web mode     → identity: server, database: postgres @127.0.0.1:$DB_PORT, bind: $CA_DEV_HOST"
else
  # Desktop dev (ADR-0023): export exactly what the desktop entrypoint
  # (`python -m careerassistant` → app.local.bootstrap_environment) would
  # setdefault — local SQLite profile + desktop identity. Resolving the
  # data dir through app.local keeps dev on the same platform-default
  # profile the installed desktop app uses.
  #
  # The shell-less desktop API is UNGATED (no X-Shell-Token gate without
  # a shell) and runs open-auth DIM — so it must bind loopback only, like
  # the shipped desktop app's server does.
  DATA_DIR="$(cd backend && PYTHONPATH="$(pwd)" python -c 'from app.local import default_data_dir; print(default_data_dir())')"
  export DATA_DIR
  export CAREER_IDENTITY_MODE=desktop
  export DATABASE_URL="sqlite+aiosqlite:///$DATA_DIR/career-assistant.db"
  export UPLOAD_DIR="$DATA_DIR/uploads"
  export CA_DEV_HOST="${CA_DEV_HOST:-127.0.0.1}" CA_VITE_HOST="${CA_VITE_HOST:-localhost}"
  dc_info "desktop mode → identity: desktop, database: $DATABASE_URL, bind: $CA_DEV_HOST"
  #
  # honcho re-applies the repo .env OVER our exports in the child env
  # (`e.update(p.env)`) — its DATABASE_URL/POSTGRES_*/REDIS_URL are the
  # WEB dev values and would silently point the desktop server at
  # Postgres. Filter them out into a dedicated env file for honcho (-e).
  DEV_ENV_FILE=".env.dev-desktop.local"
  grep -vE '^(DATABASE_URL|POSTGRES_[A-Z_]+|REDIS_URL)=' .env \
    > "$DEV_ENV_FILE" || true
  dc_info "env file    → $DEV_ENV_FILE (web-only keys filtered out)"
fi

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

dc_bootstrap_desktop() {
  # The desktop boot path exactly: corrupt-DB guard + migrations + the
  # idempotent starter catalog, against the local SQLite profile.
  if [[ "$NO_MIGRATE" = true ]]; then
    dc_warn "skipping desktop migrations + seed (--no-migrate)"
    return 0
  fi
  dc_step "applying desktop migrations + starter catalog (SQLite profile)"
  (cd backend && PYTHONPATH="$(pwd)" python -m careerassistant seed) \
    || dc_die "desktop bootstrap failed — see output above"
}

dc_ensure_pdf_engine() {
  # Plan 76: dev parity with the desktop bundles — the printed-PDF page
  # count (polish gate, lint, export) needs playwright + the Chromium
  # headless shell. Offline-tolerant: degrade with a warning, never block.
  dc_step "ensuring the PDF engine (playwright + chromium headless shell)"
  if ! "$VENV_DIR/bin/python" -c "import playwright" >/dev/null 2>&1; then
    "$VENV_DIR/bin/pip" install -q -r backend/requirements-pdf.txt \
      || { dc_warn "playwright install failed — PDF export/page counts degrade to estimates"; return 0; }
  fi
  if ls "$HOME/.cache/ms-playwright"/chromium_headless_shell-* >/dev/null 2>&1; then
    return 0
  fi
  "$VENV_DIR/bin/playwright" install chromium --only-shell \
    || dc_warn "chromium download failed — PDF export/page counts degrade to estimates (offline?)"
}

dc_reset_web() {
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

dc_reset_desktop() {
  dc_kill_port "$BACKEND_PORT"
  dc_kill_port "$FRONTEND_PORT"
  if [[ ${RESET_ARGS[*]} != *--yes* ]]; then
    dc_warn "This will DELETE the local desktop SQLite profile and all its data:"
    dc_warn "  $DATA_DIR (career-assistant.db + uploads; backups are kept)"
    read -r -p "Type 'reset' to continue: " reply
    [[ "$reply" == "reset" ]] || dc_die "aborted"
  fi
  dc_step "removing the local desktop SQLite profile"
  rm -f "$DATA_DIR/career-assistant.db" \
        "$DATA_DIR/career-assistant.db-wal" \
        "$DATA_DIR/career-assistant.db-shm"
  rm -rf "$DATA_DIR/uploads"
}

if [[ "$RESET" -eq 1 ]]; then
  if [[ "$WEB" = true ]]; then dc_reset_web; else dc_reset_desktop; fi
fi

if [[ "$WEB" = true ]]; then
  dc_start_dev_db
  dc_migrate
fi
dc_ensure_pdf_engine

if [[ "$WEB" = true ]]; then
  dc_step "seeding taxonomy + starter job catalog (idempotent)"
  bash scripts/seed.sh || dc_die "seeding failed — see output above"
else
  dc_bootstrap_desktop
fi

dc_check_port_free "$BACKEND_PORT" "backend"
dc_check_port_free "$FRONTEND_PORT" "frontend"

dc_info "Starting Career Assistant dev group (backend :$BACKEND_PORT, frontend :$FRONTEND_PORT)"
dc_info "Press Ctrl+C to stop all services."
if [[ "$WEB" = true ]]; then
  dc_exec_honcho Procfile.dev "$@"
else
  # -e: honcho must load the FILTERED env file, not the repo .env whose
  # web-only DATABASE_URL/POSTGRES_*/REDIS_URL would override the desktop
  # exports above (honcho applies env-file values over the inherited env).
  dc_exec_honcho Procfile.dev -e "$DEV_ENV_FILE" "$@"
fi
