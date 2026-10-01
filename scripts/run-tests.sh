#!/bin/bash
# Backend test runner. Full suite by default, or pass a path.
# Runs in parallel via pytest-xdist (per-worker databases are created by
# tests/conftest.py automatically); PYTEST_XDIST=0 opts out, and
# PYTEST_XDIST_WORKERS overrides the worker count.
set -e
cd "$(dirname "$0")/../backend"
args=(tests/"${1:-}")
if uv run python -c "import xdist" >/dev/null 2>&1 && [[ ${PYTEST_XDIST:-1} != 0 ]]; then
  args+=(-n "${PYTEST_XDIST_WORKERS:-auto}")
fi
uv run pytest "${args[@]}"
