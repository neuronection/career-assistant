import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError, NotFoundError
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus
from app.schemas.background_job import BackgroundJobOut
from app.services.deps import get_current_user

router = APIRouter(prefix="/background-jobs", tags=["background-jobs"])


async def _get_owned(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID):
    rows = await db.execute(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.user_id == user_id,
        )
    )
    job = rows.scalars().first()
    if job is None:
        raise NotFoundError("Job not found")
    return job


@router.get("", response_model=list[BackgroundJobOut])
async def my_jobs(
    status_filter: BackgroundJobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, le=100),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BackgroundJobOut]:
    """The caller's background jobs, newest first."""
    query = (
        select(BackgroundJob)
        .where(BackgroundJob.user_id == user.id)
        .order_by(BackgroundJob.created_at.desc())
        .limit(limit)
    )
    if status_filter is not None:
        query = query.where(BackgroundJob.status == status_filter.value)
    rows = await db.execute(query)
    return [BackgroundJobOut.model_validate(j) for j in rows.scalars().all()]


@router.get("/{job_id}", response_model=BackgroundJobOut)
async def get_job(
    job_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BackgroundJobOut:
    """Status/progress/result of one of the caller's jobs."""
    job = await _get_owned(db, job_id, user.id)
    return BackgroundJobOut.model_validate(job)


@router.post("/{job_id}/cancel", response_model=BackgroundJobOut)
async def cancel_job(
    job_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BackgroundJobOut:
    """Cancel a queued job immediately; ask a running one to stop."""
    job = await _get_owned(db, job_id, user.id)
    if job.status in (
        BackgroundJobStatus.SUCCEEDED.value,
        BackgroundJobStatus.FAILED.value,
        BackgroundJobStatus.CANCELLED.value,
    ):
        raise DomainError(f"Job already {job.status}")
    if job.status == BackgroundJobStatus.QUEUED.value:
        job.status = BackgroundJobStatus.CANCELLED.value
        job.finished_at = job.updated_at
    else:
        job.cancel_requested = True
    await db.commit()
    await db.refresh(job)
    return BackgroundJobOut.model_validate(job)


@router.get("/{job_id}/download")
async def download_export(
    job_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download a finished data-export archive (owner only, attachment)."""
    job = await _get_owned(db, job_id, user.id)
    if (
        job.job_type != "data_export"
        or job.status != BackgroundJobStatus.SUCCEEDED.value
    ):
        raise DomainError("No downloadable result for this job")
    export_path = Path(str((job.result or {}).get("export_path", "")))
    if not export_path.is_file():
        raise NotFoundError("Export file is gone; run the export again")
    filename = (job.result or {}).get("filename", export_path.name)
    return FileResponse(
        export_path,
        media_type="application/zip",
        filename=str(filename),
        content_disposition_type="attachment",
    )
