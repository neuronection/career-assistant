"""Plan 224 S3: the published job-catalog pack reproduces the curated catalog."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from app.core.seed_pack.export import read_pack_dir
from app.models.career_path_model import CareerPath, CareerPathStep
from app.models.job_model import Job, JobFamily, JobRelation, JobSkill, JobTag
from app.models.taxonomy_model import InterestTag, Skill
from tests.test_seed_apply import _service, _source, _store, _version

FIXTURES = Path(__file__).parent / "fixtures" / "seed_packs"
PACK = FIXTURES / "packs" / "neuronection" / "job-catalog"
SEEDS = Path(__file__).resolve().parents[1] / "app" / "data" / "seeds"


def _expected() -> tuple[int, int, int, int, int, int, int, int]:
    catalog = json.loads((SEEDS / "catalog.json").read_text(encoding="utf-8"))
    taxonomy = json.loads((SEEDS / "taxonomy.json").read_text(encoding="utf-8"))
    skill_keys = {tag["key"] for tag in taxonomy["SKILL_TAGS"]}
    interest_keys = {tag["key"] for tag in taxonomy["INTEREST_TAGS"]}
    skills = sum(
        len([key for key in job["skills"] if key in skill_keys]) for job in catalog["JOBS"]
    )
    interests = sum(
        len([key for key in job["interests"] if key in interest_keys]) for job in catalog["JOBS"]
    )
    return (
        len(catalog["FAMILIES"]),
        len(catalog["JOBS"]),
        len(catalog["RELATIONS"]),
        len(catalog["PATHS"]),
        len(taxonomy["SKILL_TAGS"]),
        len(taxonomy["INTEREST_TAGS"]),
        skills,
        interests,
    )


async def _operator_source(db):
    source = await _source(db)
    source.trust_tier = "operator"
    await db.commit()
    await db.refresh(source)
    return source


async def _apply_pack(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, read_pack_dir(PACK))
    plan = await _service(db, store).build_plan(source, version)
    assert plan.status == "ok", plan.conflicts
    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error
    return source, version, store


async def test_the_pack_reproduces_todays_catalog_and_is_idempotent(db, tmp_path):
    families, jobs, relations, paths, skills, interests, job_skills, job_tags = _expected()
    source, version, store = await _apply_pack(db, tmp_path)

    assert await db.scalar(select(func.count()).select_from(JobFamily)) == families
    assert await db.scalar(select(func.count()).select_from(Job)) == jobs
    assert await db.scalar(select(func.count()).select_from(JobRelation)) == relations
    assert await db.scalar(select(func.count()).select_from(CareerPath)) == paths
    assert await db.scalar(select(func.count()).select_from(Skill)) == skills
    assert await db.scalar(select(func.count()).select_from(InterestTag)) == interests
    assert await db.scalar(select(func.count()).select_from(JobSkill)) == job_skills
    assert await db.scalar(select(func.count()).select_from(JobTag)) == job_tags
    assert await db.scalar(select(func.count()).select_from(Job).where(Job.seed_key.is_(None))) == 0
    assert (
        await db.scalar(
            select(func.count()).select_from(CareerPath).where(CareerPath.seed_key.is_(None))
        )
        == 0
    )

    second = await _service(db, store).apply(source, version)
    assert second.status == "noop"
    assert await db.scalar(select(func.count()).select_from(Job)) == jobs


async def test_the_pack_adopts_a_seeded_catalog_without_duplicates(db, tmp_path):
    from app.seeds.run import seed_catalog, seed_taxonomy

    await seed_taxonomy(db)
    await seed_catalog(db)
    await db.commit()
    before = {row.code: row.id for row in (await db.execute(select(Job))).scalars().all()}
    family_ids = {row.key: row.id for row in (await db.execute(select(JobFamily))).scalars().all()}

    await _apply_pack(db, tmp_path)

    after = (await db.execute(select(Job))).scalars().all()
    assert len(after) == len(before)
    assert {row.code: row.id for row in after} == before
    assert all(row.seed_key == f"job-type:{row.code}" for row in after)
    assert {row.key: row.id for row in (await db.execute(select(JobFamily))).scalars().all()} == (
        family_ids
    )


async def test_every_row_matches_the_curated_source(db, tmp_path):
    await _apply_pack(db, tmp_path)
    catalog = json.loads((SEEDS / "catalog.json").read_text(encoding="utf-8"))
    taxonomy = json.loads((SEEDS / "taxonomy.json").read_text(encoding="utf-8"))
    skill_keys = {tag["key"] for tag in taxonomy["SKILL_TAGS"]}
    interest_keys = {tag["key"] for tag in taxonomy["INTEREST_TAGS"]}

    skill_rows = (await db.execute(select(Skill))).scalars().all()
    skills = {row.id: row.key for row in skill_rows}
    skill_ids = {row.key: row.id for row in skill_rows}
    tags = {row.id: row.key for row in (await db.execute(select(InterestTag))).scalars().all()}
    families = {row.id: row.key for row in (await db.execute(select(JobFamily))).scalars().all()}
    job_skills: dict = {}
    for link in (await db.execute(select(JobSkill))).scalars().all():
        job_skills.setdefault(link.job_id, set()).add(skills[link.skill_id])
    job_tags: dict = {}
    for link in (await db.execute(select(JobTag))).scalars().all():
        job_tags.setdefault(link.job_id, set()).add(tags[link.interest_tag_id])

    jobs = (await db.execute(select(Job))).scalars().all()
    assert len(jobs) == len(catalog["JOBS"])
    for spec in catalog["JOBS"]:
        job = next(row for row in jobs if row.code == spec["code"])
        assert job.title == spec["title"]
        assert job.short_description == spec["description"]
        assert job.family_id in families and families[job.family_id] == spec["family"]
        assert job.attributes["subjects"] == spec["subjects"]
        assert job.attributes["work_style"] == spec["work_style"]
        assert job.attributes["education"] == spec["education"]
        assert job.attributes["typical_positives"] == spec["positives"]
        assert job.attributes["typical_negatives"] == spec["negatives"]
        assert job_skills.get(job.id, set()) == {key for key in spec["skills"] if key in skill_keys}
        assert job_tags.get(job.id, set()) == {
            key for key in spec["interests"] if key in interest_keys
        }

    job_codes = {row.id: row.code for row in jobs}
    relations = {
        (job_codes[rel.from_job_id], job_codes[rel.to_job_id], rel.relation_type): (
            rel.weight,
            rel.rationale,
        )
        for rel in (await db.execute(select(JobRelation))).scalars().all()
    }
    assert relations == {
        (spec["from"], spec["to"], spec["type"]): (spec["weight"], spec["rationale"])
        for spec in catalog["RELATIONS"]
    }

    paths = {row.title: row for row in (await db.execute(select(CareerPath))).scalars().all()}
    assert set(paths) == {spec["title"] for spec in catalog["PATHS"]}
    for spec in catalog["PATHS"]:
        path = paths[spec["title"]]
        assert path.description == spec["description"]
        steps = (
            (
                await db.execute(
                    select(CareerPathStep)
                    .where(CareerPathStep.path_id == path.id)
                    .order_by(CareerPathStep.position)
                )
            )
            .scalars()
            .all()
        )
        assert [step.kind for step in steps] == [step["kind"] for step in spec["steps"]]
        assert [step.label for step in steps] == [step.get("label", "") for step in spec["steps"]]
        assert [step.optional for step in steps] == [
            step.get("optional", False) for step in spec["steps"]
        ]
        assert [step.education_level for step in steps] == [
            step.get("education_level") for step in spec["steps"]
        ]
        assert [step.skill_id for step in steps] == [
            skill_ids.get(step["skill_key"]) if step.get("skill_key") else None
            for step in spec["steps"]
        ]

    assert await db.scalar(select(func.count()).select_from(JobFamily)) == len(catalog["FAMILIES"])
