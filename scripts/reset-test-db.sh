#!/usr/bin/env bash
# Reset the career_test database.
#
# The full backend suite fails with confusing ghost errors when the
# shared career_test DB holds committed rows from an earlier run
# (e.g. `relation "users" does not exist` on an empty DB, or seed/state
# mismatches). This script is the documented recovery: terminate
# connections, drop + recreate, re-apply migrations.
#
# Usage: scripts/reset-test-db.sh [--migrate]
#   default: drop + recreate only (CI-style runs migrate themselves)
#   --migrate: also run `alembic upgrade head` against the test DB
set -euo pipefail

CONTAINER="${CAREER_PG_CONTAINER:-career-postgres}"
PG_USER="${CAREER_PG_USER:-career}"
PG_PASSWORD="${CAREER_PG_PASSWORD:-career_dev_pw}"
PORT="${CAREER_PG_PORT:-5433}"
DB="career_test"
MIGRATE=0
[[ "${1:-}" == "--migrate" ]] && MIGRATE=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo ">>> dropping and recreating ${DB} in ${CONTAINER}"
docker exec "$CONTAINER" psql -U "$PG_USER" -d postgres -c \
  "select pg_terminate_backend(pid) from pg_stat_activity where datname='${DB}' and pid <> pg_backend_pid();"
docker exec "$CONTAINER" psql -U "$PG_USER" -d postgres \
  -c "drop database if exists ${DB};" -c "create database ${DB} owner ${PG_USER};"

if [[ "$MIGRATE" -eq 1 ]]; then
  echo ">>> applying migrations to ${DB}"
  (cd "$ROOT/backend" && DATABASE_URL="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PORT}/${DB}" \
    ./venv/bin/alembic upgrade head)
fi

echo ">>> ${DB} is fresh"
