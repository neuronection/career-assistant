"""Idempotent seeding: taxonomy + job catalog + starter paths. Run via scripts/seed.sh."""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.career_path_model import CareerPath, CareerPathStep
from app.models.enums import JobSkillImportance, PathSource, PathStatus
from app.models.job_model import Job, JobFamily, JobRelation, JobSkill, JobTag
from app.models.taxonomy_model import InterestTag, Skill
from app.seeds.catalog import EXPERIENCE_YEARS, FAMILIES, JOBS, PATHS, RELATIONS
from app.seeds.taxonomy import INTEREST_TAGS, SKILL_TAGS

logger = logging.getLogger("seed")


async def seed_taxonomy(db) -> tuple[int, int]:
    """Insert missing taxonomy tags."""
    i_added = s_added = 0
    for tag in INTEREST_TAGS:
        exists = (
            (await db.execute(select(InterestTag).where(InterestTag.key == tag["key"])))
            .scalars()
            .first()
        )
        if exists is None:
            db.add(InterestTag(**tag))
            i_added += 1
    for tag in SKILL_TAGS:
        exists = (
            (await db.execute(select(Skill).where(Skill.key == tag["key"])))
            .scalars()
            .first()
        )
        if exists is None:
            db.add(Skill(**tag))
            s_added += 1
    await db.commit()
    return i_added, s_added


async def seed_catalog(db) -> tuple[int, int]:
    """Insert missing families, jobs and relations."""
    family_ids: dict[str, object] = {}
    families_added = 0
    for spec in FAMILIES:
        exists = (
            (await db.execute(select(JobFamily).where(JobFamily.key == spec["key"])))
            .scalars()
            .first()
        )
        if exists:
            family_ids[spec["key"]] = exists
            continue
        parent = family_ids.get(spec.get("parent"))
        parent_id = parent.id if parent is not None else None
        level = 0
        path = spec["key"]
        if parent is not None:
            level = parent.level + 1
            path = f"{parent.path}/{spec['key']}"
        family = JobFamily(
            key=spec["key"],
            label=spec["label"],
            parent_id=parent_id,
            path=path,
            level=level,
            description=spec.get("description", ""),
        )
        db.add(family)
        await db.flush()
        family_ids[spec["key"]] = family
        families_added += 1

    jobs_added = 0
    for spec in JOBS:
        exists = (
            (await db.execute(select(Job).where(Job.code == spec["code"])))
            .scalars()
            .first()
        )
        if exists:
            continue
        family = family_ids.get(spec["family"])
        if family is None:
            logger.warning(
                "Job %s references unknown family %s", spec["code"], spec["family"]
            )
            continue
        job = Job(
            code=spec["code"],
            title=spec["title"],
            family_id=family.id,
            short_description=spec["description"],
            status="published",
            source="seed",
            attributes={
                "subjects": spec["subjects"],
                "experience_typical_years": list(
                    EXPERIENCE_YEARS.get(spec["code"], (0, 3))
                ),
                "work_style": spec["work_style"],
                "education": spec["education"],
                "physical": spec["physical"],
                "salary": spec["salary"],
                "demand": spec["demand"],
                "environments": spec["environments"],
                "typical_positives": spec["positives"],
                "typical_negatives": spec["negatives"],
            },
        )
        db.add(job)
        await db.flush()
        for key in spec["interests"]:
            tag = (
                (await db.execute(select(InterestTag).where(InterestTag.key == key)))
                .scalars()
                .first()
            )
            if tag is not None:
                db.add(JobTag(job_id=job.id, interest_tag_id=tag.id, source="seed"))
        for key in spec["skills"]:
            skill = (
                (await db.execute(select(Skill).where(Skill.key == key)))
                .scalars()
                .first()
            )
            if skill is not None:
                db.add(
                    JobSkill(
                        job_id=job.id,
                        skill_id=skill.id,
                        required_level=5,
                        importance=JobSkillImportance.IMPORTANT.value,
                        source="seed",
                    )
                )
            else:
                logger.warning("Job %s references unknown skill %s", spec["code"], key)
        jobs_added += 1
    await db.commit()

    code_to_id = {
        code: job_id
        for code, job_id in (await db.execute(select(Job.code, Job.id))).all()
    }
    relations_added = 0
    for rel in RELATIONS:
        from_id = code_to_id.get(rel["from"])
        to_id = code_to_id.get(rel["to"])
        if from_id is None or to_id is None:
            continue
        exists = (
            (
                await db.execute(
                    select(JobRelation).where(
                        JobRelation.from_job_id == from_id,
                        JobRelation.to_job_id == to_id,
                        JobRelation.relation_type == rel["type"],
                    )
                )
            )
            .scalars()
            .first()
        )
        if exists:
            continue
        db.add(
            JobRelation(
                from_job_id=from_id,
                to_job_id=to_id,
                relation_type=rel["type"],
                weight=rel["weight"],
                rationale=rel["rationale"],
                source="seed",
            )
        )
        relations_added += 1
    await db.commit()
    return jobs_added, relations_added


