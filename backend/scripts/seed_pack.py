"""Seed-pack authoring CLI: ``pack``, ``export`` and ``check`` (plan 218 D8).

Run from ``backend/`` with the project environment active:

    python scripts/seed_pack.py check ../career-assistant-seeds/packs/neuronection/greece-ats
    python scripts/seed_pack.py pack  <pack-dir> --out <file.zip>
    python scripts/seed_pack.py export <pack-dir> --out <dir>

Every command validates through the same app-side parser the sync lane uses,
so an authored pack cannot pass the CLI and fail the app.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.export import (
    canonical_export,
    read_pack_dir,
    write_export,
)
from app.core.seed_pack.manifest import parse_pack


def _check(path: Path) -> int:
    parsed = parse_pack(read_pack_dir(path))
    counts: dict[str, int] = {}
    for item in parsed.items:
        counts[item.item_type] = counts.get(item.item_type, 0) + 1
    summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "no items"
    print(f"OK {parsed.manifest.id} {parsed.manifest.version} {parsed.digest} ({summary})")
    return 0


def _pack(path: Path, out: Path | None) -> int:
    files = read_pack_dir(path)
    parsed = parse_pack(files)
    target = out or path / f"{parsed.manifest.id}-{parsed.manifest.version}.zip"
    target.write_bytes(build_pack_archive(files))
    print(f"{target} {parsed.digest}")
    return 0


def _export(path: Path, out: Path) -> int:
    exported, parsed, digest = canonical_export(read_pack_dir(path))
    write_export(exported, out)
    print(f"{out} {parsed.manifest.id} {parsed.manifest.version} {digest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="seed_pack", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="validate a pack directory")
    check.add_argument("path", type=Path)

    pack = commands.add_parser("pack", help="write a deterministic pack zip")
    pack.add_argument("path", type=Path)
    pack.add_argument("--out", type=Path, default=None)

    export = commands.add_parser("export", help="write a canonical packed tree")
    export.add_argument("path", type=Path)
    export.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return _check(args.path)
        if args.command == "pack":
            return _pack(args.path, args.out)
        return _export(args.path, args.out)
    except SeedPackError as exc:
        print(f"ERROR {exc.code}: {exc.detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
