"""Effective AI configuration as seen by the caller (plan 118/123.4)."""

from pydantic import BaseModel


class AiTaskCoverageOut(BaseModel):
    assigned: int
    total: int
    missing: list[str]


class AiStatusOut(BaseModel):
    """The bootstrap ``ai`` key: derived server-side from the DB config;
    nothing here is an env setting."""

    configured: bool
    provider_type: str | None = None
    default_model: str | None = None
    task_coverage: AiTaskCoverageOut
    mock_active: bool = False
    setup_dismissed: bool = False
