"""Catalog entity adapters for the seed lane (plan 224 S2).

The catalog formats are applied as data-only upserts against the existing
catalog tables. Identity is the stored ``seed_key``; first apply adopts a
pre-existing seeded row by its natural key. Removed rows retire (status flip)
rather than delete, except pack-owned relation edges, which are deleted. The
adapter writes the same rows JobService would (including pack-owned links) but
runs the catalog side effects explicitly once per stage: one vector-index job
per published job, one fit refit per job, one transferability recompute.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed_pack.errors import CATALOG_REF_UNRESOLVED, SeedPackError
from app.models.career_path_model import CareerPath, CareerPathStep
from app.models.enums.taxonomy import PathSource, PathStatus
from app.models.job_model import Job, JobFamily, JobRelation, JobSkill, JobTag
from app.models.taxonomy_model import InterestTag, Skill

ENTITY_FAMILY = "job_family"
ENTITY_JOB_TYPE = "job_type"
ENTITY_RELATION = "job_relation"
ENTITY_CAREER_PATH = "career_path"
ENTITY_SKILL = "skill"
ENTITY_INTEREST = "interest_tag"

ENTITY_MODELS: dict[str, Any] = {
    ENTITY_FAMILY: JobFamily,
    ENTITY_JOB_TYPE: Job,
    ENTITY_RELATION: JobRelation,
    ENTITY_CAREER_PATH: CareerPath,
    ENTITY_SKILL: Skill,
    ENTITY_INTEREST: InterestTag,
}
ITEM_ENTITY = {
    "job_families": ENTITY_FAMILY,
    "job_types": ENTITY_JOB_TYPE,
    "job_relations": ENTITY_RELATION,
    "career_paths": ENTITY_CAREER_PATH,
    "skills": ENTITY_SKILL,
    "interest_tags": ENTITY_INTEREST,
}
# Apply families before the jobs that point at them, taxonomy before links,
# relations/paths last; retire in reverse dependency order.
APPLY_ORDER = (
    ENTITY_FAMILY,
    ENTITY_SKILL,
    ENTITY_INTEREST,
    ENTITY_JOB_TYPE,
    ENTITY_RELATION,
    ENTITY_CAREER_PATH,
)
RETIRE_ORDER = tuple(reversed(APPLY_ORDER))


def stage(action: str, entity: str) -> int:
    order = RETIRE_ORDER if action == "retire" else APPLY_ORDER
    return order.index(entity) if entity in order else -1


async def load_current(db: AsyncSession) -> dict[tuple[str, str], Any]:
    current: dict[tuple[str, str], Any] = {}
    for entity, model in ENTITY_MODELS.items():
        rows = cast(
            list[Any],
            (await db.execute(select(model).where(model.seed_key.is_not(None)))).scalars().all(),
        )
        for row in rows:
            current[(entity, row.seed_key)] = row
    return current


async def _job_by_code(db: AsyncSession, code: str) -> Job | None:
    return (await db.execute(select(Job).where(Job.code == code).limit(1))).scalar_one_or_none()


async def _family_by_key(db: AsyncSession, key: str) -> JobFamily | None:
    return (
        await db.execute(select(JobFamily).where(JobFamily.key == key).limit(1))
    ).scalar_one_or_none()


async def _skill_by_key(db: AsyncSession, key: str) -> Skill | None:
    return (await db.execute(select(Skill).where(Skill.key == key).limit(1))).scalar_one_or_none()


async def _interest_by_key(db: AsyncSession, key: str) -> InterestTag | None:
    return (
        await db.execute(select(InterestTag).where(InterestTag.key == key).limit(1))
    ).scalar_one_or_none()


async def natural_match(db: AsyncSession, entity: str, payload: dict[str, Any]) -> Any | None:
    """Find a pre-existing seeded row (seed_key NULL) for first-apply adoption."""
    if entity == ENTITY_FAMILY:
        return await _family_by_key(db, str(payload["key"]))
    if entity == ENTITY_SKILL:
        return await _skill_by_key(db, str(payload["key"]))
    if entity == ENTITY_INTEREST:
        return await _interest_by_key(db, str(payload["key"]))
    if entity == ENTITY_JOB_TYPE:
        job = await _job_by_code(db, str(payload["code"]))
        return job if job is not None and job.source == "seed" else None
    if entity == ENTITY_RELATION:
        from_code = str(payload["from"])
        to_code = str(payload["to"])
        from_job = await _job_by_code(db, from_code)
        to_job = await _job_by_code(db, to_code)
        if from_job is None or to_job is None:
            return None
        return (
            await db.execute(
                select(JobRelation).where(
                    JobRelation.from_job_id == from_job.id,
                    JobRelation.to_job_id == to_job.id,
                    JobRelation.relation_type == str(payload["type"]),
                    JobRelation.source == "seed",
                )
            )
        ).scalar_one_or_none()
    if entity == ENTITY_CAREER_PATH:
        job = await _job_by_code(db, str(payload["job"]))
        if job is None:
            return None
        matches = (
            (
                await db.execute(
                    select(CareerPath).where(
                        CareerPath.job_id == job.id,
                        CareerPath.source == PathSource.SEED.value,
                        CareerPath.seed_key.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        # Adoption is unambiguous only when this job has one unkeyed seed path;
        # titles are display-only and never used for identity.
        return matches[0] if len(matches) == 1 else None
    return None


def _family_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(payload["key"]),
        "label": str(payload["label"]),
        "description": str(payload.get("description") or ""),
        "status": "published",
    }


def _skill_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(payload["key"]),
        "label": str(payload["label"]),
        "category": str(payload["category"]),
        "description": str(payload.get("description") or ""),
        "parent_source": payload.get("parent_source"),
        "status": "active",
        "origin": "bank",
    }


def _interest_fields(payload: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "key": str(payload["key"]),
        "label": str(payload["label"]),
        "category": str(payload["category"]),
        "description": str(payload.get("description") or ""),
        "deprecated": False,
    }
    if payload.get("kind"):
        fields["kind"] = str(payload["kind"])
    return fields


async def apply_family(
    db: AsyncSession, payload: dict[str, Any], row: JobFamily | None, *, seed_key: str
) -> JobFamily:
    fields = _family_fields(payload)
    if row is None:
        row = JobFamily(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    parent_key = payload.get("parent_key")
    if parent_key:
        parent = await _family_by_key(db, str(parent_key))
        if parent is None:
            raise SeedPackError(
                CATALOG_REF_UNRESOLVED, f"family {fields['key']} parent {parent_key!r} is missing"
            )
        row.parent_id = parent.id
        row.path = f"{parent.path}/{fields['key']}"
        row.level = parent.level + 1
    else:
        row.parent_id = None
        row.path = fields["key"]
        row.level = 0
    await db.flush()
    return row


async def apply_skill(
    db: AsyncSession, payload: dict[str, Any], row: Skill | None, *, seed_key: str
) -> Skill:
    fields = _skill_fields(payload)
    if row is None:
        row = Skill(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    parent_key = payload.get("parent_key")
    row.parent_id = None
    if parent_key:
        parent = await _skill_by_key(db, str(parent_key))
        if parent is None:
            raise SeedPackError(
                CATALOG_REF_UNRESOLVED, f"skill {fields['key']} parent {parent_key!r} is missing"
            )
        row.parent_id = parent.id
    await db.flush()
    return row


async def apply_interest(
    db: AsyncSession, payload: dict[str, Any], row: InterestTag | None, *, seed_key: str
) -> InterestTag:
    fields = _interest_fields(payload)
    if row is None:
        row = InterestTag(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    return row


async def _require_job(db: AsyncSession, code: str) -> Job:
    job = await _job_by_code(db, code)
    if job is None:
        raise SeedPackError(CATALOG_REF_UNRESOLVED, f"job {code!r} is missing")
    return job


async def apply_job_type(
    db: AsyncSession, payload: dict[str, Any], row: Job | None, *, seed_key: str, version_id
) -> Job:
    family = await _family_by_key(db, str(payload["family_key"]))
    if family is None:
        raise SeedPackError(
            CATALOG_REF_UNRESOLVED,
            f"job {payload['code']} family {payload['family_key']!r} is missing",
        )
    fields = {
        "code": str(payload["code"]),
        "title": str(payload["title"]),
        "family_id": family.id,
        "short_description": str(payload.get("summary") or ""),
        "status": "published",
        "source": "seed",
        "attributes": payload.get("attributes") or {},
    }
    if row is None:
        row = Job(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    await _reconcile_links(db, row, payload)
    return row


async def _reconcile_links(db: AsyncSession, job: Job, payload: dict[str, Any]) -> None:
    desired_interests = {str(key) for key in payload.get("interests") or []}
    desired_skills = {str(ref["skill_key"]): ref for ref in payload.get("skills") or []}

    tag_rows = (await db.execute(select(JobTag).where(JobTag.job_id == job.id))).scalars().all()
    tags_by_key: dict[str, JobTag] = {}
    for tag_link in tag_rows:
        tag = await db.get(InterestTag, tag_link.interest_tag_id)
        if tag is not None:
            tags_by_key[tag.key] = tag_link
    for key in desired_interests:
        tag = await _interest_by_key(db, key)
        if tag is None:
            raise SeedPackError(CATALOG_REF_UNRESOLVED, f"interest {key!r} is missing")
        existing = tags_by_key.get(key)
        if existing is None:
            db.add(JobTag(job_id=job.id, interest_tag_id=tag.id, source="seed"))
        elif existing.source == "seed":
            existing.interest_tag_id = tag.id
    for key, tag_link in tags_by_key.items():
        if key not in desired_interests and tag_link.source == "seed":
            await db.delete(tag_link)

    skill_rows = (
        (await db.execute(select(JobSkill).where(JobSkill.job_id == job.id))).scalars().all()
    )
    skills_by_key: dict[str, JobSkill] = {}
    for skill_link in skill_rows:
        skill = await db.get(Skill, skill_link.skill_id)
        if skill is not None:
            skills_by_key[skill.key] = skill_link
    for key, ref in desired_skills.items():
        skill = await _skill_by_key(db, key)
        if skill is None:
            raise SeedPackError(CATALOG_REF_UNRESOLVED, f"skill {key!r} is missing")
        existing_skill = skills_by_key.get(key)
        if existing_skill is None:
            db.add(
                JobSkill(
                    job_id=job.id,
                    skill_id=skill.id,
                    required_level=int(ref.get("required_level", 5)),
                    importance=str(ref.get("importance", "important")),
                    source="seed",
                )
            )
        elif existing_skill.source == "seed":
            existing_skill.required_level = int(ref.get("required_level", 5))
            existing_skill.importance = str(ref.get("importance", "important"))
    for key, skill_link in skills_by_key.items():
        if key not in desired_skills and skill_link.source == "seed":
            await db.delete(skill_link)
    await db.flush()


async def apply_relation(
    db: AsyncSession, payload: dict[str, Any], row: JobRelation | None, *, seed_key: str
) -> JobRelation:
    from_job = await _require_job(db, str(payload["from"]))
    to_job = await _require_job(db, str(payload["to"]))
    fields = {
        "from_job_id": from_job.id,
        "to_job_id": to_job.id,
        "relation_type": str(payload["type"]),
        "weight": float(payload.get("weight", 0.5)),
        "rationale": str(payload.get("rationale") or ""),
        "source": "seed",
        "confidence": 1.0,
    }
    if row is None:
        row = JobRelation(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    return row


async def apply_career_path(
    db: AsyncSession, payload: dict[str, Any], row: CareerPath | None, *, seed_key: str
) -> CareerPath:
    job = await _require_job(db, str(payload["job"]))
    fields = {
        "job_id": job.id,
        "title": str(payload["title"]),
        "description": str(payload.get("description") or ""),
        "source": PathSource.SEED.value,
        "status": PathStatus.PUBLISHED.value,
    }
    if row is None:
        row = CareerPath(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()

    existing = (
        (await db.execute(select(CareerPathStep).where(CareerPathStep.path_id == row.id)))
        .scalars()
        .all()
    )
    for step in existing:
        await db.delete(step)
    await db.flush()
    for position, raw in enumerate(payload.get("steps") or []):
        family_id = None
        skill_id = None
        if raw.get("family_key"):
            family = await _family_by_key(db, str(raw["family_key"]))
            if family is None:
                raise SeedPackError(
                    CATALOG_REF_UNRESOLVED, f"path family {raw['family_key']!r} is missing"
                )
            family_id = family.id
        if raw.get("skill_key"):
            skill = await _skill_by_key(db, str(raw["skill_key"]))
            if skill is None:
                raise SeedPackError(
                    CATALOG_REF_UNRESOLVED, f"path skill {raw['skill_key']!r} is missing"
                )
            skill_id = skill.id
        db.add(
            CareerPathStep(
                path_id=row.id,
                position=position,
                kind=str(raw["kind"]),
                family_id=family_id,
                skill_id=skill_id,
                education_level=raw.get("education_level"),
                label=str(raw.get("label") or ""),
                optional=bool(raw.get("optional", False)),
            )
        )
    await db.flush()
    return row


async def retire(db: AsyncSession, entity: str, row: Any) -> None:
    if entity in (ENTITY_FAMILY, ENTITY_JOB_TYPE):
        row.status = "retired"
    elif entity == ENTITY_SKILL:
        row.status = "deprecated"
    elif entity == ENTITY_INTEREST:
        row.deprecated = True
    elif entity == ENTITY_CAREER_PATH:
        row.status = PathStatus.RETIRED.value
    elif entity == ENTITY_RELATION:
        await db.delete(row)
    await db.flush()


async def mark_user_modified(db: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> None:
    """Protect a pack-owned row's direct admin edit from the next pack apply."""
    from app.models.seed_model import SeedItemProvenance

    provenance = (
        await db.execute(
            select(SeedItemProvenance).where(
                SeedItemProvenance.entity_type == entity_type,
                SeedItemProvenance.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    if provenance is not None and not provenance.user_modified:
        provenance.user_modified = True
        await db.flush()


async def job_side_effects(db: AsyncSession, job_ids: list[uuid.UUID]) -> None:
    from app.services.catalog.job_service import JobService

    await JobService(db).seed_write_side_effects(job_ids)
    await db.flush()


__all__ = [
    "APPLY_ORDER",
    "ENTITY_CAREER_PATH",
    "ENTITY_FAMILY",
    "ENTITY_INTEREST",
    "ENTITY_JOB_TYPE",
    "ENTITY_MODELS",
    "ENTITY_RELATION",
    "ENTITY_SKILL",
    "ITEM_ENTITY",
    "RETIRE_ORDER",
    "apply_career_path",
    "apply_family",
    "apply_interest",
    "apply_job_type",
    "apply_relation",
    "apply_skill",
    "job_side_effects",
    "load_current",
    "mark_user_modified",
    "natural_match",
    "retire",
    "stage",
]
