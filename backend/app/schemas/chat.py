from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(default="New chat", max_length=200)
    context: Optional[dict] = None


class SessionOut(BaseModel):
    id: UUID
    title: str
    context: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    metadata_json: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AssistIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    page: str = Field(default="", max_length=80)
    job_code: Optional[str] = None


class AssistOut(BaseModel):
    answer: str
    referenced_job_codes: list[str] = Field(default_factory=list)
