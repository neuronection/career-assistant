"""HITL profile-proposal schemas (plan 77).

Payload models reuse the REST create/patch schemas per entity kind, so
validation rules are identical whether a change arrives from a form or a
chat-proposed card. `ProfileProposalOut` is the wire shape of a card.
"""

from datetime import datetime
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.cv import CvContextRef

ProposalActionLiteral = Literal["create", "update", "delete"]
ProposalStatusLiteral = Literal[
    "pending", "approved", "rejected", "conflict", "expired"
]
ProposalKindLiteral = Literal[
    "experience_item",
    "education_item",
    "certification",
    "profile_achievement",
    "user_skill",
    "profile_section",
    "cv_synth",
]

PROFILE_SECTIONS: tuple[str, ...] = (
    "basics",
    "academics",
    "work_preferences",
    "preferences",
    "constraints",
)


class UserSkillAddIn(BaseModel):
    """Chat add of one skill — upsert, never a full-list replace."""

    skill_key: str = Field(min_length=1, max_length=80)
    level: int = Field(ge=1, le=10)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class UserSkillPatchIn(BaseModel):
    """Chat edit of one claimed skill row."""

    level: Optional[int] = Field(default=None, ge=1, le=10)
    derive_enabled: Optional[bool] = None


class TextEdit(BaseModel):
    """An anchored text edit (plan 99.2) — the coding-agent transplant.

    ``replace`` requires an exact ``find`` anchor that must match the
    current field content exactly once (never "replace first");
    ``append``/``prepend`` are additive and cannot delete.
    """

    field: str = Field(min_length=1, max_length=40)
    op: Literal["replace", "append", "prepend"]
    find: Optional[str] = Field(default=None, max_length=2000)
    text: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _anchor_shape(self) -> "TextEdit":
        if self.op == "replace":
            if not self.find:
                raise ValueError("replace requires a non-empty find anchor")
        elif self.find:
            raise ValueError("find applies to replace only")
        return self


class CollectionEdit(BaseModel):
    """One granular child-collection edit (plan 99.2).

    ``add`` carries ``value`` ({skill_key, role_in_item?, level_claim?} |
    {text, metric?} | {url} — label strings / bare URLs normalize
    server-side like create payloads); ``remove`` carries ``match``
    ({id} primary for skills/achievements, {skill_key}/{text exact}/
    {url} fallback) — full-replacement update semantics are retired.
    """

    collection: Literal["skills", "achievements", "links"]
    op: Literal["add", "remove"]
    value: Optional[Union[str, dict]] = None
    match: Optional[dict] = None

    @model_validator(mode="after")
    def _shape(self) -> "CollectionEdit":
        if self.op == "add" and not self.value:
            raise ValueError("add requires a value")
        if self.op == "remove" and not self.match:
            raise ValueError("remove requires a match")
        return self


class ProfileSectionPatchIn(BaseModel):
    """Chat patch of one profile JSONB section (languages live here)."""

    section: Literal[
        "basics",
        "academics",
        "work_preferences",
        "preferences",
        "constraints",
    ]
    value: dict[str, Any]


class CvSynthOpPayload(BaseModel):
    """Chat-proposed variant drafting (plan 82): refs + action only.

    Batches stay small enough to review as one card; library-owned
    concerns (`translate`, `regenerate` of existing rows) are rejected —
    they belong to the Synth Library surface.
    """

    model_config = {"extra": "forbid"}

    refs: list[CvContextRef] = Field(min_length=1, max_length=10)
    action: Literal["summarize", "detail", "restyle", "posting_fit"] = "summarize"
    posting_id: Optional[UUID] = None
    language: str = Field(default="en", min_length=2, max_length=10)
    tone: Optional[str] = Field(default=None, max_length=60)
    length: Optional[str] = Field(default=None, max_length=20)
    variant_key: Optional[str] = Field(default=None, min_length=1, max_length=60)


class ProfileProposalOut(BaseModel):
    """One HITL card (persisted state, field-level diff included)."""

    model_config = {"from_attributes": True}

    id: UUID
    kind: ProposalKindLiteral
    action: ProposalActionLiteral
    status: ProposalStatusLiteral
    entity_id: Optional[UUID] = None
    entity_label: str
    title: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    diff: list[dict[str, Any]] = Field(default_factory=list)
    destructive: bool = False
    source: str = "chat"
    chat_session_id: Optional[UUID] = None
    chat_message_id: Optional[UUID] = None
    ai_generation_id: Optional[UUID] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolve_error: str = ""


class ProfileProposalResolveOut(BaseModel):
    """Approve/reject result: the card plus what the apply produced."""

    proposal: ProfileProposalOut
    applied: Optional[dict[str, Any]] = None
    already: bool = False
