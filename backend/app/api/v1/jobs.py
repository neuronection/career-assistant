from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import suggest_relations
from app.core.database import get_db
from app.core.errors import DomainError
from app.models.enums import BackgroundJobType
from app.schemas.common import Message
from app.schemas.job import JobCreate, JobGraph, JobOut, JobUpdate, RelationOut
from app.services.deps import get_current_user
from app.services.job_service import JobService
from app.services.job_worker import enqueue

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/tree")
async def family_tree(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Job families as a nested tree with published job counts."""
    return await JobService(db).family_tree()


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
                relation_type=rel.relation_type,
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
    peers, _ = await service.list_jobs(family_key=job.family.key, page_size=12)
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
            relation_type=rel.relation_type,
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
    job = await enqueue(
        db, BackgroundJobType.JOB_GENERATE.value, payload, user_id=user.id
    )
    return {"job_id": str(job.id), "status": job.status}


@router.post("/{ref}/publish", response_model=JobOut)
async def publish_job(
    ref: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> JobOut:
    """Publish an AI/user draft job."""
    service = JobService(db)
    job = await service.require_job(ref)
    job.status = "published"
    await db.commit()
    await db.refresh(job)
    job = await service._get_with_family(job.id)
    await service.notify_published(job)
    await service._refit_job(job.id)
    return JobOut.from_model(job)


@router.get("", response_model=list[JobOut])
async def list_jobs(
    q: str | None = Query(default=None),
    family: str | None = Query(default=None, alias="family_key"),
    interests: str | None = Query(default=None, description="comma-separated tag keys"),
    demand: str | None = Query(default=None),
    education_level: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    source: str | None = Query(default=None),
    min_salary: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[JobOut]:
    """Search/filter the job catalog."""
    interest_keys = [k.strip() for k in interests.split(",")] if interests else None
    jobs, _total = await JobService(db).list_jobs(
        q=q,
        family_key=family,
        interest_keys=interest_keys,
        demand=demand,
        education_level=education_level,
        environment=environment,
        source=source,
        min_salary=min_salary,
        page=page,
        page_size=page_size,
    )
    return [JobOut.from_model(j) for j in jobs]


@router.post("", response_model=JobOut, status_code=201)
async def create_job(
    data: JobCreate, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> JobOut:
    """Manually add a job to the catalog."""
    try:
        job = await JobService(db).create(data, user, source="user")
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return JobOut.from_model(job)


@router.get("/{ref}", response_model=JobOut)
async def get_job(
    ref: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> JobOut:
    """Job detail by id or code."""
    try:
        job = await JobService(db).require_job(ref)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return JobOut.from_model(job)


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
    return JobOut.from_model(job)


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
