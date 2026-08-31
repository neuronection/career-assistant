from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class InterestTagOut(BaseModel):
    id: UUID
    key: str
    label: str
    category: str
    description: str
    deprecated: bool = False
    kind: Literal["topic", "industry"] = "topic"

    model_config = {"from_attributes": True}


class SkillOut(BaseModel):
    id: UUID
    key: str
    label: str
    category: str
    description: str
    parent_id: Optional[UUID] = None
    level_anchors: list[dict] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: str
    origin: str

    model_config = {"from_attributes": True}


class TagCreateIn(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)
    kind: Literal["topic", "industry"] = "topic"


class TagUpdateIn(BaseModel):
    # extra="forbid" makes key-change attempts fail loudly (keys are immutable)
    model_config = {"extra": "forbid"}

    label: Optional[str] = Field(default=None, max_length=120)
    category: Optional[str] = Field(default=None, max_length=60)
    description: Optional[str] = Field(default=None, max_length=500)
    deprecated: Optional[bool] = None
    kind: Optional[Literal["topic", "industry"]] = None


class SkillUpdateIn(BaseModel):
    """Admin edits for a skill; keys stay immutable, lifecycle via status."""

    model_config = {"extra": "forbid"}

    label: Optional[str] = Field(default=None, max_length=120)
    category: Optional[str] = Field(default=None, max_length=60)
    description: Optional[str] = Field(default=None, max_length=500)
    status: Optional[str] = None
    parent_id: Optional[UUID] = None
    aliases: Optional[list[str]] = Field(default=None, max_length=20)
    level_anchors: Optional[list[dict]] = None
