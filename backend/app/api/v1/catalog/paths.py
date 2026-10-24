"""Career paths: curated routes + computed graph + the user explorer."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.models.enums import CareerStage
from app.schemas.paths import CareerPathOut, PathDetailOut, PathFlagIn, PathGraphOut
from app.services.catalog.job_service import JobService
from app.services.catalog.paths_service import PathService
from app.services.deps import get_current_user

router = APIRouter(tags=["paths"])


@router.get("/paths", response_model=list[CareerPathOut])
async def list_paths(
    job: str | None = Query(default=None),
    family: str | None = Query(default=None),
    stage: CareerStage | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CareerPathOut]:
    """Published paths + the caller's own copies (filterable by target
    job reference, target-job family key or career stage)."""
    job_id = None
    if job:
        found = await JobService(db).get_by_code_or_id(job)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
        job_id = found.id
    return await PathService(db).index(user, job_id=job_id, family_key=family, stage=stage)


@router.get("/paths/{path_id}", response_model=PathDetailOut)
async def path_detail(
    path_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """One path with the caller's marks and per-step skill gaps."""
    try:
        path = await PathService(db).require_visible(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return await PathService(db).detail(path, user)


@router.put("/paths/{path_id}/flags", response_model=PathDetailOut)
async def set_path_flag(
    path_id: uuid.UUID,
    payload: PathFlagIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Set or clear one mark (interested/dismissed/pinned) on the path or
    a step. Marks are preferences — they never feed fit or scores."""
    service = PathService(db)
    try:
        path = await service.require_visible(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if payload.step_id is not None and not any(step.id == payload.step_id for step in path.steps):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Step not found")
    await service.set_flag(
        path,
        user,
        step_id=payload.step_id,
        flag=payload.flag,
        note=payload.note,
    )
    fresh = await service.require_visible(path_id, user)
    return await service.detail(fresh, user)


@router.get("/jobs/{ref}/paths", response_model=list[CareerPathOut])
async def job_paths(
    ref: str,
    include_drafts: bool = Query(default=False),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CareerPathOut]:
    """Curated + AI-drafted paths towards this job (drafts: admin only)."""
    if include_drafts and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    try:
        job = await JobService(db).require_job(ref)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    from app.services.profile.stages_service import stage_for_user

    stage, _source = await stage_for_user(db, user.id)
    return await PathService(db).paths_out(
        job.id, include_drafts=include_drafts, stage=stage, user_id=user.id
    )


@router.get("/jobs/{ref}/paths/graph", response_model=PathGraphOut)
async def job_paths_graph(
    ref: str,
    depth: int = Query(default=4, ge=1, le=4),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathGraphOut:
    """Computed graph of jobs leading into this one (BFS, cycle-safe)."""
    try:
        job = await JobService(db).require_job(ref)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return await PathService(db).graph(job, depth=depth)


@router.post("/jobs/{ref}/paths/suggest", status_code=status.HTTP_202_ACCEPTED)
async def suggest_job_paths(
    ref: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Queue AI path drafting for jobs missing them; poll /background-jobs."""
    from app.models.enums import BackgroundJobType
    from app.services.job_worker import enqueue

    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    try:
        job = await JobService(db).require_job(ref)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    queued = await enqueue(
        db,
        BackgroundJobType.PATH_SUGGEST.value,
        {"job_ids": [job.code]},
        user_id=user.id,
    )
    return {"job_id": str(queued.id), "status": queued.status}
