"""CV intake endpoints: parse → review draft → apply.

Lives under `/cv/intake` (not `/documents`) so the university flow's
`POST /documents/{id}/apply` stays unambiguous; registered before the
`/cv` router so `/cv/intake/...` is not captured by `/cv/{cv_id}`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.models.enums import BackgroundJobType, DocumentStatus
from app.services.cv_intake_service import CvIntakeService
from app.services.deps import get_current_user
from app.services.document_service import DocumentService
from app.services.job_worker import enqueue

router = APIRouter(prefix="/cv/intake", tags=["cv"])


class CvApplyRequest(BaseModel):
    """Partial apply: section → true (all) or list of item indices.

    `drafts` marks selections that should land as drafts (not active):
    section → true (all applied items of that section) or a list of
    item indices. Items are active by default — the review ticks are
    the user's approval."""

    selections: dict
    drafts: dict = {}


@router.get("/drafts")
async def list_cv_drafts(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Import history: every CV draft + its source document."""
    return await CvIntakeService(db).list_drafts(user.id)


@router.post("/{document_id}/parse", status_code=status.HTTP_202_ACCEPTED)
async def parse_cv_document(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Extract structured fields from a CV document."""
    document = await DocumentService(db).get_owned(document_id, user.id)
    if document.kind != "cv":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a CV document")
    if document.status not in (
        DocumentStatus.READY.value,
        DocumentStatus.PROCESSING.value,
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Document text extraction not ready"
        )
    job = await enqueue(
        db,
        BackgroundJobType.CV_PARSE.value,
        {"document_id": str(document.id)},
        user_id=user.id,
    )
    return {"job_id": str(job.id)}


@router.get("/{document_id}/drafts")
async def get_cv_drafts(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The review-first extraction draft; applied drafts also carry
    `applied` — where their import created profile entities."""
    try:
        service = CvIntakeService(db)
        draft = await service.get_draft(document_id, user.id)
        applied: list[dict] = []
        if draft.status == "applied":
            applied = await service.applied_counts(document_id, user.id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {
        "id": str(draft.id),
        "status": draft.status,
        "payload": draft.payload,
        "report": draft.report,
        "section_count": CvIntakeService.section_count(draft.payload or {}),
        "applied": applied,
    }


@router.post("/{document_id}/apply")
async def apply_cv_draft(
    document_id: uuid.UUID,
    payload: CvApplyRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply confirmed selections to the profile (review-first)."""
    try:
        service = CvIntakeService(db)
        report = await service.apply(
            document_id, user.id, payload.selections, payload.drafts
        )
        applied = await service.applied_counts(document_id, user.id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"report": report, "applied": applied}


@router.post("/{document_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
async def discard_cv_draft(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Discard the extraction draft; nothing was ever written."""
    try:
        await CvIntakeService(db).discard(document_id, user.id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
