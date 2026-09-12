#!/usr/bin/env bash
# Playwright E2E smoke: build SPA → scratch DB → boot the
# real server → run e2e/ specs → teardown.
#
# Env:
#   DATABASE_URL       target scratch DB (default: career_e2e on the dev
#                      Postgres :5433; created when the dev container runs)
#   SKIP_FRONTEND_BUILD=1  reuse frontend/dist as-is
#   E2E_PORT           server port (default 8111)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${E2E_PORT:-8111}"
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://career:career_dev_pw@127.0.0.1:5433/career_e2e}"
export E2E_BASE_URL="http://127.0.0.1:${PORT}"
export APP_ENV=test
export SCHEDULER_ENABLED=false
# The e2e server loads `.env` (not `.env.test`), so the unit suite's
# RATE_LIMIT_ENABLED=false never applies and back-to-back registrations
# can 429. Disable it here to keep the smoke suite deterministic.
export RATE_LIMIT_ENABLED=false

cd "$ROOT"

echo ">>> resolving backend toolchain"
if [[ -x "$ROOT/backend/venv/bin/alembic" ]]; then
  ALEMBIC_BIN=("$ROOT/backend/venv/bin/alembic")
  PY_BIN=("$ROOT/backend/venv/bin/python")
  UVICORN_BIN=("$ROOT/backend/venv/bin/uvicorn")
else
  # CI installs into the global env — no venv checkout to lean on.
  ALEMBIC_BIN=(python3 -m alembic)
  PY_BIN=(python3)
  UVICORN_BIN=(python3 -m uvicorn)
fi

if [[ "${SKIP_FRONTEND_BUILD:-0}" != "1" ]]; then
  echo ">>> building SPA"
  (cd frontend && npm run build)
fi

if [[ "$DATABASE_URL" == *"career_e2e" ]] && docker ps --format '{{.Names}}' | grep -qx career-postgres; then
  docker exec career-postgres psql -U career -d postgres -tc \
    "select 1 from pg_database where datname='career_e2e'" | grep -q 1 ||
    docker exec career-postgres psql -U career -d postgres -c "create database career_e2e owner career;"
fi

echo ">>> migrating scratch DB"
(cd backend && "${ALEMBIC_BIN[@]}" upgrade head)

echo ">>> seeding catalog (idempotent)"
(cd backend && PYTHONPATH="$(pwd)" "${PY_BIN[@]}" -m app.seeds.run)

echo ">>> booting server on :${PORT}"
(cd backend && exec "${UVICORN_BIN[@]}" app.main:app --host 127.0.0.1 --port "$PORT" \
  > /tmp/career-e2e-server.log 2>&1) &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -fsS "$E2E_BASE_URL/health" > /dev/null 2>&1 && break
  sleep 1
done
curl -fsS "$E2E_BASE_URL/health" > /dev/null || { echo "server never became healthy"; exit 1; }

echo ">>> running e2e specs"
./backend/venv/bin/pytest e2e -q
