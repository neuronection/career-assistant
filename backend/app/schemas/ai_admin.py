from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import AICapability

ALLOWED_CAPS = frozenset(c.value for c in AICapability)


def _validate_caps(values: list[str] | None) -> list[str] | None:
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
    user_id: UUID | None = None
    provider_type: str
    api_base: str
    api_key: str | None = None
    is_active: bool
    is_local: bool | None = None
    country: str | None = None
    is_mine: bool = False
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider_type: str = "openai_compatible"
    api_base: str = Field(default="https://api.openai.com/v1", max_length=500)
    api_key: str | None = Field(default=None, max_length=400)
    scope: str = "user"
    is_local: bool | None = None
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider_type: str | None = None
    api_base: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=400)
    is_active: bool | None = None
    is_local: bool | None = None
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class ModelOut(BaseModel):
    id: UUID
    provider_id: UUID
    name: str
    model_name: str
    is_active: bool
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    tier: str | None = None
    caps: list[str] | None = None

    model_config = {"from_attributes": True}


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    model_name: str = Field(min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    reasoning_effort: str | None = Field(default=None, max_length=20)
    tier: str | None = Field(default=None, pattern="^(fast|strong)$")
    caps: list[str] | None = None

    _validate_caps = field_validator("caps")(_validate_caps)


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    reasoning_effort: str | None = Field(default=None, max_length=20)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    caps: list[str] | None = None

    _validate_caps = field_validator("caps")(_validate_caps)


class AssignmentOut(BaseModel):
    id: UUID
    task_type: str
    scope: str
    model_id: UUID | None = None
    tier: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class AssignmentSet(BaseModel):
    scope: str = "user"
    model_id: UUID | None = None
    tier: str | None = Field(default=None, pattern="^(fast|strong)$")


class EffectiveAssignment(BaseModel):
    task_type: str
    source: str
    provider_type: str
    model_name: str
    api_base: str
    tier: str | None = None


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
    task_type: str | None = None
    user_id: UUID | None = None
    window: str
    max_tokens: int
    is_active: bool

    model_config = {"from_attributes": True}


class BudgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    task_type: str | None = Field(default=None, max_length=40)
    user_id: UUID | None = None
    window: str = Field(default="day", pattern="^(day|month)$")
    max_tokens: int = Field(ge=1)


class UsageRollup(BaseModel):
    task_type: str
    calls: int
    tokens_in: int
    tokens_out: int


class WebSettingsOut(BaseModel):
    """Admin view of the AI web-tool configuration (plan 80)."""

    searxng_url: str
    searxng_probe: dict
    github_token_set: bool


class WebSettingsUpdate(BaseModel):
    searxng_url: str | None = Field(default=None, max_length=500)
    github_token: str | None = Field(default=None, max_length=200)
