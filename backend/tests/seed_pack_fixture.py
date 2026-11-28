"""Plan 224 S4 / plan 225 S5: the published packs as shared test fixtures.

The app bundles no catalog and no reference bank, so tests that need jobs,
taxonomy, starter paths or the reference banks apply the released packs
instead. The pack bytes are read once per worker process; rows are written
inside each test's own transaction.
"""

from __future__ import annotations

import json
import tempfile
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
BANK_PACK_DIR = (
    Path(__file__).parent / "fixtures" / "seed_packs" / "packs" / "neuronection" / "reference-banks"
)

BANK_ITEM_FILES = {
    "assessment_questions": "items/assessment_questions/questions.json",
    "assessment_templates": "items/assessment_templates/batteries.json",
    "cv_templates": "items/cv_templates/templates.json",
    "metric_dimensions": "items/metric_dimensions/dimensions.json",
    "metric_category_anchors": "items/metric_category_anchors/anchors.json",
    "skill_packs": "items/skill_packs/packs.json",
}


@cache
def pack_items(relative: str) -> tuple[dict, ...]:
    """One item envelope of the fixture pack (e.g. ``job_relations/relations.json``)."""
    envelope = json.loads((PACK_DIR / "items" / relative).read_text(encoding="utf-8"))
    return tuple(envelope["items"])


@cache
def bank_items(item_type: str) -> tuple[dict, ...]:
    """One item type of the reference-banks fixture pack, by item type."""
    return _envelope_items(BANK_PACK_DIR, BANK_ITEM_FILES[item_type])


def _envelope_items(root: Path, relative: str) -> tuple[dict, ...]:
    envelope = json.loads((root / relative).read_text(encoding="utf-8"))
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


def _scratch_root(root: Path | None) -> Path:
    """One process-wide store root so every fixture apply sees earlier archives.

    The provider lane resolves other approved sources' current versions while
    planning claims; a per-call temporary store made those archives invisible
    once a second fixture pack was applied.
    """
    if root is not None:
        return root
    return _SHARED_ROOT


_SHARED_ROOT = Path(tempfile.mkdtemp(prefix="career-pack-fixtures-"))


async def _apply_pack(
    db, root: Path | None, files: dict[str, bytes], *, name: str
) -> FixtureCatalog:
    store = fixture_store(_scratch_root(root))
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
        raise AssertionError(f"fixture pack failed to apply: {result.as_dict()}")
    return FixtureCatalog(source=source, version=version, store=store)


async def seed_category_anchors(db) -> None:
    """The catalog pack carries interest tags, so the planner needs anchors.

    On a real install the reference-banks pack publishes them; the fixture
    seeds the same anchor rows directly so a catalog-first test fixture is not
    a manual-out-of-order install.
    """
    from sqlalchemy import select

    from app.models.metric_model import MetricCategoryAnchor

    existing = {
        category for (category,) in (await db.execute(select(MetricCategoryAnchor.category))).all()
    }
    for item in bank_items("metric_category_anchors"):
        if item["category"] in existing:
            continue
        db.add(
            MetricCategoryAnchor(
                category=item["category"],
                letter=item["letter"],
                status="published",
                seed_key=item["seed_key"],
            )
        )
    await db.commit()


async def apply_catalog_pack(db, root: Path | None = None) -> FixtureCatalog:
    """Apply the whole job-catalog fixture pack as an operator file provider."""
    await seed_category_anchors(db)
    return await _apply_pack(db, root, catalog_pack_files(), name="Fixture job catalog")


async def apply_taxonomy_pack(db, root: Path | None = None) -> FixtureCatalog:
    """Apply only the pack's skills and interest tags (profile fixtures)."""
    await seed_category_anchors(db)
    return await _apply_pack(db, root, taxonomy_pack_files(), name="Fixture job taxonomy")


@lru_cache(maxsize=1)
def bank_pack_files() -> dict[str, bytes]:
    """The reference-banks fixture pack's files, parsed once per worker process."""
    return {
        path.relative_to(BANK_PACK_DIR).as_posix(): path.read_bytes()
        for path in sorted(BANK_PACK_DIR.rglob("*.json"))
    }


@lru_cache(maxsize=1)
def assessment_questions_pack_files() -> dict[str, bytes]:
    """The bank pack restricted to the assessment questions.

    A test that needs questions but not a metric bank (the no-pack contract)
    applies this subset instead of the whole reference banks.
    """
    files = dict(bank_pack_files())
    keep = {BANK_ITEM_FILES["assessment_questions"]}
    manifest = json.loads(files["manifest.json"])
    manifest["item_files"] = [ref for ref in manifest["item_files"] if ref["path"] in keep]
    files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    return files


async def apply_bank_pack(db, root: Path | None = None) -> FixtureCatalog:
    """Apply the reference-banks fixture pack as an operator file provider.

    Carries the assessment questions and batteries, the CV layouts, the metric
    dimensions and category anchors, and the skill packs (installed as drafts).
    """
    return await _apply_pack(db, root, bank_pack_files(), name="Fixture reference banks")


async def apply_assessment_questions_pack(db, root: Path | None = None) -> FixtureCatalog:
    """Apply only the reference-banks questions (no metric bank)."""
    return await _apply_pack(
        db, root, assessment_questions_pack_files(), name="Fixture assessment questions"
    )
