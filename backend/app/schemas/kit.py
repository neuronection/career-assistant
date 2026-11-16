"""Application kit schemas (plan 212 S1.3).

One pre-application kit per posting: identity, the S1.1 gap report, the
CV / cover-letter state, deterministic screening prompts and a
sourced checklist — plus the application-scoped variant that adds the
timeline and the linked documents. Nothing here writes: the kit reads,
prepare computes, and the only writes ride the existing application
surface on an explicit user action.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.application import ApplicationEventOut
from app.schemas.cv_suggest import SectionGap, TailorCoverage
from app.schemas.posting import PostingGapOut, PostingLocationOut

KitCheckLevel = Literal["pass", "warn", "fail", "info"]


class KitPostingOut(BaseModel):
    """The posting identity the kit hangs off (bounded on purpose — the
    full detail stays on the posting-detail surface)."""

    id: UUID
    ref: str = ""
    title: str = ""
    org: str = ""
    url: str = ""
    location: PostingLocationOut | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    employment_type: str | None = None
    seniority: str | None = None
    extract_ready: bool = False


class KitDocumentRef(BaseModel):
    """One candidate document; `target_posting_id` set marks it as this
    posting's scoped variant."""

    id: UUID
    title: str = ""
    kind: str = "resume"
    updated_at: datetime | None = None
    target_posting_id: UUID | None = None


class KitCvState(BaseModel):
    """CV side of the kit: candidates (newest first, bounded), the
    posting-scoped variant when one exists, and `needs_cv` when the
    user has no resume at all — the CV Studio CTA state."""

    needs_cv: bool = False
    candidates: list[KitDocumentRef] = Field(default_factory=list, max_length=10)
    variant: KitDocumentRef | None = None


class KitLetterState(BaseModel):
    """Cover-letter side: the posting-scoped letter when one exists plus
    the user's other letters (bounded) for the link action."""

    doc: KitDocumentRef | None = None
    candidates: list[KitDocumentRef] = Field(default_factory=list, max_length=10)


class KitAnswerPrompt(BaseModel):
    """One common screening prompt backed by the saved-answer library.

    Deterministic and bounded; `saved_answer` is the user's own text
    (null before they save one) — never a faked answer."""

    key: str = Field(max_length=80)
    prompt: str = Field(max_length=300)
    saved_answer: str | None = None
    saved_answer_id: UUID | None = None


class KitChecklistItem(BaseModel):
    """One read-only checklist row with its source: a measured fact
    (page count, posting state), a lint finding, or a static hint.

    Labels are backend English strings like the lint's own messages —
    deterministic and quoted verbatim in the docs; the level badge text
    is localized client-side."""

    id: str = Field(max_length=60)
    level: KitCheckLevel = "info"
    label: str = Field(max_length=400)
    source: str = Field(max_length=40)


class KitApplicationState(BaseModel):
    """The application row's identity when one exists — id/stage only,
    so the kit can deep-link without duplicating the tracker."""

    id: UUID
    stage: str = "applied"
    applied_at: datetime | None = None
    cv_id: UUID | None = None
    cover_letter_id: UUID | None = None


class PostingKitOut(BaseModel):
    """The pre-application kit for one posting."""

    posting: KitPostingOut
    gap: PostingGapOut | None = None
    cv: KitCvState = Field(default_factory=KitCvState)
    cover_letter: KitLetterState = Field(default_factory=KitLetterState)
    answers: list[KitAnswerPrompt] = Field(default_factory=list, max_length=8)
    checklist: list[KitChecklistItem] = Field(default_factory=list, max_length=10)
    application: KitApplicationState | None = None


class KitLinkedDocuments(BaseModel):
    """The documents actually linked to the application."""

    cv: KitDocumentRef | None = None
    cover_letter: KitDocumentRef | None = None


class ApplicationKitOut(PostingKitOut):
    """The kit plus the application timeline and the linked documents."""

    timeline: list[ApplicationEventOut] = Field(default_factory=list, max_length=50)
    timeline_truncated: bool = False
    documents: KitLinkedDocuments = Field(default_factory=KitLinkedDocuments)


class KitPrepareOut(BaseModel):
    """Idempotent deterministic prep: the same computation every run,
    no writes — no CV, cover letter or application row is created.

    `needs_cv` asks for the CV Studio CTA; `extract_ready` false means
    the posting has no deep extraction yet, so coverage is honestly
    absent rather than guessed. AI proposals stay in CV Studio's own
    tailor action; this returns the deterministic coverage only."""

    posting_id: UUID
    ref: str = ""
    needs_cv: bool = False
    extract_ready: bool = False
    cv_id: UUID | None = None
    coverage: TailorCoverage | None = None
    section_gaps: list[SectionGap] = Field(default_factory=list, max_length=20)
    cover_letter: KitLetterState = Field(default_factory=KitLetterState)
