from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import suggest_relations
from app.core.database import get_db
from app.core.errors import DomainError
from app.models.enums import BackgroundJobType, RelationType
from app.schemas.common import Message
from app.schemas.job import (
    JobCreate,
    JobGraph,
    JobOut,
    JobPostingsOut,
    JobsPageOut,
    JobUpdate,
    RelationOut,
    SimilarJobsOut,
)
from app.services.catalog.job_service import JobService
from app.services.deps import get_current_user
from app.services.job_worker import enqueue

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [part.strip() for part in value.split(",") if part.strip()]
    return items or None


def _skill_entries(value: str | None) -> list[tuple[str, int | None]] | None:
    if not value:
        return None
    entries: list[tuple[str, int | None]] = []
    for part in value.split(","):
        entry = part.strip()
        if not entry:
            continue
        key, separator, raw_level = entry.partition("@")
        key = key.strip().lower()
        if not key:
            continue
        if not separator or not raw_level:
            entries.append((key, None))
            continue
        try:
            level = int(raw_level)
        except ValueError:
            continue
        if 1 <= level <= 10:
            entries.append((key, level))
    return entries or None


@router.get("/tree")
async def family_tree(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Job families as a nested tree with published job counts."""
    from app.services.catalog.localized_view import localize_family_tree, resolve_locale

    tree = await JobService(db).family_tree()
    return await localize_family_tree(db, tree, await resolve_locale(db, user))


@router.get("/graph", response_model=JobGraph)
async def graph(
    root: str | None = Query(default=None),
    depth: int = Query(default=2, ge=1, le=4),
    family: str | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobGraph:
    """Relation-graph payload (nodes + typed edges) for reactflow."""
    try:
        data = await JobService(db).graph(root=root, depth=depth, family_key=family)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return JobGraph.model_validate(data)


@router.get("/relations/{ref}", response_model=list[RelationOut])
async def relations(
    ref: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[RelationOut]:
    """All relations touching a job."""
    rows = await JobService(db).relations(ref)
    out = []
    for rel in rows:
        out.append(
            RelationOut(
                id=rel.id,
                from_code=rel.from_job.code,
                to_code=rel.to_job.code,
                from_title=rel.from_job.title,
                to_title=rel.to_job.title,
                relation_type=RelationType(rel.relation_type),
                weight=rel.weight,
                rationale=rel.rationale,
                source=rel.source,
            )
        )
    return out


@router.post("/{ref}/relations/suggest", response_model=list[RelationOut])
async def suggest_job_relations(
    ref: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[RelationOut]:
    """AI-propose relations between this job and same-family peers (stored as ai)."""
    service = JobService(db)
    job = await service.require_job(ref)
    peers, _, _ = await service.list_jobs(family_key=job.family.key, page_size=12)
    candidates = [j for j in peers if j.id != job.id][:11]
    snapshots = [service.job_snapshot(j) for j in [job, *candidates]]
    suggestions = await suggest_relations(db, user.id, snapshots, max_suggestions=8)
    from app.models.job_model import JobRelation

    created = []
    for rel in suggestions:
        to_job = await service.get_by_code_or_id(rel.to_code)
        if to_job is None:
            continue
        duplicate = await db.execute(
            select(JobRelation).where(
                JobRelation.from_job_id == job.id,
                JobRelation.to_job_id == to_job.id,
                JobRelation.relation_type == rel.relation_type.value,
            )
        )
        existing = duplicate.scalars().first()
        if existing:
            continue
        relation = JobRelation(
            from_job_id=job.id,
            to_job_id=to_job.id,
            relation_type=rel.relation_type.value,
            weight=rel.weight,
            rationale=rel.rationale,
            source="ai",
            confidence=rel.confidence,
        )
        db.add(relation)
        created.append((relation, to_job, rel))
    await db.commit()
    return [
        RelationOut(
            id=relation_row.id,
            from_code=job.code,
            to_code=to_job.code,
            from_title=job.title,
            to_title=to_job.title,
            relation_type=RelationType(rel.relation_type),
            weight=rel.weight,
            rationale=rel.rationale,
            source="ai",
        )
        for relation_row, to_job, rel in created
    ]


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate(
    body: dict,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Queue AI job generation; poll /background-jobs/{job_id} for progress."""
    payload = {
        "mode": body.get("mode", "general"),
        "prompt": body.get("prompt"),
        "criteria": body.get("criteria") or {},
        "count": int(body.get("count", 5)),
    }
    job = await enqueue(db, BackgroundJobType.JOB_GENERATE.value, payload, user_id=user.id)
    return {"job_id": str(job.id), "status": job.status}


@router.post("/{ref}/publish", response_model=JobOut)
async def publish_job(
    ref: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> JobOut:
    """Publish an AI/user draft job."""
    service = JobService(db)
    job = await service.require_job(ref)
    if job.status == "retired":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A retired job type cannot be republished",
        )
    job.status = "published"
    await db.commit()
    await db.refresh(job)
    job = await service._get_with_family(job.id)
    await service.notify_published(job)
    await service._refit_job(job.id)
    await service._refresh_transferability()
    from app.services.catalog.job_service import enqueue_job_index

    await enqueue_job_index(db, job)
    from app.services.catalog.localized_view import job_out, resolve_locale

    return await job_out(db, job, await resolve_locale(db, user))


@router.get("", response_model=JobsPageOut)
async def list_jobs(
    q: str | None = Query(default=None),
    family: str | None = Query(default=None, alias="family_key"),
    interests: str | None = Query(default=None, description="comma-separated tag keys"),
    interest_exclude: str | None = Query(default=None),
    demand: str | None = Query(default=None),
    demand_exclude: str | None = Query(default=None),
    education: str | None = Query(default=None, description="comma-separated levels"),
    education_exclude: str | None = Query(default=None),
    education_min: str | None = Query(default=None),
    skills: str | None = Query(default=None, description="key@level CSV"),
    skill_exclude: str | None = Query(default=None),
    skill_mode: str = Query(default="all", pattern="^(all|any)$"),
    skill_min_level: int | None = Query(default=None, ge=1, le=10),
    environment: str | None = Query(default=None),
    environment_exclude: str | None = Query(default=None),
    contract: str | None = Query(default=None),
    contract_exclude: str | None = Query(default=None),
    schedule: str | None = Query(default=None),
    schedule_exclude: str | None = Query(default=None),
    travel: str | None = Query(default=None),
    travel_exclude: str | None = Query(default=None),
    source: str | None = Query(default=None),
    source_exclude: str | None = Query(default=None),
    salary_min: int | None = Query(default=None, ge=0),
    salary_max: int | None = Query(default=None, ge=0),
    experience_max_years: float | None = Query(default=None, ge=0),
    has_roles: bool | None = Query(default=None),
    status: str | None = Query(default="published"),
    sort: str = Query(default="title", pattern="^(title|demand|salary|open_roles|family)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    with_facets: bool = Query(default=True),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobsPageOut:
    """Search/filter the job catalog; items carry the page's live-role count."""
    service = JobService(db)
    jobs, total, facets = await service.list_jobs(
        q=q,
        family_key=family,
        interest_keys=_csv(interests),
        interest_exclude=_csv(interest_exclude),
        demand=_csv(demand),
        demand_exclude=_csv(demand_exclude),
        education=_csv(education),
        education_exclude=_csv(education_exclude),
        education_min=education_min,
        skills=_skill_entries(skills),
        skill_exclude=_csv(skill_exclude),
        skill_mode=skill_mode,
        skill_min_level=skill_min_level,
        environment=_csv(environment),
        environment_exclude=_csv(environment_exclude),
        source=_csv(source),
        source_exclude=_csv(source_exclude),
        contract=_csv(contract),
        contract_exclude=_csv(contract_exclude),
        schedule=_csv(schedule),
        schedule_exclude=_csv(schedule_exclude),
        travel=_csv(travel),
        travel_exclude=_csv(travel_exclude),
        experience_max_years=experience_max_years,
        salary_min=salary_min,
        salary_max=salary_max,
        has_roles=has_roles,
        status=status,
        sort=sort,
        page=page,
        page_size=page_size,
        with_facets=with_facets,
    )
    from app.services.catalog.localized_view import job_outs, resolve_locale

    items = await job_outs(db, jobs, await resolve_locale(db, user))
    counts = await service.open_role_counts([job.id for job in jobs])
    return JobsPageOut(
        items=[item.model_copy(update={"open_roles": counts.get(item.id, 0)}) for item in items],
        total=total,
        facets=facets,
    )


@router.post("", response_model=JobOut, status_code=201)
async def create_job(
    data: JobCreate, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> JobOut:
    """Manually add a job to the catalog."""
    try:
        job = await JobService(db).create(data, user, source="user")
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    from app.services.catalog.localized_view import job_out, resolve_locale

    return await job_out(db, job, await resolve_locale(db, user))


@router.get("/{ref}", response_model=JobOut)
async def get_job(
    ref: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> JobOut:
    """Job detail by id or code."""
    try:
        job = await JobService(db).require_job(ref)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    from app.services.catalog.localized_view import job_out, resolve_locale

    return await job_out(db, job, await resolve_locale(db, user))


@router.get("/{ref}/similar", response_model=SimilarJobsOut)
async def similar_jobs(
    ref: str,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=500),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SimilarJobsOut:
    """Similar published catalog jobs (semantic, skill-overlap fallback)."""
    try:
        job = await JobService(db).require_job(ref)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    from app.services.catalog.job_match_service import JobMatchService

    payload = await JobMatchService(db).similar_jobs(job, limit=limit, offset=offset)
    return SimilarJobsOut.model_validate(payload)


@router.get("/{ref}/postings", response_model=JobPostingsOut)
async def job_live_postings(
    ref: str,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=500),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobPostingsOut:
    """Live postings ranked against this catalog job (visibility-filtered)."""
    try:
        job = await JobService(db).require_job(ref)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    from app.services.catalog.job_match_service import JobMatchService

    payload = await JobMatchService(db).live_postings(
        job, user_id=user.id, limit=limit, offset=offset
    )
    return JobPostingsOut.model_validate(payload)


@router.put("/{ref}", response_model=JobOut)
async def update_job(
    ref: str,
    data: JobUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    """Update a catalog job."""
    try:
        job = await JobService(db).update(ref, data, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.refresh(job)
    from app.services.catalog.localized_view import job_out, resolve_locale

    return await job_out(db, job, await resolve_locale(db, user))


@router.delete("/{ref}", response_model=Message)
async def delete_job(
    ref: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Message:
    """Delete a user/AI job (seeded jobs are protected)."""
    try:
        await JobService(db).delete(ref, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return Message(message="deleted")
