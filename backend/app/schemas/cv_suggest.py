"""CV suggestion schemas: draft-then-approve writing proposals.

Every proposal must cite the evidence it rests on (`evidence_refs` into
the resolved context); the service flags proposals whose refs are not a
subset of the user's evidence allowlist — unverifiable claims are shown
flagged in the reviewer, never auto-applied.
"""

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

SuggestionAction = Literal["summary", "bullet", "compaction", "tailor", "gaps"]


class CvEvidenceRef(BaseModel):
    """A typed ref into the resolved context (source registry items)."""

    source_key: str = Field(min_length=1, max_length=60)
    item_id: str = Field(min_length=1, max_length=64)


class CvProposal(BaseModel):
    """One draft proposal (never auto-applied)."""

    ref: Optional[CvEvidenceRef] = None
    field: Optional[str] = Field(default=None, max_length=60)
    text: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(default="", max_length=600)
    evidence_refs: list[CvEvidenceRef] = Field(default_factory=list, max_length=12)


class CvSuggestion(BaseModel):
    """Structured AI output for CV_SUGGEST."""

    action: str = Field(min_length=1, max_length=40)
    notes: str = Field(default="", max_length=1000)
    proposals: list[CvProposal] = Field(default_factory=list, max_length=10)


class CoverageEntry(BaseModel):
    skill_key: str
    label: str = ""
    priority: str = ""
    user_level: Optional[int] = None


class TailorCoverage(BaseModel):
    """Deterministic must-have coverage vs the user's evidence."""

    covered: list[CoverageEntry] = Field(default_factory=list, max_length=40)
    missing: list[CoverageEntry] = Field(default_factory=list, max_length=40)


class BulletTarget(BaseModel):
    source_key: str = Field(min_length=1, max_length=60)
    item_id: str = Field(min_length=1, max_length=64)
    text: str = Field(default="", max_length=2000)


class CompactionItem(BaseModel):
    source_key: str = Field(min_length=1, max_length=60)
    item_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=2000)


class CvActionRequest(BaseModel):
    """Action payload; only the fields an action needs are read."""

    posting_id: Optional[uuid.UUID] = None
    ref: Optional[BulletTarget] = None
    items: list[CompactionItem] = Field(default_factory=list, max_length=25)
    tone: Optional[Literal["professional", "warm", "concise", "confident"]] = None
    length: Optional[Literal["short", "medium", "long"]] = None
    target_language: Optional[str] = Field(default=None, min_length=2, max_length=10)


class VerifiedProposal(BaseModel):
    proposal: CvProposal
    verified: bool


class SectionGap(BaseModel):
    source_key: str
    label: str
    message: str
    candidate_count: int


class CvSuggestionOut(BaseModel):
    action: str
    notes: str = ""
    proposals: list[VerifiedProposal] = Field(default_factory=list)
    coverage: Optional[TailorCoverage] = None
    gaps: list[SectionGap] = Field(default_factory=list)
    target_language: Optional[str] = None
