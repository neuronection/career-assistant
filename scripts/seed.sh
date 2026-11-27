#!/bin/bash
# Seed the reference banks, then install the released job-catalog pack (idempotent).
set -e
cd "$(dirname "$0")/../backend"
uv run python -m app.seeds.run
uv run python ../scripts/seed_pack_fixture.py
