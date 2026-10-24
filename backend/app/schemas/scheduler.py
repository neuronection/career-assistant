"""Admin scheduler surfaces (plan 123.4): typed schedule rows."""

from uuid import UUID

from pydantic import BaseModel, Field


class ScheduleTriggerOut(BaseModel):
    """Typed trigger envelope: when the task runs and with what params."""

    type: str
    params: dict = Field(default_factory=dict)


class ScheduleItemOut(BaseModel):
    """One system schedule row (owner null) for the admin scheduler UI."""

    id: UUID
    kind: str
    task: str | None = None
    trigger: ScheduleTriggerOut
    payload: dict = Field(default_factory=dict)
    enabled: bool
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    consecutive_failures: int = 0
    misfire_policy: str | None = None
    error: str | None = None


class ScheduleToggleOut(BaseModel):
    id: UUID
    enabled: bool


class ScheduleRunNowOut(BaseModel):
    id: UUID
    next_run_at: str | None = None
