"""Canonical pack export (plan 218 D8).

Export re-serializes a pack deterministically: sorted keys, two-space indent,
items ordered by ``seed_key``, and refreshed per-file sha256 entries in the
manifest. Exporting an already-exported pack is byte-identical, which is the
drift gate's round-trip.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from app.core.seed_pack.errors import ITEM_FILE_INVALID, PATH_DENIED, SeedPackError
from app.core.seed_pack.manifest import (
    ParsedPack,
    compute_pack_digest,
    parse_pack,
    sha256_hex,
)


def read_pack_dir(path: Path) -> dict[str, bytes]:
    """Read a pack directory's manifest and item files (no archives, no code)."""
    root = path.resolve()
    if not root.is_dir():
        raise SeedPackError(PATH_DENIED, f"not a directory: {path}")
    files: dict[str, bytes] = {}
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise SeedPackError(PATH_DENIED, f"manifest.json is missing under {path}")
    files["manifest.json"] = manifest.read_bytes()
    items = root / "items"
    if items.is_dir():
        for candidate in sorted(items.rglob("*.json")):
            if candidate.is_symlink():
                raise SeedPackError(PATH_DENIED, str(candidate))
            relative = candidate.relative_to(root).as_posix()
            files[relative] = candidate.read_bytes()
    return files


def canonical_export(files: Mapping[str, bytes]) -> tuple[dict[str, bytes], ParsedPack, str]:
    """Return canonical files, the freshly parsed pack and its digest."""
    parsed = parse_pack(files)
    manifest = json.loads(json.dumps(parsed.manifest_raw))
    exported: dict[str, bytes] = {}
    refs: list[dict[str, str]] = []
    for entry in manifest["item_files"]:
        path = entry["path"]
        payload = json.loads(files[path])
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise SeedPackError(ITEM_FILE_INVALID, path)
        payload["items"] = sorted(payload["items"], key=lambda item: str(item.get("seed_key", "")))
        data = (
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8")
            + b"\n"
        )
        exported[path] = data
        refs.append({"path": path, "sha256": sha256_hex(data)})
    manifest["item_files"] = refs
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    ordered: dict[str, bytes] = {"manifest.json": manifest_bytes}
    for path in sorted(exported):
        ordered[path] = exported[path]
    digest = compute_pack_digest(
        manifest, [(entry["path"], ordered[entry["path"]]) for entry in refs]
    )
    return ordered, parse_pack(ordered), digest


def write_export(files: Mapping[str, bytes], out: Path) -> None:
    root = out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        target = (root / relative).resolve()
        if root not in target.parents and target != root:
            raise SeedPackError(PATH_DENIED, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


__all__ = ["canonical_export", "read_pack_dir", "write_export"]
