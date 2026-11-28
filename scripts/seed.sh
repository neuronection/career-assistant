#!/bin/bash
# Seed system data, then install the released reference-banks and job-catalog packs (idempotent).
set -e
cd "$(dirname "$0")/../backend"
uv run python -m app.seeds.run
uv run python ../scripts/seed_pack_fixture.py
