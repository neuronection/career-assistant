#!/usr/bin/env bash
# check-extensions-structure — the D24 structure probe (ADR-0040 / plan 32
# Phase 1; BLOCKING since the Phase 9 closeout). Findings print as WARN;
# pass --strict to fail on any finding — the family-convergence workflow
# runs this probe with --strict, so a finding fails CI. Styled after the
# vendored check-family-convergence gate (patterns as data, loud output,
# self-describing).
#
# Probes:
#  1 scoped engine code only in the subsystem home — the pre-D24 paths are
#    gone (app/connectors/, services/search_providers.py,
#    services/mcp_bridge_service.py) and postings sync orchestration stays
#    in services/ (reference-arch: api thin → services orchestrate →
#    subsystem holds machinery)
#  2 no importlib of data-dir artifacts and no importlib under
#    app/extensions (D2's gate point: imported code never enters the
#    process) — extended Phase 3: no sys.path mutation under the
#    subsystem either (data_dir/extensions/<id>/<digest>/ content is
#    DATA: spawned, never imported), and lifecycle.py (the D24 home for
#    sources/consent/pins/GitOps) must exist
#  3 AI-layer MCP adapters stay in app/ai (ADR-0012 alignment gate R2):
#    fastmcp/mcp imports appear only under backend/app/ai/
#  4 vendored family contract modules exist at their ledgered paths
#    (backend/app/extensions/{polite_http,contract,conformance}.py +
#    contracts/extension-charter.json …) — drift vs the dev canonicals is
#    the dev repo's sync --check gate, not this probe
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STRICT=0
[[ "${1:-}" == "--strict" ]] && STRICT=1

findings=0
note() { echo "WARN: $1"; findings=$((findings + 1)); }
ok() { echo "ok:   $1"; }

# 1 — old paths gone, orchestration in place
for gone in \
  "backend/app/connectors" \
  "backend/app/services/search_providers.py" \
  "backend/app/services/mcp_bridge_service.py"; do
  if [ -e "$ROOT/$gone" ]; then
    note "pre-D24 path still present: $gone (engine code lives in backend/app/extensions/)"
  else
    ok "pre-D24 path absent: $gone"
  fi
done
if [ -f "$ROOT/backend/app/services/postings_service.py" ]; then
  ok "postings sync orchestration stays in services/ (postings_service.py)"
else
  note "services/postings_service.py missing — sync orchestration belongs in services/ (D24 rule 1)"
fi
if [ -f "$ROOT/backend/app/ai/mcp_client.py" ]; then
  ok "AI-layer MCP client stays in ai/ (mcp_client.py, ADR-0012)"
else
  note "backend/app/ai/mcp_client.py missing — the MCP client construction stays in ai/"
fi

# 2 — no dynamic code loading under the subsystem home (D2's gate point:
# imported artifacts are data, never importlib'd into the process; stdlib
# `importlib.metadata` entry-point discovery is NOT dynamic loading).
# Phase 3 extension: sys.path mutations are equally banned — landing
# data_dir/extensions/<id>/<digest>/ on sys.path would make the
# content-addressed clone importable, the exact hole D2 closes.
importlib_hits="$(grep -rn -E "importlib\.(import_module|machinery|util|reload)|SourceFileLoader|exec_module" "$ROOT/backend/app/extensions" 2>/dev/null | grep -v __pycache__ || true)"
if [ -n "$importlib_hits" ]; then
  note "importlib usage under app/extensions (imported code is never importlib'd — D2):"
  echo "$importlib_hits" | sed 's/^/      /'
else
  ok "no importlib under app/extensions (D2 gate point)"
fi
syspath_hits="$(grep -rn -E "sys\.path\.(append|insert)|PYTHONPATH" "$ROOT/backend/app/extensions" 2>/dev/null | grep -v __pycache__ || true)"
if [ -n "$syspath_hits" ]; then
  note "sys.path/PYTHONPATH mutation under app/extensions (data-dir content is spawned, never importable — D2):"
  echo "$syspath_hits" | sed 's/^/      /'
else
  ok "no sys.path mutation under app/extensions (imported content is data, never a module path)"
fi
if [ -f "$ROOT/backend/app/extensions/lifecycle.py" ]; then
  ok "lifecycle.py present (D24 home: sources, consent, pins, GitOps reconcile)"
else
  note "backend/app/extensions/lifecycle.py missing — the import layer lives there (D13/D22)"
fi

# 3 — fastmcp/mcp imports only under backend/app/ai/
mcp_hits="$(
  grep -rln -E '^\s*(from (fastmcp|mcp)|import (fastmcp|mcp))' "$ROOT/backend/app" 2>/dev/null \
  | grep -v __pycache__ | grep -v "^$ROOT/backend/app/ai/" || true)"
if [ -n "$mcp_hits" ]; then
  note "fastmcp/mcp imports outside app/ai/ (ADR-0012 alignment gate R2):"
  echo "$mcp_hits" | sed 's/^/      /'
else
  ok "fastmcp/mcp imports confined to app/ai/ (ADR-0012)"
fi

# 4 — vendored family contract set at ledgered paths
for vendored in \
  "backend/app/extensions/polite_http.py" \
  "backend/app/extensions/contract.py" \
  "backend/app/extensions/conformance.py" \
  "contracts/extension-charter.json" \
  "contracts/extension-manifest.schema.json" \
  "contracts/extension-sources.schema.json" \
  "contracts/capability-rpc.schema.json" \
  "contracts/capability-rpc.md" \
  "contracts/extension-contract.fixtures.json" \
  "contracts/polite_http.fixtures.json"; do
  if [ -f "$ROOT/$vendored" ]; then
    ok "vendored: $vendored"
  else
    note "vendored contract module missing: $vendored (run ../dev/scripts/sync-extension-contract.sh --project career-assistant)"
  fi
done

echo
if [ "$findings" -gt 0 ]; then
  echo "extensions structure: $findings finding(s)"
  if [ "$STRICT" -eq 1 ]; then
    exit 1
  fi
  echo "warning-level run (plan 32 Phase 9: CI invokes this probe --strict)"
  exit 0
fi
echo "extensions structure: OK"
