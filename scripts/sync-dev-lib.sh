#!/usr/bin/env bash
# Sync the canonical dev-script library to the sibling assistant repos.
# scripts/lib/dev-common.sh in THIS repo is the single source of truth; the
# copies in study-assistant and health-assistant/core are derived (like
# frontend/public brand assets). Run after editing the canonical copy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/scripts/lib/dev-common.sh"

TARGETS=(
  "$ROOT/../study-assistant/scripts/lib"
  "$ROOT/../health-assistant/core/scripts/lib"
)

for dir in "${TARGETS[@]}"; do
  if [[ ! -d "$(dirname "$dir")" ]]; then
    echo "sync-dev-lib: skipping $(dirname "$dir") (sibling repo not checked out)"
    continue
  fi
  mkdir -p "$dir"
  cp "$SRC" "$dir/dev-common.sh"
  echo "sync-dev-lib: scripts/lib/dev-common.sh -> $dir/dev-common.sh"
done