async def seed_paths(db) -> int:
    """Insert curated career paths for the starter catalog."""
    jobs = {j.code: j for j in (await db.execute(select(Job))).scalars().all()}
    skills = {s.key: s for s in (await db.execute(select(Skill))).scalars().all()}
    families = {f.key: f for f in (await db.execute(select(JobFamily))).scalars().all()}
    added = 0
    for spec in PATHS:
        job = jobs.get(spec["job"])
        if job is None:
            continue
        exists = (
            (
                await db.execute(
                    select(CareerPath).where(
                        CareerPath.job_id == job.id,
                        CareerPath.title
                        == spec[
                            "title"
                        ],  # label-compare-ok: seed idempotency; titles are the curated identity
                    )
                )
            )
            .scalars()
            .first()
        )
        if exists:
            continue
        path = CareerPath(
            job_id=job.id,
            title=spec["title"],
            description=spec.get("description", ""),
            source=PathSource.SEED.value,
            status=PathStatus.PUBLISHED.value,
        )
        db.add(path)
        await db.flush()
        for position, step in enumerate(spec["steps"]):
            skill = skills.get(step["skill_key"]) if step.get("skill_key") else None
            family = (
                families.get(step["family_key"]) if step.get("family_key") else None
            )
            db.add(
                CareerPathStep(
                    path_id=path.id,
                    position=position,
                    kind=step["kind"],
                    family_id=family.id if family else None,
                    skill_id=skill.id if skill else None,
                    education_level=step.get("education_level"),
                    label=step.get("label", ""),
                    optional=step.get("optional", False),
                )
            )
        added += 1
    await db.commit()
    return added


NOTIFICATION_KINDS = [
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8001",
        "key": "fit_threshold",
        "label": "Fit threshold reached",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": True,
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8002",
        "key": "new_in_family",
        "label": "New job in a followed family",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": True,
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8003",
        "key": "new_posting_match",
        "label": "New posting match",
        "group": "postings",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": True,
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8004",
        "key": "digest_ready",
        "label": "Weekly digest",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": True,
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8005",
        "key": "background_failed",
        "label": "Scheduled task failed",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": True,
    },
]


async def seed_notification_kinds(db) -> int:
    """Insert missing notification kinds (system data, stable keys)."""
    from app.models.engagement_model import NotificationKind

    added = 0
    for spec in NOTIFICATION_KINDS:
        exists = (
            (
                await db.execute(
                    select(NotificationKind).where(NotificationKind.key == spec["key"])
                )
            )
            .scalars()
            .first()
        )
        if exists is None:
            db.add(NotificationKind(**{**spec, "id": uuid.UUID(spec["id"])}))
            added += 1
    await db.commit()
    return added


async def run() -> None:
    """Seed everything (idempotent)."""
    logging.basicConfig(level=logging.INFO)
    async with AsyncSessionLocal() as db:
        i, s = await seed_taxonomy(db)
        logger.info("taxonomy: +%d interests, +%d skills", i, s)
        j, r = await seed_catalog(db)
        logger.info("catalog: +%d jobs, +%d relations", j, r)
        p = await seed_paths(db)
        logger.info("paths: +%d curated career paths", p)
        from app.seeds.assessment import seed_assessment_bank

        q = await seed_assessment_bank(db)
        logger.info("assessment: +%d bank questions", q)
        k = await seed_notification_kinds(db)
        logger.info("notifications: +%d kinds", k)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
