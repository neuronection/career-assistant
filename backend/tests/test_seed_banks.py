"""Plan 225 S0: the bank lane — parse, plan, apply, no-op, retire, parity."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.seed_pack.errors import SeedPackError
from app.models.assessment_template_model import AssessmentTemplate
from app.models.metric_model import MetricCategoryAnchor
from app.seeds.bank_keys import QUESTION_KEYS
from app.services.seeds.banks import (
    APPLY_ORDER,
    BANK_ENTITY_MODELS,
    BANK_FORMATS,
    COUNT_KEYS,
    ITEM_ENTITY,
    RETIRE,
)
from tests.test_seed_apply import _service, _source, _store, _version
from tests.test_seed_pack import _envelope, _pack

TEMPLATE = {
    "seed_key": "assessment-template:synthetic-battery/v1",
    "key": "synthetic-battery",
    "version": 1,
    "title": "Synthetic battery",
    "description": "One slider.",
    "audience_stages": ["student"],
    "language": "en",
    "schema_version": 1,
    "content": {
        "phases": [
            {
                "title": "Interests",
                "questions": [
                    {
                        "kind": "slider",
                        "prompt": "Rate this interest.",
                        "dimension_key": "interest.social",
                        "numeric_min": 1,
                        "numeric_max": 10,
                        "cap": 10,
                    }
                ],
            }
        ],
        "normalization": {},
    },
}
DIMENSION = {
    "seed_key": "metric-dimension:interest.social",
    "key": "interest.social",
    "label": "Social",
    "group": "interest",
    "description": "Helping people.",
    "sources": ["profile.interests"],
    "consumers": ["fit.interests"],
}


def _bank_pack(items: list | None, *, version: str = "1.0.0", replaces=None) -> dict[str, bytes]:
    return _pack(
        {
            "items/assessment_templates/templates.json": _envelope(
                "assessment_templates", items or []
            )
        },
        manifest={"version": version, "replaces": replaces or []},
    )


def _template_pack(
    *,
    key: str = "synthetic-battery",
    version: str = "1.0.0",
    replaces=None,
) -> dict[str, bytes]:
    item = dict(TEMPLATE, key=key, seed_key=f"assessment-template:{key}/v1")
    return _bank_pack([item], version=version, replaces=replaces)


async def _operator_source(db):
    source = await _source(db)
    source.trust_tier = "operator"
    await db.commit()
    await db.refresh(source)
    return source


async def test_assessment_template_pack_parses_plans_applies_noops_and_retires(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    anchor = await db.scalar(
        select(MetricCategoryAnchor).where(MetricCategoryAnchor.category == "science")
    )
    if anchor is None:
        anchor = MetricCategoryAnchor(
            category="science",
            letter="investigative",
            status="published",
            seed_key="interest-category:science",
        )
        db.add(anchor)
        await db.commit()
    version = await _version(db, store, source, _template_pack())

    plan = await _service(db, store).build_plan(source, version)
    assert plan.status == "ok"
    [item] = [row for row in plan.items if row.entity_type == "assessment_template"]
    assert item.action == "create"
    assert item.preview == {
        "title": "Synthetic battery",
        "version": 1,
        "phases": 1,
        "questions": 1,
    }

    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error
    row = await db.scalar(select(AssessmentTemplate))
    assert row is not None
    assert row.seed_key == "assessment-template:synthetic-battery/v1"
    assert row.author_key == "bank" and row.source == "bank"
    assert row.status == "published" and row.visibility == "private"
    assert row.content_hash and row.ref

    again = await _service(db, store).apply(source, version)
    assert again.status == "noop"
    await db.refresh(anchor)
    assert anchor.status == "published"

    removed = await _version(db, store, source, _bank_pack([], version="2.0.0"))
    retired = await _service(db, store).apply(source, removed)
    assert retired.status == "applied", retired.error
    await db.refresh(row)
    assert row.status == "retired"

    restored = await _version(db, store, source, _template_pack(version="3.0.0"))
    back = await _service(db, store).apply(source, restored)
    assert back.status == "applied", back.error
    await db.refresh(row)
    assert row.status == "published"


async def test_a_bank_pack_requires_operator_or_official_trust(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _template_pack())

    with pytest.raises(SeedPackError) as exc:
        await _service(db, store).build_plan(source, version)
    assert exc.value.code == "BANK_TRUST_DENIED"


async def test_a_registered_bank_format_without_an_adapter_is_refused(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    files = _pack(
        {"items/metric_dimensions/dimensions.json": _envelope("metric_dimensions", [DIMENSION])}
    )
    version = await _version(db, store, source, files)

    with pytest.raises(SeedPackError) as exc:
        await _service(db, store).build_plan(source, version)
    assert exc.value.code == "BANK_UNSUPPORTED"


async def test_replaces_renames_a_bank_row_and_keeps_its_uuid(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _template_pack(key="old-battery"))
    await _service(db, store).apply(source, first)
    old = await db.scalar(select(AssessmentTemplate))
    assert old is not None
    old_id = old.id

    second = await _version(
        db,
        store,
        source,
        _template_pack(key="new-battery", version="2.0.0", replaces=["old-battery/v1"]),
    )
    plan = await _service(db, store).build_plan(source, second)
    assert plan.warnings == []
    assert not [
        item
        for item in plan.items
        if item.action == "retire" and item.seed_key.endswith("old-battery/v1")
    ]
    applied = await _service(db, store).apply(source, second)
    assert applied.status == "applied", applied.error
    db.expire_all()
    rows = (await db.execute(select(AssessmentTemplate))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == old_id
    assert rows[0].key == "new-battery"
    assert rows[0].seed_key == "assessment-template:new-battery/v1"


async def test_a_bank_key_claimed_by_another_approved_source_is_not_retired(db, tmp_path):
    store = _store(tmp_path)
    keeper = await _operator_source(db)
    first = await _version(db, store, keeper, _template_pack())
    await _service(db, store).apply(source=keeper, version=first)

    other = await _operator_source(db)
    second = await _version(db, store, other, _bank_pack([], version="2.0.0"))
    plan = await _service(db, store).build_plan(other, second)
    assert not [
        item
        for item in plan.items
        if item.entity_type == "assessment_template" and item.action == "retire"
    ]


def _migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0022_bank_pack_identity.py"
    spec = importlib.util.spec_from_file_location("migration_0022", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_question_keys_match_the_bank_and_the_migration():
    from app.seeds.assessment import BANK_QUESTIONS

    prompts = [question["prompt"] for question in BANK_QUESTIONS]
    assert len(prompts) == len(set(prompts)) == 8
    assert set(prompts) == set(QUESTION_KEYS)
    assert len(set(QUESTION_KEYS.values())) == len(QUESTION_KEYS)

    migration = _migration_module()
    assert dict(migration.QUESTION_KEYS) == QUESTION_KEYS


def test_dimension_anchor_and_version_keys_match_the_migration():
    from app.seeds.cv_templates import BANK_TEMPLATES
    from app.seeds.metrics import CATEGORY_RIASEC, DIMENSIONS
    from app.seeds.skill_packs import BANK_PACKS

    migration = _migration_module()
    assert tuple(spec["key"] for spec in DIMENSIONS) == migration.DIMENSION_KEYS
    assert dict(migration.CATEGORY_ANCHORS) == CATEGORY_RIASEC
    assert (
        tuple((spec["key"], spec.get("version", 1)) for spec in BANK_TEMPLATES)
        == migration.CV_TEMPLATE_KEYS
    )
    assert tuple((spec["key"], 1) for spec in BANK_PACKS) == migration.SKILL_PACK_KEYS


async def test_assessment_template_keys_match_the_migration(db):
    from app.seeds.metrics import seed_metric_templates

    await seed_metric_templates(db)
    rows = (
        await db.execute(
            select(AssessmentTemplate.key, AssessmentTemplate.version).where(
                AssessmentTemplate.author_key == "bank"
            )
        )
    ).all()
    assert sorted(rows) == sorted(_migration_module().ASSESSMENT_TEMPLATE_KEYS)


def test_bank_registries_are_total():
    from app.core.seed_pack.manifest import BANK_FORMAT_NAMES

    assert set(BANK_FORMATS) == set(ITEM_ENTITY) == set(BANK_FORMAT_NAMES)
    assert set(BANK_ENTITY_MODELS) == set(ITEM_ENTITY.values())
    assert set(APPLY_ORDER) == set(BANK_ENTITY_MODELS)
    assert set(RETIRE) == set(BANK_ENTITY_MODELS)
    assert set(COUNT_KEYS) == set(BANK_ENTITY_MODELS)
    assert BANK_FORMATS["assessment_templates"] is not None
    assert all(
        adapter is None for name, adapter in BANK_FORMATS.items() if name != "assessment_templates"
    )
