"""Application tracker schemas (plan 116).

The list row carries the application plus the posting identity it
belongs to; the detail row adds the reverse-chron event timeline.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ApplicationOutcome, ApplicationStage, ApplicationVia


class ApplicationEventOut(BaseModel):
    """One timeline entry."""

    model_config = {"from_attributes": True}

    id: UUID
    at: datetime
    kind: str
    stage_from: str | None = None
    stage_to: str | None = None
    body: str = ""
    actor: str = "user"
    meta: dict = Field(default_factory=dict)


class ApplicationOut(BaseModel):
    """The application row as the tracker renders it."""

    model_config = {"from_attributes": True}

    id: UUID
    posting_id: UUID
    posting_ref: str = ""
    posting_title: str = ""
    posting_org: str = ""
    stage: str
    applied_at: datetime | None = None
    applied_via: str = ApplicationVia.URL.value
    applied_via_url: str = ""
    deadline_at: datetime | None = None
    next_followup_at: datetime | None = None
    contact: dict = Field(default_factory=dict)
    offer: dict = Field(default_factory=dict)
    outcome: str | None = None
    closed_at: datetime | None = None
    cv_id: UUID | None = None
    cover_letter_id: UUID | None = None
    external_ref: str = ""
    notes: str = ""
    meta: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ApplicationDetailOut(ApplicationOut):
    """The list row plus the newest-first event timeline."""

    timeline: list[ApplicationEventOut] = Field(default_factory=list)


class FunnelOut(BaseModel):
    """Dashboard funnel: saved → applied → interviewing → offers."""

    saved: int = 0
    applied: int = 0
    interviewing: int = 0
    offers: int = 0
    closed: int = 0


class ApplicationListOut(BaseModel):
    """One tracker page of applications plus aggregate counts."""

    items: list[ApplicationOut]
    total: int
    funnel: FunnelOut
    next_followup_at: datetime | None = None


class ApplicationCreateIn(BaseModel):
    """Track an application (idempotent per posting)."""

    posting_id: UUID
    stage: ApplicationStage | None = None
    applied_via: ApplicationVia = ApplicationVia.URL
    applied_via_url: str = Field(default="", max_length=1000)
    deadline_at: datetime | None = None
    cv_id: UUID | None = None
    cover_letter_id: UUID | None = None
    notes: str = ""


class ApplicationTransitionIn(BaseModel):
    """Move an application to another stage."""

    stage: ApplicationStage
    body: str = Field(default="", max_length=2000)


class ApplicationNoteIn(BaseModel):
    """Append one note to the timeline."""

    text: str = Field(min_length=1, max_length=4000)


class ApplicationDocumentIn(BaseModel):
    """Attach the documents actually sent."""

    cv_id: UUID | None = None
    cover_letter_id: UUID | None = None


class ApplicationSnoozeIn(BaseModel):
    """Push the next follow-up out by whole days."""

    days: int = Field(ge=1, le=120)


class ApplicationCloseIn(BaseModel):
    """Close the application with a terminal outcome."""

    outcome: ApplicationOutcome
    note: str = Field(default="", max_length=4000)


class FollowupRuleOut(BaseModel):
    """Per-user follow-up cadence and switches."""

    enabled: bool = True
    cadence_days: list[int] = Field(default_factory=lambda: [7, 14])
    milestone_checkins: bool = True
    channels: dict = Field(default_factory=dict)


class FollowupRuleIn(BaseModel):
    """Partial follow-up rules patch."""

    enabled: bool | None = None
    cadence_days: list[int] | None = None
    milestone_checkins: bool | None = None
    channels: dict | None = None


class FollowupItemOut(BaseModel):
    """Per-application follow-up state."""

    application_id: str
    posting_ref: str | None = None
    role: str = ""
    org: str = ""
    applied_at: str
    stage: str
    sent_steps: list[str] = Field(default_factory=list)
    next_step: str | None = None
    next_due: str | None = None
    due_now: bool = False


class FollowupSurfaceOut(BaseModel):
    """What the settings block and notification deep links read."""

    rules: FollowupRuleOut
    items: list[FollowupItemOut] = Field(default_factory=list)
