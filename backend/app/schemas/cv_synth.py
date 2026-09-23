"""Synthesized CV item schemas (plan 62): the library CRUD + read shapes.

Voice params mirror the plan-47 writing-action vocabulary
(tone/length) plus per-row language. `CvSynthPayload` is the validated
synthesized text; `CvSynthSourceState` carries the per-source content
hash captured at generation for staleness detection.
"""

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.cv import CvContextRef, CvContextSelection
from app.services.rich_text import validate_rich_text

CvSynthAction = Literal["summarize", "detail", "restyle", "posting_fit", "translate"]
CvSynthScope = Literal["item", "summary", "bullets"]
CvSynthStateStatus = Literal["draft", "active", "archived"]


class CvSynthBullet(BaseModel):
    """One canonical CV bullet (plan 106): `{"text": str}` everywhere."""

    text: str

    @field_validator("text")
    @classmethod
    def _rich(cls, value: str) -> str:
        return validate_rich_text(value, 500)


class CvSynthPayload(BaseModel):
    """The validated synthesized text (only text-bearing fields land).

    `omit_bullets` (plan 110) is an EXPLICIT omission deal: a pinned
    row with it clears the item's bullet list — the item prints its
    (variant) description only. It exists because empty
    `achievements` is the default serialization of every text-only
    variant and can never be a user signal; presence semantics stay
    unchanged otherwise."""

    description: Optional[str] = Field(default=None, max_length=4000)
    summary: Optional[str] = Field(default=None, max_length=2000)
    achievements: list[CvSynthBullet] = Field(default_factory=list, max_length=12)
    omit_bullets: bool = Field(default=False)

    @field_validator("description", "summary")
    @classmethod
    def _rich(cls, value: Optional[str], info) -> Optional[str]:
        if value is None:
            return None
        bound = 4000 if info.field_name == "description" else 2000
        return validate_rich_text(value, bound)

    def text(self) -> str:
        """Primary text content of the variant."""
        return self.summary or self.description or ""


class CvSynthVoice(BaseModel):
    """Recorded generation request (drives matching + regenerate)."""

    language: str = Field(default="en", min_length=2, max_length=10)
    tone: Optional[str] = None
    length: Optional[str] = None
    action: Optional[str] = None
    instruction: Optional[str] = Field(default=None, max_length=600)
    translate_of: Optional[uuid.UUID] = None


class CvSynthItemCreate(BaseModel):
    """Manual variant creation (user-written text, no AI)."""

    refs: list[CvContextRef] = Field(min_length=1, max_length=5)
    scope: CvSynthScope = "item"
    payload: CvSynthPayload
    variant_key: str = Field(default="default", min_length=1, max_length=60)
    target_posting_id: Optional[uuid.UUID] = None
    voice: CvSynthVoice = Field(default_factory=CvSynthVoice)


class CvSynthItemUpdate(BaseModel):
    """User actions on a variant (draft→active, text edits)."""

    payload: Optional[CvSynthPayload] = None
    status: Optional[CvSynthStateStatus] = None
    variant_key: Optional[str] = Field(default=None, min_length=1, max_length=60)


class CvSynthItemGenerate(BaseModel):
    """Body of POST /cv/synth/generate. >5 refs ride the CV_SYNTH queue."""

    refs: list[CvContextRef] = Field(min_length=1, max_length=40)
    action: CvSynthAction = "summarize"
    scope: CvSynthScope = "item"
    posting_id: Optional[uuid.UUID] = None
    language: str = Field(default="en", min_length=2, max_length=10)
    target_language: Optional[str] = Field(default=None, min_length=2, max_length=10)
    tone: Optional[str] = None
    length: Optional[str] = None
    instruction: Optional[str] = Field(
        default=None,
        max_length=600,
        description="Free-text steering for the AI (plan 103); never "
        "overrides the grounding contract. Short steering only — recreate "
        "or rework an existing variant via regenerate_of, not by retyping.",
    )
    variant_key: Optional[str] = Field(default=None, min_length=1, max_length=60)
    translate_of: Optional[uuid.UUID] = None
    regenerate_of: Optional[uuid.UUID] = None


class CvSynthDraft(BaseModel):
    """One AI-drafted variant inside a batch output."""

    refs: list[CvContextRef] = Field(min_length=1, max_length=5)
    payload: CvSynthPayload
    evidence_refs: list[CvContextRef] = Field(default_factory=list, max_length=10)
    rationale: str = Field(default="", max_length=600)


class CvSynthBatch(BaseModel):
    """Structured AI output for CV_SYNTH."""

    notes: str = Field(default="", max_length=1000)
    items: list[CvSynthDraft] = Field(default_factory=list, max_length=40)


class CvSynthGenerateOut(BaseModel):
    """Sync drafts, or 202 with the queue job id (bulk runs)."""

    job_id: Optional[uuid.UUID] = None
    items: list["CvSynthItemOut"] = Field(default_factory=list)


class CvSynthItemOut(BaseModel):
    """Read shape with computed state (staleness, orphan, applicability)."""

    id: uuid.UUID
    scope: str
    variant_key: str
    target_posting_id: Optional[uuid.UUID] = None
    source_refs: list[CvContextRef]
    source_state: list[dict] = Field(default_factory=list)
    payload: CvSynthPayload
    voice: CvSynthVoice
    status: str
    source: str
    verified: bool
    stale: bool = False
    orphaned: bool = False
    last_used_at: Optional[str] = None
    created_at: Optional[str] = None


class CvSynthBulkIn(BaseModel):
    """Body of POST /cv/synth/bulk — multi-row archive/restore/delete."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: Literal["archive", "unarchive", "delete"]


class CvSynthBulkOut(BaseModel):
    """{id, kind} outcome rows of one bulk call."""

    affected: list[uuid.UUID] = Field(default_factory=list)
    deleted: list[uuid.UUID] = Field(default_factory=list)


class CvSynthPreviewIn(BaseModel):
    """Body of POST /cv/synth/preview — match candidates without AI.

    `refs` (≤40) when the caller knows the item ids; otherwise the
    caller's context selection is resolved server-side."""

    target_posting_id: Optional[uuid.UUID] = None
    language: str = Field(default="en", min_length=2, max_length=10)
    refs: list[CvContextRef] = Field(default_factory=list, max_length=40)
    context: Optional[CvContextSelection] = None


class CvSynthPreviewItemOut(BaseModel):
    """One matched + applying variant pair (plan 69.3)."""

    source_key: str
    item_id: str
    synth_id: uuid.UUID
    variant_key: str
    stale: bool


class CvSynthPreviewOut(BaseModel):
    items: list[CvSynthPreviewItemOut] = Field(default_factory=list)
    total: int = 0
