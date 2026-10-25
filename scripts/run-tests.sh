#!/bin/bash
# Backend test runner. Full suite by default, or pass a path.
# Runs in parallel via pytest-xdist (per-worker databases are created by
# tests/conftest.py automatically); PYTEST_XDIST=0 opts out, and
# PYTEST_XDIST_WORKERS overrides the worker count.
set -e
cd "$(dirname "$0")/.."
# Fresh clones carry only the tracked example (plan 126) — recreate the
# pytest env file so the first run needs zero manual steps. Idempotent.
if [[ ! -f backend/.env.test && -f backend/.env.test.example ]]; then
  cp backend/.env.test.example backend/.env.test
fi
# shellcheck source=scripts/lib/worktree-env.sh
source scripts/lib/worktree-env.sh
dc_wt_load
cd backend
if [[ -n "${DATABASE_URL_TEST:-}" ]]; then
  export CAREER_DATABASE_URL="$DATABASE_URL_TEST"
fi
args=(tests/"${1:-}")
if uv run python -c "import xdist" >/dev/null 2>&1 && [[ ${PYTEST_XDIST:-1} != 0 ]]; then
  args+=(-n "${PYTEST_XDIST_WORKERS:-auto}")
fi
uv run pytest "${args[@]}"
