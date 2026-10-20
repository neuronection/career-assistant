"""Application pipeline (plan 113): one `applications` row per
(user, posting) plus its append-only event timeline.

`posting_interactions` keeps ONLY engagement state (seen/saved/hidden);
everything about an actual application — stage, dates, documents sent,
notes — lives here. Every stage transition writes exactly one
`stage_change` event (service-enforced in
`app.services.applications_service`).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import (
    ApplicationActor,
    ApplicationStage,
    ApplicationVia,
)

_STAGE_ALLOWED = (
    "stage IN ('applied', 'screening', 'interview', 'offer', 'accepted', 'rejected', 'withdrawn')"
)
_VIA_ALLOWED = "applied_via IN ('url', 'email', 'portal', 'referral', 'event', 'other')"
_OUTCOME_ALLOWED = (
    "outcome IS NULL OR outcome IN ('accepted', 'rejected', 'withdrawn', 'expired', 'ghosted')"
)
_EVENT_KIND_ALLOWED = (
    "kind IN ('stage_change', 'note', 'document_linked', 'followup_sent', "
    "'followup_snoozed', 'interview_scheduled', 'offer_received', "
    "'external_update', 'imported')"
)
_ACTOR_ALLOWED = "actor IN ('user', 'system', 'assistant', 'extension')"


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One real application: pipeline stage, dates, documents and notes."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "posting_id", name="uq_applications_user_posting"),
        CheckConstraint(_STAGE_ALLOWED, name="stage_allowed"),
        CheckConstraint(_VIA_ALLOWED, name="applied_via_allowed"),
        CheckConstraint(_OUTCOME_ALLOWED, name="outcome_allowed"),
        Index("ix_applications_user_stage", "user_id", "stage"),
        Index("ix_applications_user_next_followup", "user_id", "next_followup_at"),
        Index("ix_applications_posting_id", "posting_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ApplicationStage.APPLIED.value
    )
    applied_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    applied_via: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ApplicationVia.URL.value
    )
    applied_via_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    deadline_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    # Scheduler-facing: maintained by the follow-up sweep (116).
    next_followup_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    # {name, email, role, channel} — recruiter/contact person.
    contact: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    # {currency, amount, period, benefits[]} — the money triple on offer.
    offer: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    cv_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_documents.id", ondelete="SET NULL"), nullable=True
    )
    cover_letter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_documents.id", ondelete="SET NULL"), nullable=True
    )
    # Future inbound-webhook / ATS matching key (122): landed now.
    external_ref: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Extension-sourced extras only (T2 provenance); app code never
    # writes free-shape keys here.
    meta: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class ApplicationEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One timeline entry; `at` is the event time, not the row's."""

    __tablename__ = "application_events"
    __table_args__ = (
        CheckConstraint(_EVENT_KIND_ALLOWED, name="kind_allowed"),
        CheckConstraint(_ACTOR_ALLOWED, name="actor_allowed"),
        Index("ix_application_events_application_at", "application_id", "at"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=lambda: datetime.now(UTC)
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    stage_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stage_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor: Mapped[str] = mapped_column(
        String(12), nullable=False, default=ApplicationActor.USER.value
    )
    # Typed per-kind keys (document id, follow-up step, webhook payload…) —
    # documented in docs/dev/data-model.md.
    meta: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
