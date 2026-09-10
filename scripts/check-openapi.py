#!/usr/bin/env python3
"""OpenAPI contract gate.

Dumps the FastAPI schema via ``create_app().openapi()``, normalizes it
(sorted keys, ``info.version`` stripped — release churn is not contract
drift) and either rewrites the committed contract (``--update``, run in
the SAME commit as the endpoint change) or exits 1 with a unified diff
when the live schema drifted (``--check``, the CI default).

Stdlib only; imports the app from ``backend/`` relative to this file.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = REPO_ROOT / "contracts" / "openapi.json"
BACKEND = REPO_ROOT / "backend"


def _sorted(node):
    if isinstance(node, dict):
        return {key: _sorted(node[key]) for key in sorted(node)}
    if isinstance(node, list):
        return [_sorted(item) for item in node]
    return node


def normalized_schema() -> dict:
    sys.path.insert(0, str(BACKEND))
    from app.main import create_app

    schema = create_app().openapi()
    schema.setdefault("info", {}).pop("version", None)
    return _sorted(schema)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--update",
        action="store_true",
        help="rewrite contracts/openapi.json (deliberate contract change)",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="fail when the live schema differs from the contract (default)",
    )
    args = parser.parse_args()

    live = normalized_schema()
    rendered = json.dumps(live, indent=2, sort_keys=False) + "\n"

    if args.update or not CONTRACT.is_file():
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(rendered, encoding="utf-8")
        print(f"contracts/openapi.json written ({len(live.get('paths', {}))} paths)")
        return 0

    committed = CONTRACT.read_text(encoding="utf-8")
    if committed == rendered:
        print(f"openapi contract OK ({len(live.get('paths', {}))} paths)")
        return 0

    diff = "\n".join(
        difflib.unified_diff(
            committed.splitlines(),
            rendered.splitlines(),
            fromfile="contracts/openapi.json (committed)",
            tofile="live schema",
            lineterm="",
        )
    )
    print("OpenAPI contract drift detected:", file=sys.stderr)
    print(diff, file=sys.stderr)
    print(
        "\nIf this change is deliberate, regenerate the contract in the "
        "same commit:\n  python scripts/check-openapi.py --update",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
