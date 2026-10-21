"""Application tracker REST surface (plan 116.2).

Every mutation resolves through :class:`ApplicationService` — the same
audited path chat and MCP use — and returns the detail row (with the
fresh timeline) so the drawer never needs a second round-trip.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.application_model import Application
from app.models.enums import ApplicationOutcome, ApplicationStage
from app.models.posting_model import JobPosting
from app.schemas.application import (
    ApplicationCloseIn,
    ApplicationCreateIn,
    ApplicationDetailOut,
    ApplicationDocumentIn,
    ApplicationEventOut,
    ApplicationListOut,
    ApplicationNoteIn,
    ApplicationOut,
    ApplicationSnoozeIn,
    ApplicationTransitionIn,
    FunnelOut,
)
from app.services.applications_service import ApplicationService
from app.services.deps import get_current_user

router = APIRouter(prefix="/me/applications", tags=["applications"])


def _out(application: Application, posting: JobPosting | None) -> ApplicationOut:
    """One application row with the posting identity it belongs to."""
    return ApplicationOut(
        id=application.id,
        posting_id=application.posting_id,
        posting_ref=(posting.ref if posting is not None else "") or "",
        posting_title=posting.title if posting is not None else "",
        posting_org=posting.org if posting is not None else "",
        stage=application.stage,
        applied_at=application.applied_at,
        applied_via=application.applied_via,
        applied_via_url=application.applied_via_url,
        deadline_at=application.deadline_at,
        next_followup_at=application.next_followup_at,
        contact=application.contact or {},
        offer=application.offer or {},
        outcome=application.outcome,
        closed_at=application.closed_at,
        cv_id=application.cv_id,
        cover_letter_id=application.cover_letter_id,
        external_ref=application.external_ref,
        notes=application.notes,
        meta=application.meta or {},
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


def _detail_out(
    application: Application, posting: JobPosting | None, timeline: list
) -> ApplicationDetailOut:
    """The application row plus its reverse-chronological timeline."""
    base = _out(application, posting)
    return ApplicationDetailOut(
        **base.model_dump(),
        timeline=[ApplicationEventOut.model_validate(row) for row in timeline],
    )


async def _detail(db: AsyncSession, user_id: UUID, application_id: UUID) -> ApplicationDetailOut:
    service = ApplicationService(db)
    application = await service.get(user_id, application_id)
    posting = await db.get(JobPosting, application.posting_id)
    timeline = await service.timeline(user_id, application_id)
    return _detail_out(application, posting, timeline)


@router.get("", response_model=ApplicationListOut)
async def list_applications(
    stage: ApplicationStage | None = Query(default=None),
    open_only: bool = Query(default=False),
    q: str | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationListOut:
    """The tracker listing with the dashboard funnel counts."""
    service = ApplicationService(db)
    rows = await service.list_applications(user.id, stage=stage, open_only=open_only, q=q)
    funnel = await service.funnel(user.id)
    next_due = await service.next_due(user.id)
    return ApplicationListOut(
        items=[_out(application, posting) for application, posting in rows],
        total=len(rows),
        funnel=FunnelOut(**funnel),
        next_followup_at=next_due,
    )


@router.post("", response_model=ApplicationDetailOut, status_code=status.HTTP_201_CREATED)
async def create_application(
    data: ApplicationCreateIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationDetailOut:
    """Track one application (idempotent per posting)."""
    service = ApplicationService(db)
    application = await service.create(
        user.id,
        data.posting_id,
        stage=data.stage,
        via=data.applied_via,
        applied_via_url=data.applied_via_url,
        deadline_at=data.deadline_at,
        cv_id=data.cv_id,
        cover_letter_id=data.cover_letter_id,
        notes=data.notes,
    )
    return await _detail(db, user.id, application.id)


@router.get("/{application_id}", response_model=ApplicationDetailOut)
async def get_application(
    application_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationDetailOut:
    """One application with its reverse-chronological timeline."""
    return await _detail(db, user.id, application_id)


@router.post("/{application_id}/transition", response_model=ApplicationDetailOut)
async def transition_application(
    application_id: UUID,
    data: ApplicationTransitionIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationDetailOut:
    """Move the application; each real move writes one `stage_change`."""
    await ApplicationService(db).transition(
        user.id, application_id, to_stage=data.stage, body=data.body
    )
    return await _detail(db, user.id, application_id)


@router.post("/{application_id}/notes", response_model=ApplicationDetailOut)
async def add_application_note(
    application_id: UUID,
    data: ApplicationNoteIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationDetailOut:
    """Append a note event and refresh the rolling note column."""
    await ApplicationService(db).add_note(user.id, application_id, data.text)
    return await _detail(db, user.id, application_id)


@router.post("/{application_id}/documents", response_model=ApplicationDetailOut)
async def link_application_document(
    application_id: UUID,
    data: ApplicationDocumentIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationDetailOut:
    """Attach the CV / cover letter actually sent."""
    await ApplicationService(db).link_document(
        user.id,
        application_id,
        cv_id=data.cv_id,
        cover_letter_id=data.cover_letter_id,
    )
    return await _detail(db, user.id, application_id)


@router.post("/{application_id}/snooze", response_model=ApplicationDetailOut)
async def snooze_application_followup(
    application_id: UUID,
    data: ApplicationSnoozeIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationDetailOut:
    """Push the next follow-up out by whole days."""
    await ApplicationService(db).snooze_followup(user.id, application_id, days=data.days)
    return await _detail(db, user.id, application_id)


@router.post("/{application_id}/close", response_model=ApplicationDetailOut)
async def close_application(
    application_id: UUID,
    data: ApplicationCloseIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationDetailOut:
    """Close with a terminal outcome."""
    await ApplicationService(db).close(
        user.id,
        application_id,
        outcome=ApplicationOutcome(data.outcome),
        note=data.note,
    )
    return await _detail(db, user.id, application_id)
