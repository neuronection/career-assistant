"""Cover-letter schemas: structured brief + draft-then-approve
paragraphs. Every paragraph cites the evidence it rests on; the service
flags paragraphs whose refs are not a subset of the user's evidence
allowlist (or that cite nothing) — unverifiable claims are shown flagged
in the reviewer, never auto-applied."""

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.cv_suggest import CvEvidenceRef, TailorCoverage

LETTER_TONES = {"professional", "warm", "concise", "confident"}
LETTER_LENGTHS = {"short", "medium", "long"}


class LetterParagraph(BaseModel):
    """One AI-drafted paragraph with the refs its claims rest on."""

    text: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[CvEvidenceRef] = Field(default_factory=list, max_length=12)


class CoverLetterDraft(BaseModel):
    """Structured AI output for CV_COVER_LETTER."""

    subject: str = Field(default="", max_length=200)
    salutation: str = Field(default="Dear Hiring Team,", min_length=1, max_length=80)
    paragraphs: list[LetterParagraph] = Field(default_factory=list, max_length=8)
    closing: str = Field(default="Sincerely,", min_length=1, max_length=80)


class VerifiedParagraph(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[CvEvidenceRef] = Field(default_factory=list, max_length=12)
    verified: bool


class CoverLetterSuggestionOut(BaseModel):
    action: str
    notes: str = ""
    draft: CoverLetterDraft
    paragraphs: list[VerifiedParagraph] = Field(default_factory=list)


class CoverLetterCreate(BaseModel):
    """Create a cover-letter document targeted at one posting."""

    posting_id: uuid.UUID
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    base_cv_id: Optional[uuid.UUID] = None
    language: Optional[str] = Field(default=None, min_length=2, max_length=10)


class CoverLetterActionRequest(BaseModel):
    tone: Optional[str] = None
    length: Optional[str] = None


class BriefSkill(BaseModel):
    skill_key: str
    label: str = ""
    required_level: int = 0
    priority: str = ""
    evidence_quote: str = ""
    user_level: Optional[int] = None


class BriefFitDimension(BaseModel):
    dimension: str
    score: float
    detail: str = ""


class BriefFit(BaseModel):
    score: Optional[float] = None
    estimate: bool = False
    dimensions: list[BriefFitDimension] = Field(default_factory=list, max_length=8)


class CoverLetterBriefOut(BaseModel):
    """The deterministic grounding pack: posting digest + fit + coverage +
    the goal line the letter should open from."""

    posting_id: uuid.UUID
    posting_title: str
    org: str = ""
    location: str = ""
    extract_ready: bool = False
    must_have: list[BriefSkill] = Field(default_factory=list, max_length=40)
    nice_to_have: list[BriefSkill] = Field(default_factory=list, max_length=40)
    responsibilities: list[str] = Field(default_factory=list, max_length=10)
    fit: BriefFit = Field(default_factory=BriefFit)
    coverage: TailorCoverage = Field(default_factory=TailorCoverage)
    goal: str = ""
    evidence_items: int = 0
