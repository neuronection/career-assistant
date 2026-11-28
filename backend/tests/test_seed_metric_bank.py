"""Plan 225 S3: the metric bank — adapters, anchor law and install order."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.errors import (
    CATALOG_REF_UNRESOLVED,
    SeedPackError,
)
from app.core.seed_pack.manifest import compute_files_digest
from app.models.metric_model import MetricCategoryAnchor, MetricDimension
from app.models.seed_model import SeedItemProvenance, SeedSource, SeedSourceVersion
from app.models.taxonomy_model import InterestTag
from app.services.seeds.applier import SeedApplyService
from app.services.seeds.banks import REFERENCE_BANK_SUBPATH
from app.services.seeds.provider_service import ProviderService
from app.services.seeds.service import ProviderSyncService
from tests.test_seed_apply import _service, _source, _store, _version
from tests.test_seed_pack import _envelope, _pack

DIMENSION = {
    "seed_key": "metric-dimension:interest.investigative",
    "key": "interest.investigative",
    "label": "Investigative",
    "group": "interest",
    "description": "Synthetic investigative affinity.",
    "scale": "scalar",
    "reverse_score": False,
    "sources": ["profile.interests"],
    "consumers": ["fit.interests"],
}
SECOND_DIMENSION = {
    "seed_key": "metric-dimension:values.autonomy",
    "key": "values.autonomy",
    "label": "Autonomy",
    "group": "value",
    "description": "Synthetic autonomy value.",
    "sources": ["assessment.tradeoff"],
    "consumers": ["fit.values"],
}
ANCHOR = {
    "seed_key": "interest-category:synthetic-science",
    "category": "synthetic-science",
    "letter": "investigative",
}
SECOND_ANCHOR = {
    "seed_key": "interest-category:synthetic-arts",
    "category": "synthetic-arts",
    "letter": "artistic",
}
ANCHOR_LETTERS = {
    "science": "investigative",
    "arts": "artistic",
    "technology": "investigative",
    "cognitive": "investigative",
    "technical": "investigative",
    "creative": "artistic",
    "people": "social",
    "interpersonal": "social",
    "business": "enterprising",
    "communication": "enterprising",
    "society": "enterprising",
    "sports": "realistic",
    "physical": "realistic",
    "hands-on": "realistic",
}


def _metric_pack(
    dimensions: list | None,
    anchors: list | None,
    *,
    version: str = "1.0.0",
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if dimensions is not None:
        files["items/metric_dimensions/dimensions.json"] = _envelope(
            "metric_dimensions", dimensions
        )
    if anchors is not None:
        files["items/metric_category_anchors/anchors.json"] = _envelope(
            "metric_category_anchors", anchors
        )
    return _pack(files, manifest={"version": version, "replaces": []})


def _interest_pack(categories: list[str]) -> dict[str, bytes]:
    items = [
        {
            "seed_key": f"interest:{category}-probe",
            "key": f"{category}-probe",
            "label": f"{category.title()} probe",
            "category": category,
        }
        for category in categories
    ]
    return _pack(
        {"items/interest_tags/interests.json": _envelope("interest_tags", items)},
        manifest={"version": "1.0.0", "replaces": []},
    )


async def _operator_source(db):
    source = await _source(db)
    source.trust_tier = "operator"
    await db.commit()
    await db.refresh(source)
    return source


async def _clear_anchors(db) -> None:
    """Drop the migration-seeded anchors so the pack under test owns the bank.

    Postgres keeps the rows the migration inserted (Alembic is outside the
    per-test transaction); SQLite truncates them. Clearing up front makes
    both lanes assert the same plan.
    """
    from sqlalchemy import delete

    await db.execute(delete(MetricCategoryAnchor))
    await db.commit()


async def _retire_all_anchors(db) -> None:
    """The no-anchor state: every anchor is retired, none is published."""
    from sqlalchemy import update

    await db.execute(update(MetricCategoryAnchor).values(status="retired"))
    await db.commit()


async def test_metric_pack_parses_plans_applies_noops_updates_and_retires(db, tmp_path):
    await _clear_anchors(db)
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(
        db, store, source, _metric_pack([DIMENSION, SECOND_DIMENSION], [ANCHOR, SECOND_ANCHOR])
    )

    plan = await _service(db, store).build_plan(source, version)
    assert plan.status == "ok"
    actions = {
        item.entity_type: item.action
        for item in plan.items
        if item.entity_type.startswith("metric_")
    }
    assert actions == {"metric_dimension": "create", "metric_category_anchor": "create"}
    preview = next(item.preview for item in plan.items if item.seed_key == ANCHOR["seed_key"])
    assert preview == {"category": "synthetic-science", "letter": "investigative"}

    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error

    dimension = await db.scalar(
        select(MetricDimension).where(MetricDimension.key == "interest.investigative")
    )
    assert dimension is not None
    assert dimension.seed_key == DIMENSION["seed_key"]
    assert dimension.group == "interest"
    assert dimension.status == "published"
    assert dimension.sources == ["profile.interests"]
    anchor = await db.scalar(
        select(MetricCategoryAnchor).where(MetricCategoryAnchor.category == "synthetic-science")
    )
    assert anchor is not None
    assert anchor.letter == "investigative"
    assert anchor.status == "published"
    assert anchor.seed_key == ANCHOR["seed_key"]
    provenance = await db.scalar(
        select(SeedItemProvenance).where(
            SeedItemProvenance.entity_type == "metric_category_anchor",
            SeedItemProvenance.entity_id == anchor.id,
        )
    )
    assert provenance is not None

    again = await _service(db, store).apply(source, version)
    assert again.status == "noop"

    changed = await _version(
        db,
        store,
        source,
        _metric_pack([{**DIMENSION, "label": "Investigative updated"}], [], version="2.0.0"),
    )
    changed_plan = await _service(db, store).build_plan(source, changed)
    changed_actions = {
        (item.entity_type, item.seed_key): item.action for item in changed_plan.items
    }
    assert changed_actions[("metric_dimension", DIMENSION["seed_key"])] == "update"
    assert changed_actions[("metric_category_anchor", ANCHOR["seed_key"])] == "retire"
    assert changed_actions[("metric_category_anchor", SECOND_ANCHOR["seed_key"])] == "retire"

    applied = await _service(db, store).apply(source, changed)
    assert applied.status == "applied", applied.error
    dimension = await db.scalar(
        select(MetricDimension).where(MetricDimension.key == "interest.investigative")
    )
    assert dimension is not None and dimension.label == "Investigative updated"
    anchors = (await db.execute(select(MetricCategoryAnchor))).scalars().all()
    assert {row.status for row in anchors} == {"retired"}

    removed = await _version(db, store, source, _metric_pack([], [], version="3.0.0"))
    applied = await _service(db, store).apply(source, removed)
    assert applied.status == "applied", applied.error
    dimension = await db.scalar(
        select(MetricDimension).where(MetricDimension.key == "interest.investigative")
    )
    assert dimension is not None and dimension.status == "retired"


async def test_a_pack_apply_invalidates_the_metric_registry(db, tmp_path):
    from app.services.catalog.metric_registry import metric_registry

    empty = await metric_registry.snapshot(db)
    assert empty.available is False

    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _metric_pack([DIMENSION], []))
    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error

    fresh = await metric_registry.snapshot(db)
    assert fresh.available is True
    assert "interest.investigative" in fresh.dimension_keys


async def test_a_pack_adopts_the_stamped_metric_bank_without_duplicates(db, tmp_path):
    from app.seeds.bank_stamp import stamp_bank_identities
    from app.seeds.metrics import CATEGORY_RIASEC, DIMENSIONS, seed_metric_dimensions

    await seed_metric_dimensions(db)
    await stamp_bank_identities(db)
    await db.commit()
    before_dimensions = {
        row.seed_key: row.id for row in (await db.execute(select(MetricDimension))).scalars().all()
    }
    before_anchors = {
        row.seed_key: row.id
        for row in (await db.execute(select(MetricCategoryAnchor))).scalars().all()
    }
    assert len(before_dimensions) == len(DIMENSIONS)
    assert len(before_anchors) == len(CATEGORY_RIASEC)
    assert None not in before_dimensions and None not in before_anchors

    dimension_items = [
        {"seed_key": f"metric-dimension:{spec['key']}", **spec} for spec in DIMENSIONS
    ]
    anchor_items = [
        {"seed_key": f"interest-category:{category}", "category": category, "letter": letter}
        for category, letter in CATEGORY_RIASEC.items()
    ]
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _metric_pack(dimension_items, anchor_items))

    plan = await _service(db, store).build_plan(source, version)
    assert not [item for item in plan.items if item.action in ("create", "retire", "delete")]
    assert {item.action for item in plan.items if item.entity_type.startswith("metric_")} == {
        "update"
    }

    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error
    again = await _service(db, store).apply(source, version)
    assert again.status == "noop"

    dimensions = (await db.execute(select(MetricDimension))).scalars().all()
    anchors = (await db.execute(select(MetricCategoryAnchor))).scalars().all()
    assert len(dimensions) == len(DIMENSIONS)
    assert len(anchors) == len(CATEGORY_RIASEC)
    assert {row.id for row in dimensions} == set(before_dimensions.values())
    assert {row.id for row in anchors} == set(before_anchors.values())
    assert {row.status for row in dimensions} == {"published"}
    assert {row.status for row in anchors} == {"published"}


async def test_retiring_an_anchor_used_by_an_active_tag_is_conflicted(db, tmp_path):
    await _clear_anchors(db)
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _metric_pack([DIMENSION], [ANCHOR]))
    applied = await _service(db, store).apply(source, first)
    assert applied.status == "applied", applied.error

    db.add(InterestTag(key="science-probe", label="Science probe", category="synthetic-science"))
    await db.commit()

    removed = await _version(db, store, source, _metric_pack([DIMENSION], [], version="2.0.0"))
    plan = await _service(db, store).build_plan(source, removed)
    assert plan.status == "conflicted"
    assert any("synthetic-science" in conflict["reason"] for conflict in plan.conflicts)
    assert not [
        item
        for item in plan.items
        if item.entity_type == "metric_category_anchor" and item.action == "retire"
    ]

    result = await _service(db, store).apply(source, removed)
    assert result.status == "conflicted"
    anchor = await db.scalar(
        select(MetricCategoryAnchor).where(MetricCategoryAnchor.category == "synthetic-science")
    )
    assert anchor is not None and anchor.status == "published"


async def test_a_pack_retiring_an_anchor_and_its_tag_together_is_allowed(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(
        db,
        store,
        source,
        _pack(
            {
                "items/metric_dimensions/dimensions.json": _envelope(
                    "metric_dimensions", [DIMENSION]
                ),
                "items/metric_category_anchors/anchors.json": _envelope(
                    "metric_category_anchors", [ANCHOR]
                ),
                "items/interest_tags/interests.json": _envelope(
                    "interest_tags",
                    [
                        {
                            "seed_key": "interest:science-probe",
                            "key": "science-probe",
                            "label": "Science probe",
                            "category": "synthetic-science",
                        }
                    ],
                ),
            },
            manifest={"version": "1.0.0", "replaces": []},
        ),
    )
    applied = await _service(db, store).apply(source, first)
    assert applied.status == "applied", applied.error
    tag = await db.scalar(select(InterestTag).where(InterestTag.key == "science-probe"))
    assert tag is not None and tag.deprecated is False

    removed = await _version(db, store, source, _metric_pack([DIMENSION], [], version="2.0.0"))
    plan = await _service(db, store).build_plan(source, removed)
    assert plan.status == "ok"
    actions = {(item.entity_type, item.seed_key): item.action for item in plan.items}
    assert actions[("interest_tag", "interest:science-probe")] == "retire"
    assert actions[("metric_category_anchor", ANCHOR["seed_key"])] == "retire"
    applied = await _service(db, store).apply(source, removed)
    assert applied.status == "applied", applied.error


async def test_a_catalog_pack_with_interest_tags_needs_anchors(db, tmp_path):
    await _retire_all_anchors(db)
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _interest_pack(["synthetic-science"]))

    with pytest.raises(SeedPackError) as refused:
        await _service(db, store).build_plan(source, version)
    assert refused.value.code == CATALOG_REF_UNRESOLVED
    assert "neuronection-reference-banks" in refused.value.detail

    with_anchors = _pack(
        {
            "items/interest_tags/interests.json": _envelope(
                "interest_tags",
                [
                    {
                        "seed_key": "interest:science-probe",
                        "key": "science-probe",
                        "label": "Science probe",
                        "category": "synthetic-science",
                    }
                ],
            ),
            "items/metric_category_anchors/anchors.json": _envelope(
                "metric_category_anchors", [ANCHOR]
            ),
        },
        manifest={"version": "2.0.0", "replaces": []},
    )
    candidate = await _version(db, store, source, with_anchors)
    plan = await _service(db, store).build_plan(source, candidate)
    assert plan.status == "ok"
    assert not plan.conflicts
    applied = await _service(db, store).apply(source, candidate)
    assert applied.status == "applied", applied.error
    assert await db.scalar(
        select(MetricCategoryAnchor).where(MetricCategoryAnchor.category == "synthetic-science")
    )
    assert await db.scalar(select(InterestTag).where(InterestTag.key == "science-probe"))


async def test_install_official_installs_reference_banks_before_the_catalog(
    db, tmp_path, monkeypatch
):
    await _retire_all_anchors(db)
    store = _store(tmp_path)
    catalog_files = _interest_pack(["science"])
    reference_items = [
        {
            "seed_key": f"interest-category:{category}",
            "category": category,
            "letter": letter,
        }
        for category, letter in ANCHOR_LETTERS.items()
    ]
    reference_files = _pack(
        {
            "items/metric_category_anchors/anchors.json": _envelope(
                "metric_category_anchors", reference_items
            )
        },
        manifest={"version": "1.0.0", "replaces": []},
    )
    packs_by_source: dict[object, dict[str, bytes]] = {}

    async def fake_sync(self, source, *, trigger="manual", actor=None):
        files = packs_by_source[source.id]
        digest = compute_files_digest(files)
        store.put(source.id, digest, build_pack_archive(files))
        version = SeedSourceVersion(
            source_id=source.id,
            digest=digest,
            manifest=json.loads(files["manifest.json"]),
            pack_version="1.0.0",
            schema_version="1.0",
            status="pending",
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(version)
        return {"status": "ok", "version_id": str(version.id)}

    monkeypatch.setattr(ProviderSyncService, "sync", fake_sync)

    order: list[str] = []
    original_apply = SeedApplyService.apply

    async def recording_apply(self, source, version, **kwargs):
        order.append(source.subpath)
        return await original_apply(self, source, version, **kwargs)

    monkeypatch.setattr(SeedApplyService, "apply", recording_apply)

    reference = SeedSource(
        name="Reference banks",
        kind="git",
        uri="https://example.test/seeds.git",
        subpath=REFERENCE_BANK_SUBPATH,
        trust_tier="official",
        priority=100,
        enabled=False,
    )
    catalog = SeedSource(
        name="Job catalog",
        kind="git",
        uri="https://example.test/seeds.git",
        subpath="packs/neuronection/job-catalog",
        trust_tier="official",
        priority=100,
        enabled=False,
    )
    db.add_all([reference, catalog])
    await db.commit()
    await db.refresh(reference)
    await db.refresh(catalog)
    packs_by_source[reference.id] = reference_files
    packs_by_source[catalog.id] = catalog_files

    result = await ProviderService(db, packs=store).install_official(catalog.id)
    assert result["status"] == "applied", result
    await db.refresh(reference)
    await db.refresh(catalog)
    assert reference.current_version_id is not None
    assert catalog.current_version_id is not None
    assert order == [REFERENCE_BANK_SUBPATH, catalog.subpath]
    anchor = await db.scalar(
        select(MetricCategoryAnchor).where(MetricCategoryAnchor.category == "science")
    )
    assert anchor is not None
    tag = await db.scalar(select(InterestTag).where(InterestTag.key == "science-probe"))
    assert tag is not None


async def test_install_official_refuses_a_catalog_without_the_reference_tile(db, tmp_path):
    await _retire_all_anchors(db)
    store = _store(tmp_path)
    source = SeedSource(
        name="Job catalog",
        kind="git",
        uri="https://example.test/seeds.git",
        subpath="packs/neuronection/job-catalog",
        trust_tier="official",
        priority=100,
        enabled=False,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    version = await _version(db, store, source, _interest_pack(["science"]))

    with pytest.raises(SeedPackError) as refused:
        await SeedApplyService(db, packs=store).apply(source, version)
    assert refused.value.code == CATALOG_REF_UNRESOLVED
    assert "neuronection-reference-banks" in refused.value.detail
