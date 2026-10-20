"""Application pipeline operations (plan 113).

The one writer of stage transitions: every move records exactly one
`stage_change` event, so the timeline is the history and no reader ever
has to infer "what happened when" from a status column.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.application_model import Application, ApplicationEvent
from app.models.enums import (
    ApplicationActor,
    ApplicationEventKind,
    ApplicationStage,
    ApplicationVia,
)
from app.models.posting_model import JobPosting


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


async def get_application(
    db: AsyncSession, user_id: uuid.UUID, posting_id: uuid.UUID
) -> Application | None:
    """The user's application for one posting, if it exists."""
    rows = await db.execute(
        select(Application).where(
            Application.user_id == user_id,
            Application.posting_id == posting_id,
        )
    )
    return rows.scalars().first()


async def applications_for_postings(
    db: AsyncSession, user_id: uuid.UUID, posting_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Application]:
    """Applications keyed by posting id for a listing page."""
    if not posting_ids:
        return {}
    rows = await db.execute(
        select(Application).where(
            Application.user_id == user_id,
            Application.posting_id.in_(posting_ids),
        )
    )
    return {application.posting_id: application for application in rows.scalars().all()}


def record_event(
    db: AsyncSession,
    application: Application,
    *,
    kind: ApplicationEventKind,
    actor: ApplicationActor = ApplicationActor.SYSTEM,
    body: str = "",
    meta: dict | None = None,
    at: datetime | None = None,
) -> ApplicationEvent:
    """Append one timeline event to an application."""
    event = ApplicationEvent(
        application_id=application.id,
        at=at or _utcnow(),
        kind=_value(kind),
        body=body,
        actor=_value(actor),
        meta=meta or {},
    )
    db.add(event)
    return event


def record_stage_change(
    db: AsyncSession,
    application: Application,
    *,
    stage_from: str | None,
    stage_to: str,
    actor: ApplicationActor = ApplicationActor.USER,
    body: str = "",
    meta: dict | None = None,
) -> ApplicationEvent:
    """Append exactly one `stage_change` event."""
    event = ApplicationEvent(
        application_id=application.id,
        at=_utcnow(),
        kind=ApplicationEventKind.STAGE_CHANGE.value,
        stage_from=stage_from,
        stage_to=stage_to,
        body=body,
        actor=_value(actor),
        meta=meta or {},
    )
    db.add(event)
    return event


async def transition_stage(
    db: AsyncSession,
    application: Application,
    *,
    to_stage: ApplicationStage | str,
    actor: ApplicationActor = ApplicationActor.USER,
    body: str = "",
    meta: dict | None = None,
) -> Application:
    """Move an application to a new stage, recording the transition."""
    target = _value(to_stage)
    previous = application.stage
    if previous == target:
        return application
    application.stage = target
    record_stage_change(
        db,
        application,
        stage_from=previous,
        stage_to=target,
        actor=actor,
        body=body,
        meta=meta,
    )
    await db.flush()
    return application


async def apply_to_posting(
    db: AsyncSession,
    user_id: uuid.UUID,
    posting_id: uuid.UUID,
    *,
    applied_via_url: str = "",
    stage: ApplicationStage | str | None = None,
    via: ApplicationVia | str = ApplicationVia.URL,
) -> Application:
    """Record that the user applied to a posting.

    Idempotent per (user, posting): the first call creates the
    application and its first `stage_change` event; repeat calls refresh
    the applied date/URL and only write another event when the stage
    actually moves. Commits (the API write path owns the transaction).
    """
    posting_exists = (
        await db.execute(select(JobPosting.id).where(JobPosting.id == posting_id))
    ).scalar_one_or_none()
    if posting_exists is None:
        raise ValidationError("Posting not found")

    target = _value(stage) if stage is not None else ApplicationStage.APPLIED.value
    now = _utcnow()
    application = await get_application(db, user_id, posting_id)
    if application is None:
        application = Application(
            user_id=user_id,
            posting_id=posting_id,
            stage=target,
            applied_at=now,
            applied_via=_value(via),
            applied_via_url=applied_via_url,
        )
        db.add(application)
        await db.flush()
        record_stage_change(
            db,
            application,
            stage_from=None,
            stage_to=target,
            actor=ApplicationActor.USER,
        )
    else:
        application.applied_at = now
        application.applied_via = _value(via)
        application.applied_via_url = applied_via_url
        if target != application.stage:
            await transition_stage(db, application, to_stage=target, actor=ApplicationActor.USER)
    await db.commit()
    await db.refresh(application)
    return application
