"""Career paths: curated routes + computed graph + the user explorer."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.models.enums import CareerStage, PathStatus
from app.schemas.paths import (
    CareerPathOut,
    PathCreateIn,
    PathDetailOut,
    PathFlagIn,
    PathGraphOut,
    PathReorderIn,
    PathStepIn,
    PathStepUpdateIn,
    PathUpdateIn,
)
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


@router.post("/paths", response_model=PathDetailOut, status_code=status.HTTP_201_CREATED)
async def create_path(
    payload: PathCreateIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Create a review-first user path (draft; the creator activates it
    after review). Chat saves and manual creation share this gate."""
    service = PathService(db)
    try:
        job = await JobService(db).get_by_code_or_id(payload.job_ref)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target job not found")
    try:
        path = await service.create_user_path(
            user,
            job_id=job.id,
            title=payload.title,
            description=payload.description,
            steps=[step.model_dump() for step in payload.steps],
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    fresh = await service.require_visible(path.id, user)
    return await service.detail(fresh, user)


@router.patch("/paths/{path_id}", response_model=PathDetailOut)
async def update_path(
    path_id: uuid.UUID,
    payload: PathUpdateIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Rename/re-describe an owned user path."""
    service = PathService(db)
    try:
        path = await service.require_owned(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await service.update_path(path, title=payload.title, description=payload.description)
    fresh = await service.require_owned(path_id, user)
    return await service.detail(fresh, user)


@router.post("/paths/{path_id}/activate", response_model=PathDetailOut)
async def activate_path(
    path_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Owner review action: draft → active (never automatic)."""
    service = PathService(db)
    try:
        path = await service.require_owned(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if path.status != PathStatus.DRAFT.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Path is not a draft")
    await service.activate(path)
    fresh = await service.require_owned(path_id, user)
    return await service.detail(fresh, user)


@router.delete("/paths/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_path(
    path_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an owned user path (curated paths are shared, never deletable)."""
    service = PathService(db)
    try:
        path = await service.require_owned(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await service.delete_path(path)


@router.post(
    "/paths/{path_id}/fork", response_model=PathDetailOut, status_code=status.HTTP_201_CREATED
)
async def fork_path(
    path_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Fork-on-edit: the caller gets their own active copy; the original
    stays curated (no shared mutation)."""
    service = PathService(db)
    try:
        copy = await service.fork(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    fresh = await service.require_visible(copy.id, user)
    return await service.detail(fresh, user)


@router.post(
    "/paths/{path_id}/steps", response_model=PathDetailOut, status_code=status.HTTP_201_CREATED
)
async def add_path_step(
    path_id: uuid.UUID,
    payload: PathStepIn,
    parent_step_id: uuid.UUID | None = Query(default=None),
    position: int | None = Query(default=None, ge=0),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Add a step (append to the chain) or branch one off a parent
    (parent_step_id + edge_label)."""
    service = PathService(db)
    try:
        path = await service.require_owned(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    try:
        await service.add_step(
            path,
            parent_step_id=parent_step_id,
            spec=payload.model_dump(),
            position=position,
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    fresh = await service.require_owned(path_id, user)
    return await service.detail(fresh, user)


@router.patch("/paths/{path_id}/steps/{step_id}", response_model=PathDetailOut)
async def update_path_step(
    path_id: uuid.UUID,
    step_id: uuid.UUID,
    payload: PathStepUpdateIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Edit one step of an owned path (label/kind/optional/edge/refs)."""
    service = PathService(db)
    try:
        path = await service.require_owned(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    spec = {key: value for key, value in payload.model_dump().items() if value is not None}
    if "optional" in payload.model_dump() and payload.optional is not None:
        spec["optional"] = payload.optional
    try:
        await service.update_step(path, step_id, spec)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    fresh = await service.require_owned(path_id, user)
    return await service.detail(fresh, user)


@router.delete("/paths/{path_id}/steps/{step_id}", response_model=PathDetailOut)
async def delete_path_step(
    path_id: uuid.UUID,
    step_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Remove one step; its branch children cascade with it."""
    service = PathService(db)
    try:
        path = await service.require_owned(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    try:
        await service.delete_step(path, step_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    fresh = await service.require_owned(path_id, user)
    return await service.detail(fresh, user)


@router.post("/paths/{path_id}/steps/reorder", response_model=PathDetailOut)
async def reorder_path_steps(
    path_id: uuid.UUID,
    payload: PathReorderIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailOut:
    """Reorder one sibling set (a branch, or the main chain)."""
    service = PathService(db)
    try:
        path = await service.require_owned(path_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    try:
        await service.reorder_steps(
            path, parent_step_id=payload.parent_step_id, ordered=payload.ordered
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    fresh = await service.require_owned(path_id, user)
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
