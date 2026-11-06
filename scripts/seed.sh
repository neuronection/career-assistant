#!/bin/bash
# Seed taxonomy + starter job catalog into the dev DB (idempotent).
set -e
cd "$(dirname "$0")/../backend"
uv run python -m app.seeds.run
