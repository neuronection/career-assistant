from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BackgroundJobOut(BaseModel):
    id: UUID
    job_type: str
    status: str
    progress: int
    stage: str | None = None
    error: str | None = None
    result: dict | None = None
    payload: dict | None = None
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class EnqueueResponse(BaseModel):
    job_id: UUID
    status: str = "queued"
