"""Application pipeline operations (plan 116).

The one writer of `applications` and `application_events`: every stage
move records exactly one `stage_change` event, so the timeline is the
history and no reader ever has to infer "what happened when" from a
status column. Chat, MCP and REST all funnel through
:class:`ApplicationService` — the same audited-op discipline as the CV
services.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.application_model import Application, ApplicationEvent
from app.models.cv_model import CvDocument
from app.models.enums import (
    ApplicationActor,
    ApplicationEventKind,
    ApplicationOutcome,
    ApplicationStage,
    ApplicationVia,
)
from app.models.followup_model import FollowupRule
from app.models.posting_model import JobPosting

MILESTONE_STAGES = frozenset({ApplicationStage.INTERVIEW.value, ApplicationStage.OFFER.value})
CLOSING_STAGES = frozenset(
    {
        ApplicationStage.ACCEPTED.value,
        ApplicationStage.REJECTED.value,
        ApplicationStage.WITHDRAWN.value,
    }
)
_OUTCOME_STAGE = {
    ApplicationOutcome.ACCEPTED.value: ApplicationStage.ACCEPTED.value,
    ApplicationOutcome.REJECTED.value: ApplicationStage.REJECTED.value,
    ApplicationOutcome.WITHDRAWN.value: ApplicationStage.WITHDRAWN.value,
}
DEFAULT_CADENCE_DAYS = (7, 14)
MAX_CADENCE_DAYS = 120
MIN_SNOOZE_DAYS = 1


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


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


def normalize_cadence(cadence_days) -> list[int]:
    """Ordered positive ints, de-duplicated, bounded."""
    seen: list[int] = []
    for raw in cadence_days or []:
        try:
            days = int(raw)
        except (TypeError, ValueError):
            continue
        if days < 1:
            continue
        days = min(days, MAX_CADENCE_DAYS)
        if days not in seen:
            seen.append(days)
    return sorted(seen) or list(DEFAULT_CADENCE_DAYS)


def next_followup_at(
    application: Application,
    *,
    enabled: bool,
    cadence_days,
    milestone_checkins: bool,
    now: datetime | None = None,
) -> datetime | None:
    """The next scheduler-facing follow-up moment for one application.

    Closed applications never nudge. An interview/offer application is
    due immediately while the milestone check-in is switched on; the
    regular cadence counts from `applied_at` and stops once every step
    has passed (the sweep owns sent-state).
    """
    if application.closed_at is not None:
        return None
    if not enabled:
        return None
    now = now or _utcnow()
    if milestone_checkins and application.stage in MILESTONE_STAGES:
        return now
    applied_at = _as_utc(application.applied_at) or now
    for days in normalize_cadence(cadence_days):
        due = applied_at + timedelta(days=days)
        if due > now:
            return due
    return None


class ApplicationService:
    """The only writer of application rows and their event timeline."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def rule(self, user_id: uuid.UUID) -> FollowupRule:
        """The user's follow-up rule row, with defaults merged in-memory."""
        row = (
            (await self.db.execute(select(FollowupRule).where(FollowupRule.user_id == user_id)))
            .scalars()
            .first()
        )
        if row is not None:
            return row
        return FollowupRule(
            user_id=user_id,
            enabled=True,
            cadence_days=list(DEFAULT_CADENCE_DAYS),
            milestone_checkins=True,
            channels={},
        )

    async def get(self, user_id: uuid.UUID, application_id: uuid.UUID) -> Application:
        """One owned application or 404."""
        return await self._owned(user_id, application_id)

    async def _owned(self, user_id: uuid.UUID, application_id: uuid.UUID) -> Application:
        application = (
            (
                await self.db.execute(
                    select(Application).where(
                        Application.id == application_id,
                        Application.user_id == user_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if application is None:
            raise NotFoundError("Application not found")
        return application

    async def timeline(
        self, user_id: uuid.UUID, application_id: uuid.UUID
    ) -> list[ApplicationEvent]:
        """The application's events, newest first."""
        await self._owned(user_id, application_id)
        rows = await self.db.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.at.desc(), ApplicationEvent.created_at.desc())
        )
        return list(rows.scalars().all())

    async def _refresh_schedule(
        self,
        user_id: uuid.UUID,
        application: Application,
        *,
        now: datetime | None = None,
    ) -> None:
        rule = await self.rule(user_id)
        application.next_followup_at = next_followup_at(
            application,
            enabled=rule.enabled,
            cadence_days=rule.cadence_days,
            milestone_checkins=rule.milestone_checkins,
            now=now,
        )

    async def _validate_cv(self, user_id: uuid.UUID, cv_id: uuid.UUID | None) -> None:
        if cv_id is None:
            return
        owned = (
            await self.db.execute(
                select(CvDocument.id).where(CvDocument.id == cv_id, CvDocument.user_id == user_id)
            )
        ).scalar_one_or_none()
        if owned is None:
            raise ValidationError("Document not found")

    async def create(
        self,
        user_id: uuid.UUID,
        posting_id: uuid.UUID,
        *,
        stage: ApplicationStage | str | None = None,
        via: ApplicationVia | str = ApplicationVia.URL,
        applied_via_url: str = "",
        applied_at: datetime | None = None,
        deadline_at: datetime | None = None,
        cv_id: uuid.UUID | None = None,
        cover_letter_id: uuid.UUID | None = None,
        notes: str = "",
        external_ref: str = "",
        actor: ApplicationActor = ApplicationActor.USER,
    ) -> Application:
        """Track one application; idempotent per (user, posting).

        A repeat call refreshes the application's editable fields and
        only writes a `stage_change` event when the stage actually
        moves. Commits.
        """
        posting_exists = (
            await self.db.execute(select(JobPosting.id).where(JobPosting.id == posting_id))
        ).scalar_one_or_none()
        if posting_exists is None:
            raise ValidationError("Posting not found")
        await self._validate_cv(user_id, cv_id)
        await self._validate_cv(user_id, cover_letter_id)

        target = _value(stage) if stage is not None else ApplicationStage.APPLIED.value
        self._validate_stage(target)
        now = _utcnow()
        application = await get_application(self.db, user_id, posting_id)
        if application is None:
            application = Application(
                user_id=user_id,
                posting_id=posting_id,
                stage=target,
                applied_at=applied_at or now,
                applied_via=_value(via),
                applied_via_url=applied_via_url,
                deadline_at=deadline_at,
                cv_id=cv_id,
                cover_letter_id=cover_letter_id,
                external_ref=external_ref,
                notes=notes,
            )
            self.db.add(application)
            await self.db.flush()
            record_stage_change(
                self.db,
                application,
                stage_from=None,
                stage_to=target,
                actor=actor,
            )
        else:
            if application.closed_at is not None:
                raise ConflictError("Application is closed")
            application.applied_at = applied_at or application.applied_at or now
            application.applied_via = _value(via)
            application.applied_via_url = applied_via_url
            if deadline_at is not None:
                application.deadline_at = deadline_at
            if cv_id is not None:
                application.cv_id = cv_id
            if cover_letter_id is not None:
                application.cover_letter_id = cover_letter_id
            if notes:
                application.notes = notes
            if external_ref:
                application.external_ref = external_ref
            if target != application.stage:
                await self._move(application, target, actor=actor)
        await self._refresh_schedule(user_id, application, now=now)
        await self.db.commit()
        await self.db.refresh(application)
        return application

    def _validate_stage(self, stage: str) -> None:
        if stage not in {member.value for member in ApplicationStage}:
            raise ValidationError(f"Unknown stage: {stage}")

    async def _move(
        self,
        application: Application,
        target: str,
        *,
        actor: ApplicationActor,
        body: str = "",
        meta: dict | None = None,
    ) -> None:
        previous = application.stage
        if previous == target:
            return
        application.stage = target
        record_stage_change(
            self.db,
            application,
            stage_from=previous,
            stage_to=target,
            actor=actor,
            body=body,
            meta=meta,
        )
        await self.db.flush()

    async def transition(
        self,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        *,
        to_stage: ApplicationStage | str,
        actor: ApplicationActor = ApplicationActor.USER,
        body: str = "",
        meta: dict | None = None,
    ) -> Application:
        """Move an application; forward, backward and terminal moves are
        all allowed and each real move writes one `stage_change` event."""
        application = await self._owned(user_id, application_id)
        target = _value(to_stage)
        self._validate_stage(target)
        if application.closed_at is not None and target != application.stage:
            raise ConflictError("Application is closed")
        if application.stage == target:
            return application
        previous = application.stage
        await self._move(application, target, actor=actor, body=body, meta=meta)
        if target in CLOSING_STAGES:
            application.closed_at = application.closed_at or _utcnow()
            application.outcome = application.outcome or (
                target if target in {m.value for m in ApplicationOutcome} else None
            )
        elif previous in CLOSING_STAGES:
            application.closed_at = None
            application.outcome = None
        await self._refresh_schedule(user_id, application)
        await self.db.commit()
        await self.db.refresh(application)
        return application

    async def add_note(
        self,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        text: str,
        *,
        actor: ApplicationActor = ApplicationActor.USER,
    ) -> ApplicationEvent:
        """Append one note event and keep the rolling note column current."""
        clean = (text or "").strip()
        if not clean:
            raise ValidationError("Note text is required")
        application = await self._owned(user_id, application_id)
        history = application.notes.strip()
        application.notes = f"{history}\n{clean}".strip() if history else clean
        event = record_event(
            self.db,
            application,
            kind=ApplicationEventKind.NOTE,
            actor=actor,
            body=clean,
        )
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def link_document(
        self,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        *,
        cv_id: uuid.UUID | None = None,
        cover_letter_id: uuid.UUID | None = None,
        actor: ApplicationActor = ApplicationActor.USER,
    ) -> Application:
        """Attach the CV and/or cover letter actually sent."""
        application = await self._owned(user_id, application_id)
        if cv_id is None and cover_letter_id is None:
            raise ValidationError("Choose a document to link")
        await self._validate_cv(user_id, cv_id)
        await self._validate_cv(user_id, cover_letter_id)
        if cv_id is not None:
            application.cv_id = cv_id
        if cover_letter_id is not None:
            application.cover_letter_id = cover_letter_id
        record_event(
            self.db,
            application,
            kind=ApplicationEventKind.DOCUMENT_LINKED,
            actor=actor,
            meta={
                "cv_id": str(application.cv_id) if application.cv_id else None,
                "cover_letter_id": (
                    str(application.cover_letter_id) if application.cover_letter_id else None
                ),
            },
        )
        await self.db.commit()
        await self.db.refresh(application)
        return application

    async def snooze_followup(
        self,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        *,
        days: int,
        actor: ApplicationActor = ApplicationActor.USER,
    ) -> Application:
        """Push the next follow-up out by a whole number of days."""
        if days < MIN_SNOOZE_DAYS or days > MAX_CADENCE_DAYS:
            raise ValidationError("Snooze must be between 1 and 120 days")
        application = await self._owned(user_id, application_id)
        if application.closed_at is not None:
            raise ConflictError("Application is closed")
        until = _utcnow() + timedelta(days=days)
        application.next_followup_at = until
        record_event(
            self.db,
            application,
            kind=ApplicationEventKind.FOLLOWUP_SNOOZED,
            actor=actor,
            body=f"Follow-up snoozed for {days} day(s)",
            meta={"days": days, "until": until.isoformat()},
        )
        await self.db.commit()
        await self.db.refresh(application)
        return application

    async def close(
        self,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        *,
        outcome: ApplicationOutcome | str,
        note: str = "",
        actor: ApplicationActor = ApplicationActor.USER,
    ) -> Application:
        """Close with a terminal outcome; accepted/rejected/withdrawn also
        move the stage (one `stage_change`), expired/ghosted keep it."""
        application = await self._owned(user_id, application_id)
        target_outcome = _value(outcome)
        if target_outcome not in {member.value for member in ApplicationOutcome}:
            raise ValidationError(f"Unknown outcome: {target_outcome}")
        if application.closed_at is not None:
            return application
        application.outcome = target_outcome
        application.closed_at = _utcnow()
        application.next_followup_at = None
        stage = _OUTCOME_STAGE.get(target_outcome)
        if stage is not None:
            await self._move(
                application,
                stage,
                actor=actor,
                body=note,
                meta={"outcome": target_outcome},
            )
        clean = (note or "").strip()
        if clean:
            record_event(
                self.db,
                application,
                kind=ApplicationEventKind.NOTE,
                actor=actor,
                body=clean,
                meta={"outcome": target_outcome},
            )
        await self.db.commit()
        await self.db.refresh(application)
        return application


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
    """Record that the user applied to a posting (idempotent per pair)."""
    return await ApplicationService(db).create(
        user_id,
        posting_id,
        stage=stage,
        via=via,
        applied_via_url=applied_via_url,
    )
