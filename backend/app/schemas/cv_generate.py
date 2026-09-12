"""One-shot CV generation schemas.

The request is the generate modal: target, voice, format, section
toggles, context selection and free-text emphasis notes. The server
never trusts the client's section list — kinds are crossed with the
resolved context sources at run time.
"""

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.cv import CvContextSelection

CvGenerateSectionKind = Literal[
    "summary",
    "experience",
    "projects",
    "volunteer",
    "education",
    "certifications",
    "skills",
    "languages",
    "achievements",
    "interests",
]

GENERATABLE_KINDS: tuple[CvGenerateSectionKind, ...] = (
    "summary",
    "experience",
    "projects",
    "volunteer",
    "education",
    "certifications",
    "skills",
    "languages",
    "achievements",
    "interests",
)


class CvGenerateRequest(BaseModel):
    """The generate modal's preferences."""

    target_posting_id: Optional[uuid.UUID] = None
    posting_text: str = Field(default="", max_length=5000)
    template_pick: Literal["none", "ai"] = "none"
    language: str = Field(default="en", min_length=2, max_length=10)
    tone: Optional[Literal["professional", "warm", "concise", "confident"]] = None
    length: Literal["concise", "standard", "detailed"] = "standard"
    max_pages: int = Field(default=1, ge=1, le=3)
    template_id: Optional[uuid.UUID] = None
    include_photo: bool = False
    sections: list[CvGenerateSectionKind] = Field(default_factory=list, max_length=10)
    context: CvContextSelection = Field(default_factory=CvContextSelection)
    notes: str = Field(default="", max_length=5000)

    def enabled_kinds(self) -> list[str]:
        """The requested section kinds (empty = every generatable kind)."""
        requested = list(dict.fromkeys(self.sections))
        if not requested:
            return list(GENERATABLE_KINDS)
        known = set(GENERATABLE_KINDS)
        return [kind for kind in requested if kind in known]


class CvGenerateAccepted(BaseModel):
    """202 body: the background job tracking the run."""

    job_id: uuid.UUID
    status: str = "queued"


class CvGenerateResultOut(BaseModel):
    """The finished run's payload (stored on the job's result)."""

    cv_id: uuid.UUID
    title: str
    version: int
    lint: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    fallback_sections: list[str] = Field(default_factory=list)
    plan_fallback: bool = False
    synth_applied: dict[str, str] = Field(default_factory=dict)
    synth_proposed: list[dict] = Field(default_factory=list)
    polish: Optional[dict] = None


class CvGeneratePreviewOut(BaseModel):
    """Live draft preview while the polish loop edits (plan 64 §3).

    `pct` and `stage` come from the job's progress; `iteration` from the
    trace so the card can label ("polishing 2/3"); `trace` is the
    mid-run mirror of the polish trace (the card's timeline). `html` is
    the deterministic render of the currently committed working state."""

    stage: str = ""
    pct: int = Field(default=0, ge=0, le=100)
    iteration: int = 0
    html: str = ""
    trace: Optional[dict] = None


class CvGenerateStatusOut(BaseModel):
    """Poll target for the generate progress card."""

    job_id: uuid.UUID
    status: str
    progress: int
    stage: Optional[str] = None
    error: Optional[str] = None
    result: Optional[CvGenerateResultOut] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


class CvRunCallOut(BaseModel):
    """One audited LLM call of a CV run (plan 65.3)."""

    id: uuid.UUID
    task: str
    stage: Optional[str] = None
    status: str
    provider: str
    model: str
    prompt_version: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: Optional[int] = None


class CvRunAggregateOut(BaseModel):
    """Per-run totals of the LLM-call ledger (task breakdown included)."""

    calls: int
    tokens_in: int
    tokens_out: int
    latency_ms_sum: int
    by_task: dict[str, dict] = Field(default_factory=dict)


class CvRunOut(BaseModel):
    """One run of `cv_generate` / `cv_polish` for a CV (plan 65.3).

    `iterations` carries the polish trace per iteration (ops ledger,
    coverage, verdicts); `llm_calls` is the run's audit ledger from
    `ai_generations` (run-linked); `outcome` is the loop's terminal
    status (completed / cap / failed / cancelled)."""

    job_id: uuid.UUID
    job_type: str
    status: str
    stage: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None
    outcome: Optional[str] = None
    resumed_from: Optional[str] = None
    final_version: Optional[int] = None
    stages: list[dict] = Field(default_factory=list)
    iterations: list[dict] = Field(default_factory=list)
    llm_calls: list[CvRunCallOut] = Field(default_factory=list)
    aggregate: CvRunAggregateOut
