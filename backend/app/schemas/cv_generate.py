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
    language: str = Field(default="en", min_length=2, max_length=10)
    tone: Optional[Literal["professional", "warm", "concise", "confident"]] = None
    length: Literal["concise", "standard", "detailed"] = "standard"
    max_pages: int = Field(default=1, ge=1, le=3)
    template_id: Optional[uuid.UUID] = None
    include_photo: bool = False
    sections: list[CvGenerateSectionKind] = Field(default_factory=list, max_length=8)
    context: CvContextSelection = Field(default_factory=CvContextSelection)
    notes: str = Field(default="", max_length=2000)

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
