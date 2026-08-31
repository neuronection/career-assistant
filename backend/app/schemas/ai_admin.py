from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProviderOut(BaseModel):
    id: UUID
    name: str
    scope: str
    user_id: Optional[UUID] = None
    provider_type: str
    api_base: str
    api_key: Optional[str] = None
    is_active: bool
    is_mine: bool = False
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider_type: str = "openai_compatible"
    api_base: str = Field(default="https://api.openai.com/v1", max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=400)
    scope: str = "user"


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    provider_type: Optional[str] = None
    api_base: Optional[str] = Field(default=None, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=400)
    is_active: Optional[bool] = None


class ModelOut(BaseModel):
    id: UUID
    provider_id: UUID
    name: str
    model_name: str
    is_active: bool
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    model_config = {"from_attributes": True}


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    model_name: str = Field(min_length=1, max_length=200)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)


class AssignmentOut(BaseModel):
    id: UUID
    task_type: str
    scope: str
    model_id: Optional[UUID] = None
    is_active: bool

    model_config = {"from_attributes": True}


class AssignmentSet(BaseModel):
    scope: str = "user"
    model_id: Optional[UUID] = None


class EffectiveAssignment(BaseModel):
    task_type: str
    source: str
    provider_type: str
    model_name: str
    api_base: str


class ConfigSummary(BaseModel):
    tasks: list[EffectiveAssignment]
    can_manage_global: bool
    mock_allowed: bool = False


class TestResult(BaseModel):
    ok: bool
    reply: str = ""
    error: str = ""
