"""Career paths: curated routes + computed graph to a job."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.schemas.paths import CareerPathOut, PathGraphOut
from app.services.deps import get_current_user
from app.services.job_service import JobService
from app.services.paths_service import PathService

router = APIRouter(tags=["paths"])


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
    from app.services.stages_service import stage_for_user

    stage, _source = await stage_for_user(db, user.id)
    return await PathService(db).paths_out(
        job.id, include_drafts=include_drafts, stage=stage
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
