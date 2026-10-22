#!/usr/bin/env bash
# Playwright E2E smoke: build SPA → scratch DB → boot the
# real server → run e2e/ specs → teardown.
#
# Env:
#   CAREER_DATABASE_URL       target scratch DB (default: neuronection_career_e2e on
#                      the dev Postgres :5433; created when the dev container
#                      runs)
#   SKIP_FRONTEND_BUILD=1  reuse frontend/dist as-is
#   E2E_PORT           server port (default 8111)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/worktree-env.sh
source "$ROOT/scripts/lib/worktree-env.sh"
dc_wt_load
PG_CONTAINER="${POSTGRES_CONTAINER:-career-postgres}"
PG_PORT="${POSTGRES_PORT:-5433}"
PORT="${E2E_PORT:-8111}"
if [[ -n "${E2E_DATABASE_URL:-}" ]]; then
  export CAREER_DATABASE_URL="$E2E_DATABASE_URL"
elif [[ "${CAREER_DATABASE_URL:-}" == */neuronection_career ]]; then
  export CAREER_DATABASE_URL="${CAREER_DATABASE_URL%/neuronection_career}/neuronection_career_e2e"
fi
export CAREER_DATABASE_URL="${CAREER_DATABASE_URL:-postgresql+asyncpg://neuronection_career_owner:career_dev_pw@127.0.0.1:${PG_PORT}/neuronection_career_e2e}"
export E2E_BASE_URL="http://127.0.0.1:${PORT}"
export CAREER_APP_ENV=test
export CAREER_SCHEDULER_ENABLED=false
# The mock provider is opt-in since plan 99.1 (mock rows are invisible to
# AI resolution without the knob) — the scratch DB starts unconfigured,
# so the mock carrier must be bootstrapped explicitly for the smoke suite.
export CAREER_MOCK_AI=1
# The e2e server loads `.env` (not `.env.test`), so the unit suite's
# CAREER_RATELIMIT_ENABLED=false never applies and back-to-back registrations
# can 429. Disable it here to keep the smoke suite deterministic.
# The gateway's AI limiter reads CAREER_RATELIMIT_AI directly (default 30/min
# — the suite makes far more mock calls than that, the LAST test files
# hit the cap and the turn 429s with "retry in 23s").
export CAREER_RATELIMIT_ENABLED=false
export CAREER_RATELIMIT_AI=0
# Notification reach (plan 117): the email transport captures messages as
# `.eml` files (never real SMTP) and the webhook SSRF hatch lets the spec's
# loopback receiver stand in for a vendor endpoint. Both are dev/test-only.
export CAREER_MAIL_TRANSPORT=file
export CAREER_MAIL_DIR="${E2E_MAIL_DIR:-/tmp/career-e2e-mail}"
export CAREER_WEBHOOK_ALLOW_PRIVATE_HOSTS=1
export E2E_MAIL_DIR="$CAREER_MAIL_DIR"
rm -rf "$CAREER_MAIL_DIR"
mkdir -p "$CAREER_MAIL_DIR"
# The extension-surface spec (plan 32 Phase 4) imports the reference
# mini-app through the local-git-source variant, confined (net_guard-style)
# to the sibling template repo when it is checked out.
DEFAULT_LOCAL_ROOT="$(printf '["%s"]' "$ROOT/../career-connector-template")"
export CAREER_EXTENSION_LOCAL_SOURCE_ROOTS="${CAREER_EXTENSION_LOCAL_SOURCE_ROOTS:-$DEFAULT_LOCAL_ROOT}"

cd "$ROOT"

echo ">>> resolving backend toolchain"
ALEMBIC_BIN=(uv run alembic)
PY_BIN=(uv run python)
PYTEST_BIN=(uv run pytest)
UVICORN_BIN=(uv run uvicorn)

if [[ "${SKIP_FRONTEND_BUILD:-0}" != "1" ]]; then
  echo ">>> building SPA"
  (cd frontend && npm run build)
fi

if [[ "$CAREER_DATABASE_URL" == *"neuronection_career_e2e" ]] && docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER"; then
  # Recreate the scratch DB — a stale seeded provider (pre CAREER_MOCK_AI gate)
  # pre-empts the bootstrap resolution and leaves the mock fixtures
  # unregistered (the smoke suite ran with generic answers, plan 99.1).
  docker exec "$PG_CONTAINER" psql -U neuronection_career_owner -d postgres -c \
    "DROP DATABASE IF EXISTS neuronection_career_e2e (FORCE)" 2>/dev/null \
    || docker exec "$PG_CONTAINER" psql -U neuronection_career_owner -d postgres \
      -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='neuronection_career_e2e' and pid <> pg_backend_pid(); commit;" \
      -c "DROP DATABASE IF EXISTS neuronection_career_e2e;"
  docker exec "$PG_CONTAINER" psql -U neuronection_career_owner -d postgres -c "CREATE DATABASE neuronection_career_e2e OWNER neuronection_career_owner;"
fi

echo ">>> migrating scratch DB"
(cd backend && "${ALEMBIC_BIN[@]}" upgrade head)

echo ">>> seeding catalog (idempotent)"
(cd backend && PYTHONPATH="$(pwd)" "${PY_BIN[@]}" -m app.seeds.run)

echo ">>> seeding the e2e posting"
(cd backend && PYTHONPATH="$(pwd)" "${PY_BIN[@]}" ../e2e/seed_posting.py)

echo ">>> seeding the e2e mock AI carrier (plan 118)"
(cd backend && PYTHONPATH="$(pwd)" "${PY_BIN[@]}" ../e2e/seed_ai.py)

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
# All specs by default; a subset passes through (E2E_SPECS="e2e/test_x.py").
"${PYTEST_BIN[@]}" ${E2E_SPECS:-e2e} -q
