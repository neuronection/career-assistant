#!/usr/bin/env python3
"""Regenerate the shipped official seed-repository snapshot (plan 218).

Startup never fetches, so boot registers the official tiles from a snapshot
committed as app data: ``app/data/seed_packs/official/index.json``. Run this
script when the pinned ref moves or the official repository gains a pack:

    cd backend && uv run python scripts/sync_official_index.py \
        --repo https://github.com/neuronection/career-assistant-seeds.git \
        --ref v2026.11.25.3

Existing entries keep their curated display name; a new pack gets
``<publisher> — <pack slug>``. The repository/ref are read from the current
snapshot when omitted. The read goes through the same public-HTTPS git
transport the app uses (anonymous, pinned ref, no hooks/submodules).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.seed_pack.manifest import parse_repo_index
from app.services.seeds.git_transport import GitTransport

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app" / "data" / "seed_packs" / "official" / "index.json"


def _current() -> dict:
    if TARGET.exists():
        return json.loads(TARGET.read_text(encoding="utf-8"))
    return {}


def _label(publisher, pack_id: str) -> str:
    slug = pack_id
    prefix = f"{publisher.id}-"
    if slug.startswith(prefix):
        slug = slug[len(prefix) :]
    return f"{publisher.name} — {slug}"[:120]


async def run(repo: str, ref: str) -> dict:
    raw, commit = await GitTransport().discover(repo, ref)
    index = parse_repo_index(raw)
    previous = {
        str(pack.get("path")): str(pack.get("name"))
        for pack in _current().get("packs", [])
        if pack.get("path") and pack.get("name")
    }
    payload = {
        "contract": "career-official-seed-index",
        "schema": 1,
        "repository": repo,
        "ref": ref,
        "commit": commit,
        "publisher": {"id": index.publisher.id, "name": index.publisher.name},
        "packs": [
            {
                "id": pack.id,
                "name": previous.get(pack.path) or _label(index.publisher, pack.id),
                "path": pack.path,
            }
            for pack in index.packs
        ],
    }
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    current = _current()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=current.get("repository"))
    parser.add_argument("--ref", default=current.get("ref"))
    args = parser.parse_args()
    if not args.repo or not args.ref:
        parser.error("--repo and --ref are required when no snapshot exists")
    payload = asyncio.run(run(args.repo, args.ref))
    print(f"wrote {TARGET} ({len(payload['packs'])} packs @ {args.ref})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
