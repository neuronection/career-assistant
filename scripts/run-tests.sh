#!/bin/bash
# Backend test runner. Full suite by default, or pass a path.
# Runs two passes via pytest-xdist: the parallel-safe tests (`-m "not serial"`)
# concurrently, then the `serial` ones (not parallel-safe on the SQLite desktop
# profile) in one process. PYTEST_XDIST=0 opts out of both and keeps today's
# single serial pass; PYTEST_XDIST_WORKERS overrides the worker count.
# Per-worker databases and data/upload trees are created by
# tests/xdist_routing.py automatically.
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
target="${1:-}"
if [[ -z "$target" ]]; then
  selection="tests/"
elif [[ -e "$target" ]]; then
  selection="$target"
else
  selection="tests/$target"
fi
if uv run python -c "import xdist" >/dev/null 2>&1 && [[ ${PYTEST_XDIST:-1} != 0 ]]; then
  uv run pytest "$selection" -m "not serial" -n "${PYTEST_XDIST_WORKERS:-auto}"
  serial_status=0
  uv run pytest "$selection" -m serial || serial_status=$?
  if [[ $serial_status -ne 0 && $serial_status -ne 5 ]]; then
    exit $serial_status
  fi
else
  uv run pytest "$selection"
fi
