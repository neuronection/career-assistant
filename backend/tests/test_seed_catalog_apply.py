"""Plan 224 S2: catalog adapters — apply, adopt, retire, delete, trust."""

from __future__ import annotations

from sqlalchemy import select, update

from app.models.career_path_model import CareerPath
from app.models.job_model import Job, JobFamily, JobRelation, JobSkill, JobTag
from app.models.taxonomy_model import InterestTag, Skill
from app.services.seeds.catalog import mark_user_modified
from tests.test_seed_apply import _service, _source, _store, _version
from tests.test_seed_pack import _pack

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
RELATION = {
    "seed_key": "job-relation:data-analyst/data-analyst/similar-to",
    "from": "data-analyst",
    "to": "data-analyst",
    "type": "similar_to",
    "weight": 0.5,
    "rationale": "self",
}
PATH = {
    "seed_key": "career-path:data-analyst/the-quantitative-route",
    "job": "data-analyst",
    "title": "The quantitative route",
    "description": "Study route.",
    "steps": [{"kind": "education", "label": "Degree"}],
}
SKILL = {"seed_key": "skill:sql", "key": "sql", "label": "SQL", "category": "technical"}
INTEREST = {
    "seed_key": "interest:science-physics",
    "key": "science-physics",
    "label": "Physics",
    "category": "science",
}


def _envelope(format: str, items: list, version: int = 1) -> dict:
    return {
        "metadata": {
            "item_type": format,
            "format": format,
            "format_version": version,
            "dataset_vintage": "2026-11-26",
            "license": "CC-BY-4.0",
        },
        "items": items,
    }


def _catalog_pack(
    *,
    version: str = "1.0.0",
    include_job: bool = True,
    include_relation: bool = True,
    include_path: bool = True,
) -> dict[str, bytes]:
    files: dict[str, dict] = {
        "items/job_families/families.json": _envelope("job_families", [FAMILY]),
        "items/skills/skills.json": _envelope("skills", [SKILL]),
        "items/interest_tags/interests.json": _envelope("interest_tags", [INTEREST]),
    }
    if include_job:
        files["items/job_types/jobs.json"] = _envelope("job_types", [JOB_TYPE], version=2)
    if include_relation:
        files["items/job_relations/relations.json"] = _envelope("job_relations", [RELATION])
    if include_path:
        files["items/career_paths/paths.json"] = _envelope("career_paths", [PATH])
    return _pack(files, manifest={"version": version})


async def _operator_source(db):
    source = await _source(db)
    source.trust_tier = "operator"
    await db.commit()
    await db.refresh(source)
    return source


async def test_a_catalog_pack_requires_operator_or_official_trust(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)  # community
    version = await _version(db, store, source, _catalog_pack())
    import pytest

    from app.core.seed_pack.errors import SeedPackError

    with pytest.raises(SeedPackError) as exc:
        await _service(db, store).build_plan(source, version)
    assert exc.value.code == "CATALOG_TRUST_DENIED"


async def test_catalog_apply_creates_rows_links_and_path_steps(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _catalog_pack())

    plan = await _service(db, store).build_plan(source, version)
    assert plan.status == "ok"
    result = await _service(db, store).apply(source, version)
    assert result.status == "applied", result.error

    family = await db.scalar(select(JobFamily))
    job = await db.scalar(select(Job))
    assert family is not None and family.seed_key == "job-family:data"
    assert job is not None and job.seed_key == "job-type:data-analyst"
    assert job.family_id == family.id
    assert job.status == "published" and job.source == "seed"
    assert await db.scalar(select(Skill)) is not None
    assert await db.scalar(select(InterestTag)) is not None
    assert await db.scalar(select(JobSkill)) is not None
    assert await db.scalar(select(JobTag)) is not None
    assert await db.scalar(select(JobRelation)) is not None
    path = await db.scalar(select(CareerPath))
    assert path is not None and path.seed_key == "career-path:data-analyst/the-quantitative-route"
    await db.refresh(path, ["steps"])
    assert len(path.steps) == 1

    # Idempotent re-apply: no new rows and no mutations.
    debug = await _service(db, store).build_plan(source, version)
    print("SECOND PLAN", debug.status, debug.conflicts)
    second = await _service(db, store).apply(source, version)
    assert second.status == "noop"
    assert await db.scalar(select(JobFamily)) is not None


async def test_removing_a_job_retires_and_readding_restores(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _catalog_pack(version="1.0.0"))
    await _service(db, store).apply(source, first)

    second = await _version(
        db,
        store,
        source,
        _catalog_pack(
            version="2.0.0", include_job=False, include_relation=False, include_path=False
        ),
    )
    applied = await _service(db, store).apply(source, second)
    assert applied.status == "applied", applied.error
    job = await db.scalar(select(Job))
    assert job is not None and job.status == "retired"

    third = await _version(db, store, source, _catalog_pack(version="3.0.0"))
    restored = await _service(db, store).apply(source, third)
    assert restored.status == "applied", restored.error
    db.expire_all()
    job = await db.scalar(select(Job))
    assert job is not None and job.status == "published"


