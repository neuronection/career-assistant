"""Plan 224 S1: the planner refuses catalog packs until their adapters land."""

from __future__ import annotations

import pytest

from app.core.seed_pack.errors import SeedPackError
from tests.test_seed_apply import (
    _assemble,
    _preset_pack,
    _service,
    _source,
    _store,
    _version,
)

FAMILY = {
    "seed_key": "job-family:data",
    "key": "data",
    "label": "Data",
    "parent_key": None,
    "description": "Data roles.",
}
JOB_TYPE = {
    "seed_key": "job-type:data-analyst",
    "code": "data-analyst",
    "title": "Data Analyst",
    "family_key": "data",
    "summary": "Turns data into decisions.",
    "attributes": {"experience_typical_years": [0, 3]},
    "skills": [{"skill_key": "sql", "required_level": 5, "importance": "important"}],
    "interests": ["science-physics"],
}


def _catalog_pack() -> dict[str, bytes]:
    envelope = {
        "metadata": {
            "item_type": "job_families",
            "format": "job_families",
            "format_version": 1,
            "dataset_vintage": "2026-11-25",
            "license": "CC-BY-4.0",
        },
        "items": [FAMILY],
    }
    return _assemble("job_families", envelope, "1.0.0")


def _old_job_types_pack() -> dict[str, bytes]:
    envelope = {
        "metadata": {
            "item_type": "job_types",
            "format": "job_types",
            "format_version": 1,
            "dataset_vintage": "2026-11-25",
            "license": "CC-BY-4.0",
        },
        "items": [JOB_TYPE],
    }
    return _assemble("job_types", envelope, "1.0.0")


async def test_a_catalog_candidate_requires_a_trusted_source(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _catalog_pack())
    with pytest.raises(SeedPackError) as exc:
        await _service(db, store).build_plan(source, version)
    assert exc.value.code == "CATALOG_TRUST_DENIED"


async def test_a_catalog_pack_with_no_readable_item_is_plan_empty(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _old_job_types_pack())
    with pytest.raises(SeedPackError) as exc:
        await _service(db, store).build_plan(source, version)
    assert exc.value.code == "PLAN_EMPTY"


async def test_preset_packs_still_plan(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _preset_pack())
    plan = await _service(db, store).build_plan(source, version)
    assert plan.status == "ok"
    assert plan.counts["create"] == 1
