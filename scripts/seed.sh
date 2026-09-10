#!/bin/bash
# Seed taxonomy + starter job catalog into the dev DB (idempotent).
set -e
cd "$(dirname "$0")/../backend"
if [ -d venv ]; then source venv/bin/activate; fi
PYTHONPATH=$(pwd) python -m app.seeds.run
