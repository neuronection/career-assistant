from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import AICapability

ALLOWED_CAPS = frozenset(c.value for c in AICapability)


def _validate_caps(values: Optional[list[str]]) -> Optional[list[str]]:
    """Normalize a capability list; unknown keys are rejected."""
    if values is None:
        return None
    cleaned: list[str] = []
    for value in values:
        if value not in ALLOWED_CAPS:
            allowed = ", ".join(sorted(ALLOWED_CAPS))
            raise ValueError(f"Unknown capability '{value}' (allowed: {allowed})")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


class ProviderOut(BaseModel):
    id: UUID
    name: str
    scope: str
    user_id: Optional[UUID] = None
    provider_type: str
    api_base: str
    api_key: Optional[str] = None
    is_active: bool
    is_local: Optional[bool] = None
    country: Optional[str] = None
    is_mine: bool = False
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider_type: str = "openai_compatible"
    api_base: str = Field(default="https://api.openai.com/v1", max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=400)
    scope: str = "user"
    is_local: Optional[bool] = None
    country: Optional[str] = Field(default=None, max_length=80)


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    provider_type: Optional[str] = None
    api_base: Optional[str] = Field(default=None, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=400)
    is_active: Optional[bool] = None
    is_local: Optional[bool] = None
    country: Optional[str] = Field(default=None, max_length=80)


class ModelOut(BaseModel):
    id: UUID
    provider_id: UUID
    name: str
    model_name: str
    is_active: bool
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None
    tier: Optional[str] = None
    caps: Optional[list[str]] = None

    model_config = {"from_attributes": True}


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    model_name: str = Field(min_length=1, max_length=200)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    reasoning_effort: Optional[str] = Field(default=None, max_length=20)
    tier: Optional[str] = Field(default=None, pattern="^(fast|strong)$")
    caps: Optional[list[str]] = None

    _validate_caps = field_validator("caps")(_validate_caps)


class ModelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    is_active: Optional[bool] = None
    reasoning_effort: Optional[str] = Field(default=None, max_length=20)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    caps: Optional[list[str]] = None

    _validate_caps = field_validator("caps")(_validate_caps)


class AssignmentOut(BaseModel):
    id: UUID
    task_type: str
    scope: str
    model_id: Optional[UUID] = None
    tier: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class AssignmentSet(BaseModel):
    scope: str = "user"
    model_id: Optional[UUID] = None
    tier: Optional[str] = Field(default=None, pattern="^(fast|strong)$")


class EffectiveAssignment(BaseModel):
    task_type: str
    source: str
    provider_type: str
    model_name: str
    api_base: str
    tier: Optional[str] = None


class ConfigSummary(BaseModel):
    tasks: list[EffectiveAssignment]
    can_manage_global: bool
    mock_allowed: bool = False


class TestResult(BaseModel):
    ok: bool
    reply: str = ""
    error: str = ""


class BudgetOut(BaseModel):
    id: UUID
    name: str
    task_type: Optional[str] = None
    user_id: Optional[UUID] = None
    window: str
    max_tokens: int
    is_active: bool

    model_config = {"from_attributes": True}


class BudgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    task_type: Optional[str] = Field(default=None, max_length=40)
    user_id: Optional[UUID] = None
    window: str = Field(default="day", pattern="^(day|month)$")
    max_tokens: int = Field(ge=1)


class UsageRollup(BaseModel):
    task_type: str
    calls: int
    tokens_in: int
    tokens_out: int
