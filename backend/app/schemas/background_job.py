from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class BackgroundJobOut(BaseModel):
    id: UUID
    job_type: str
    status: str
    progress: int
    stage: Optional[str] = None
    error: Optional[str] = None
    result: Optional[dict] = None
    payload: Optional[dict] = None
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EnqueueResponse(BaseModel):
    job_id: UUID
    status: str = "queued"
