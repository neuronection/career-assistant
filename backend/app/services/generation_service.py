"""AI job-generation pipeline: context gathering → agent → draft creation.

Extracted from the /jobs/generate endpoint so it can run synchronously (small
requests) or inside a background job (queue handler) without duplication.
"""

import uuid
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import generate_jobs
from app.core.errors import DomainError
from app.models.enums import JobSource
from app.models.job_model import JobRelation
from app.schemas.job import JobCreate, JobOut
from app.services.job_service import JobService
from app.services.profile_service import ProfileService
from app.services.taxonomy_service import TaxonomyService

ProgressCb = Callable[[int, str], Awaitable[None]]
CancelledCb = Callable[[], Awaitable[bool]]


async def _noop_progress(progress: int, stage: str) -> None:
    return None


async def _never_cancelled() -> bool:
    return False


async def run_generation(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: dict,
    *,
    progress: ProgressCb = _noop_progress,
    cancelled: CancelledCb = _never_cancelled,
) -> dict:
    """Generate job drafts + relation suggestions from a payload spec.

    Payload keys: mode, prompt, criteria, count — exactly the endpoint body.
    Returns the same shape as the historical endpoint response.
    """
    service = JobService(db)
    profile_service = ProfileService(db)
    profile = await profile_service.get(user_id)
    mode = payload.get("mode", "general")
    prompt = payload.get("prompt")
    criteria = payload.get("criteria") or {}
    count = int(payload.get("count", 5))

    await progress(10, "gathering catalog context")
    families = await service.families()
    interests = [i for i in await TaxonomyService(db).interests() if not i.deprecated]
    skills = await TaxonomyService(db).skills(status="active")
    existing_jobs, _ = await service.list_jobs(status=None, page_size=500)
    existing_codes = [j.code for j in existing_jobs]

    if await cancelled():
        raise DomainError("Cancelled")

    await progress(30, "calling the model")
    draft_set = await generate_jobs(
        db,
        user_id,
        mode=mode,
        prompt=prompt,
        criteria=criteria,
        count=count,
        family_keys=[f.key for f in families],
        interest_keys=[i.key for i in interests],
        skill_keys=[s.key for s in skills],
        profile_snapshot=await profile_service.snapshot(profile),
        existing_codes=existing_codes,
    )

    await progress(70, "writing drafts")
    from app.models.user_model import User
    from app.schemas.job import JobSkillIn

    user = await db.get(User, user_id)
    active_interests = {i.key for i in interests}
    active_skills = {s.key for s in skills}
    created_jobs = []
    seen_codes = set(existing_codes)
    for draft in draft_set.drafts:
        if await cancelled():
            raise DomainError("Cancelled")
        if draft.code in seen_codes:
            continue
        family = next((f for f in families if f.key == draft.family_key), None)
        if family is None:
            continue
        job = await service.create(
            JobCreate(
                code=draft.code,
                title=draft.title,
                family_key=draft.family_key,
                short_description=draft.short_description,
                attributes=draft.attributes,
                interest_keys=[k for k in draft.interest_keys if k in active_interests],
                skills=[
                    JobSkillIn(
                        skill_key=s.skill_key,
                        required_level=s.required_level,
                        importance=s.importance,
                    )
                    for s in draft.skills
                    if s.skill_key in active_skills
                ],
            ),
            user,
            source=JobSource.AI.value,
        )
        job.ai_metadata = {"rationale_note": draft_set.rationale_note}
        seen_codes.add(job.code)
        created_jobs.append(job)
    await db.commit()

    created_relations = []
    for rel in draft_set.relation_suggestions:
        from_job = await service.get_by_code_or_id(rel.from_code)
        to_job = await service.get_by_code_or_id(rel.to_code)
        if not from_job or not to_job:
            continue
        duplicate = await db.execute(
            select(JobRelation).where(
                JobRelation.from_job_id == from_job.id,
                JobRelation.to_job_id == to_job.id,
                JobRelation.relation_type == rel.relation_type.value,
            )
        )
        if duplicate.scalars().first():
            continue
        db.add(
            JobRelation(
                from_job_id=from_job.id,
                to_job_id=to_job.id,
                relation_type=rel.relation_type.value,
                weight=rel.weight,
                rationale=rel.rationale,
                source="ai",
                confidence=rel.confidence,
            )
        )
        created_relations.append((rel.from_code, rel.to_code, rel.relation_type.value))
    await db.commit()

    await progress(100, "done")
    return {
        "drafts": [JobOut.from_model(j) for j in created_jobs],
        "relations": [
            {"from_code": f, "to_code": t, "relation_type": rt}
            for f, t, rt in created_relations
        ],
        "note": draft_set.rationale_note,
    }
