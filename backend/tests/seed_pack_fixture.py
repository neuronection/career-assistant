"""Plan 224 S4: the published job-catalog pack as the shared test fixture.

The app bundles no catalog, so tests that need jobs, taxonomy or starter
paths apply the released pack instead. The pack bytes are read once per
worker process; rows are written inside each test's own transaction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache, lru_cache
from pathlib import Path

from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.manifest import compute_files_digest
from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import SeedSource, SeedSourceVersion
from app.services.seeds.applier import SeedApplyService
from app.storage.object_storage import LocalObjectStore, StorageConfig

PACK_DIR = (
    Path(__file__).parent / "fixtures" / "seed_packs" / "packs" / "neuronection" / "job-catalog"
)


@cache
def pack_items(relative: str) -> tuple[dict, ...]:
    """One item envelope of the fixture pack (e.g. ``job_relations/relations.json``)."""
    envelope = json.loads((PACK_DIR / "items" / relative).read_text(encoding="utf-8"))
    return tuple(envelope["items"])


@dataclass(frozen=True)
class FixtureCatalog:
    """The applied fixture provider, its version and its pack store."""

    source: SeedSource
    version: SeedSourceVersion
    store: SeedPackStore


@lru_cache(maxsize=1)
def catalog_pack_files() -> dict[str, bytes]:
    """The fixture pack's files, parsed once per worker process."""
    return {
        path.relative_to(PACK_DIR).as_posix(): path.read_bytes()
        for path in sorted(PACK_DIR.rglob("*.json"))
    }


@lru_cache(maxsize=1)
def taxonomy_pack_files() -> dict[str, bytes]:
    """The pack restricted to its skills and interest tags.

    A profile-only test needs the tags its payload references, not 45 jobs:
    applying the jobs would enqueue vector work and fit rows behind the
    test's back. The bytes are the published ones; only the manifest's file
    list is narrowed.
    """
    files = dict(catalog_pack_files())
    keep = {"items/skills/skills.json", "items/interest_tags/interests.json"}
    manifest = json.loads(files["manifest.json"])
    manifest["item_files"] = [ref for ref in manifest["item_files"] if ref["path"] in keep]
    files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    return files


def fixture_store(root: Path) -> SeedPackStore:
    """A content-addressed store rooted in the test's temporary directory."""
    return SeedPackStore(
        LocalObjectStore(
            StorageConfig(
                backend="local",
                entrypoint="server",
                local_root=root / "uploads",
                max_object_mb=10,
            ).validate()
        )
    )


async def _apply_pack(db, root: Path, files: dict[str, bytes], *, name: str) -> FixtureCatalog:
    store = fixture_store(root)
    digest = compute_files_digest(files)
    manifest = json.loads(files["manifest.json"])
    source = SeedSource(
        name=name,
        kind="file",
        uri=digest,
        priority=100,
        trust_tier="operator",
        enabled=True,
        refresh_minutes=0,
    )
    db.add(source)
    await db.flush()
    store.put(source.id, digest, build_pack_archive(files))
    version = SeedSourceVersion(
        source_id=source.id,
        digest=digest,
        manifest=manifest,
        pack_version=str(manifest["version"]),
        schema_version=str(manifest["schema_version"]),
        status="approved",
        approved_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()
    result = await SeedApplyService(db, packs=store, side_effects=False).apply(source, version)
    if result.status not in ("applied", "noop"):
        raise AssertionError(f"fixture catalog pack failed to apply: {result.as_dict()}")
    return FixtureCatalog(source=source, version=version, store=store)


async def apply_catalog_pack(db, root: Path) -> FixtureCatalog:
    """Apply the whole job-catalog fixture pack as an operator file provider."""
    return await _apply_pack(db, root, catalog_pack_files(), name="Fixture job catalog")


async def apply_taxonomy_pack(db, root: Path) -> FixtureCatalog:
    """Apply only the pack's skills and interest tags (profile fixtures)."""
    return await _apply_pack(db, root, taxonomy_pack_files(), name="Fixture job taxonomy")
