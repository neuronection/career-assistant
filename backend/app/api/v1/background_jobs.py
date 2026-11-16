import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
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
):
    """Download a finished data-export archive (owner only, attachment).

    New exports are objects streamed through the store; pre-contract rows
    carry a legacy local `export_path` and are served from the local tree
    (desktop/self-host only).
    """
    from app.services.profile.document_storage import chain_first, document_storage
    from app.storage.object_storage import ObjectNotFound, safe_download_filename

    job = await _get_owned(db, job_id, user.id)
    if job.job_type != "data_export" or job.status != BackgroundJobStatus.SUCCEEDED.value:
        raise DomainError("No downloadable result for this job")
    result = job.result or {}
    filename = safe_download_filename(
        str(result.get("filename") or f"career-assistant-export-{job.id}.zip")
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    key = result.get("export_key")
    if key:
        storage = document_storage()
        stream = storage.astream_key(str(key))
        try:
            first = await anext(stream)
        except ObjectNotFound as exc:
            raise NotFoundError("Export file is gone; run the export again") from exc
        except StopAsyncIteration:
            return Response(content=b"", media_type="application/zip", headers=headers)
        return StreamingResponse(
            chain_first(first, stream),
            media_type="application/zip",
            headers=headers,
        )
    export_path = Path(str(result.get("export_path") or ""))
    if not export_path.is_file():
        raise NotFoundError("Export file is gone; run the export again")
    return FileResponse(
        export_path,
        media_type="application/zip",
        filename=filename,
        content_disposition_type="attachment",
    )