async def test_removing_a_relation_deletes_only_seed_edges(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _catalog_pack(version="1.0.0"))
    await _service(db, store).apply(source, first)
    assert await db.scalar(select(JobRelation)) is not None

    second = await _version(
        db,
        store,
        source,
        _catalog_pack(version="2.0.0", include_relation=False),
    )
    applied = await _service(db, store).apply(source, second)
    assert applied.status == "applied", applied.error
    assert await db.scalar(select(JobRelation)) is None


async def test_first_apply_adopts_an_existing_seeded_job(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    family = JobFamily(key="data", label="Data", path="data", level=0, description="")
    db.add(family)
    await db.flush()
    existing = Job(
        code="data-analyst",
        title="Data Analyst",
        family_id=family.id,
        short_description="",
        status="published",
        source="seed",
        attributes={},
        links=[],
    )
    db.add(existing)
    await db.commit()
    existing_id = existing.id

    version = await _version(db, store, source, _catalog_pack())
    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error
    job = await db.scalar(select(Job).where(Job.code == "data-analyst"))
    assert job is not None and job.id == existing_id
    assert job.seed_key == "job-type:data-analyst"
    assert await db.scalar(select(JobFamily).where(JobFamily.key == "data")) is not None


def _job_only_pack(
    code: str,
    seed_key: str,
    version: str,
    *,
    replaces: list[str] | None = None,
    title: str | None = None,
) -> dict[str, bytes]:
    job = dict(
        JOB_TYPE, code=code, seed_key=seed_key, title=title or code.replace("-", " ").title()
    )
    files = {
        "items/job_families/families.json": _envelope("job_families", [FAMILY]),
        "items/skills/skills.json": _envelope("skills", [SKILL]),
        "items/interest_tags/interests.json": _envelope("interest_tags", [INTEREST]),
        "items/job_types/jobs.json": _envelope("job_types", [job], version=2),
    }
    return _pack(files, manifest={"version": version, "replaces": replaces or []})


async def test_replaces_renames_the_row_and_keeps_its_uuid(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(
        db, store, source, _job_only_pack("old-role", "job-type:old-role", "1.0.0")
    )
    await _service(db, store).apply(source, first)
    old = await db.scalar(select(Job))
    assert old is not None
    old_id = old.id

    second = await _version(
        db,
        store,
        source,
        _job_only_pack("new-role", "job-type:new-role", "2.0.0", replaces=["old-role"]),
    )
    plan = await _service(db, store).build_plan(source, second)
    assert plan.warnings == []
    applied = await _service(db, store).apply(source, second)
    assert applied.status == "applied", applied.error
    db.expire_all()
    jobs = (await db.execute(select(Job))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].id == old_id
    assert jobs[0].code == "new-role"
    assert jobs[0].seed_key == "job-type:new-role"


async def test_an_unresolved_replace_is_a_warning_not_a_failure(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(
        db, store, source, _job_only_pack("old-role", "job-type:old-role", "1.0.0")
    )
    await _service(db, store).apply(source, first)
    second = await _version(
        db,
        store,
        source,
        _job_only_pack("new-role", "job-type:new-role", "2.0.0", replaces=["missing-role"]),
    )
    plan = await _service(db, store).build_plan(source, second)
    assert plan.status == "ok"
    assert [warning["code"] for warning in plan.warnings] == ["REPLACES_UNRESOLVED"]


async def test_an_occupied_admin_link_is_kept_with_a_warning(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(
        db, store, source, _job_only_pack("old-role", "job-type:old-role", "1.0.0")
    )
    await _service(db, store).apply(source, first)
    await db.execute(update(JobSkill).values(source="admin"))
    await db.execute(update(JobTag).values(source="admin"))
    await db.commit()

    second = await _version(
        db,
        store,
        source,
        _job_only_pack("old-role", "job-type:old-role", "2.0.0", title="Data Analyst II"),
    )
    plan = await _service(db, store).build_plan(source, second)
    codes = [warning["code"] for warning in plan.warnings]
    assert codes.count("EDGE_OCCUPIED") == 2
    applied = await _service(db, store).apply(source, second)
    assert applied.status == "applied", applied.error
    db.expire_all()
    skills = (await db.execute(select(JobSkill))).scalars().all()
    tags = (await db.execute(select(JobTag))).scalars().all()
    assert len(skills) == 1 and skills[0].source == "admin"
    assert len(tags) == 1 and tags[0].source == "admin"


async def test_a_user_modified_row_plans_an_override(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(
        db, store, source, _job_only_pack("old-role", "job-type:old-role", "1.0.0")
    )
    await _service(db, store).apply(source, first)
    job = await db.scalar(select(Job))
    assert job is not None
    await mark_user_modified(db, "job_type", job.id)
    await db.commit()

    second = await _version(
        db, store, source, _job_only_pack("old-role", "job-type:old-role", "2.0.0")
    )
    plan = await _service(db, store).build_plan(source, second)
    assert [item.action for item in plan.items if item.entity_type == "job_type"] == ["override"]
