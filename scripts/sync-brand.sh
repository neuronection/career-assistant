#!/usr/bin/env bash
# Sync canonical brand assets to derived copies: assets/icon*.svg is the single
# source of truth; frontend/public/icon*.svg (Vite-served favicon + UI logos)
# are derived from it. Run after changing any asset in assets/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for f in "$ROOT"/assets/icon*.svg; do
  name="$(basename "$f")"
  cp "$f" "$ROOT/frontend/public/$name"
  echo "sync-brand: assets/$name -> frontend/public/$name"
done
