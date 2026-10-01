#!/usr/bin/env bash
# Seed the Career Assistant demo workspace used for UI capture.
# Idempotent: initializes the demo DB on first run (empty target only),
# plain reseed afterwards. The seeder itself refuses any target that is
# not a demo instance — see scripts/seed-demo.py for the guard details.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${CA_SEED_PYTHON:-$ROOT/.venv/bin/python}"
DEMO_DIR="${CA_DEMO_DIR:-$ROOT/dev/demo-data}"

if [[ ! -f "$DEMO_DIR/career.sqlite3" ]]; then
  exec "$PY" "$ROOT/scripts/seed-demo.py" --demo-dir "$DEMO_DIR" --init-demo
fi
exec "$PY" "$ROOT/scripts/seed-demo.py" --demo-dir "$DEMO_DIR"
