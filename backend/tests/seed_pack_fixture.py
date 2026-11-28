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
from app.core.seed_pack.manifest import compute_files_digest, sha256_hex
from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import SeedSource, SeedSourceVersion
from app.services.seeds.applier import SeedApplyService
from app.storage.object_storage import LocalObjectStore, StorageConfig

PACK_DIR = (
    Path(__file__).parent / "fixtures" / "seed_packs" / "packs" / "neuronection" / "job-catalog"
)

CATALOG_MIN_JOBS = ("software-developer", "data-scientist", "nurse")


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


def _referenced_keys(keys: set[str], rows_by_key: dict[str, dict], field: str) -> set[str]:
    """Close ``keys`` over a ``field`` link (e.g. skill/parent_key chains)."""
    pending = list(keys)
    while pending:
        row = rows_by_key.get(pending.pop())
        parent = (row or {}).get(field)
        if parent and parent not in keys:
            keys.add(parent)
            pending.append(parent)
    return keys


@lru_cache(maxsize=1)
def catalog_min_files() -> dict[str, bytes]:
    """The pack narrowed to a few jobs and everything they reference.

    Tests that only need "a job exists" (and the taxonomy their postings
    resolve against) apply ~30 items instead of the full 190. Job families,
    skills, interest tags, relations and career paths stay referentially
    closed, and every rewritten item file carries its new sha256.
    """
    files = dict(catalog_pack_files())
    jobs = [item for item in pack_items("job_types/jobs.json") if item["code"] in CATALOG_MIN_JOBS]
    codes = {job["code"] for job in jobs}
    paths = [item for item in pack_items("career_paths/paths.json") if item["job"] in codes]
    relations = [
        item
        for item in pack_items("job_relations/relations.json")
        if item["from"] in codes and item["to"] in codes
    ]
    families = {item["key"]: item for item in pack_items("job_families/families.json")}
    family_keys = {job["family_key"] for job in jobs}
    skills = {ref["skill_key"] for job in jobs for ref in job.get("skills") or []}
    for path in paths:
        family_keys.update(
            step["family_key"] for step in path.get("steps") or [] if step.get("family_key")
        )
        skills.update(
            step["skill_key"] for step in path.get("steps") or [] if step.get("skill_key")
        )
    skill_rows = {item["key"]: item for item in pack_items("skills/skills.json")}
    interest_keys = {key for job in jobs for key in job.get("interests") or []}
    _referenced_keys(family_keys, families, "parent_key")
    _referenced_keys(skills, skill_rows, "parent_key")

    kept = {
        "items/job_families/families.json": [
            item for key, item in families.items() if key in family_keys
        ],
        "items/skills/skills.json": [item for key, item in skill_rows.items() if key in skills],
        "items/interest_tags/interests.json": [
            item
            for item in pack_items("interest_tags/interests.json")
            if item["key"] in interest_keys
        ],
        "items/job_types/jobs.json": jobs,
        "items/career_paths/paths.json": paths,
        "items/job_relations/relations.json": relations,
    }
    manifest = json.loads(files["manifest.json"])
    for relative, items in kept.items():
        envelope = json.loads(files[relative])
        envelope["items"] = items
        files[relative] = json.dumps(envelope, sort_keys=True).encode()
    manifest["item_files"] = [
        {**ref, "sha256": sha256_hex(files[ref["path"]])}
        for ref in manifest["item_files"]
        if kept.get(ref["path"])
    ]
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


async def apply_catalog_min(db, root: Path) -> FixtureCatalog:
    """Apply the narrowed job-catalog pack (a handful of jobs)."""
    return await _apply_pack(db, root, catalog_min_files(), name="Fixture job catalog")


async def apply_taxonomy_pack(db, root: Path) -> FixtureCatalog:
    """Apply only the pack's skills and interest tags (profile fixtures)."""
    return await _apply_pack(db, root, taxonomy_pack_files(), name="Fixture job taxonomy")
