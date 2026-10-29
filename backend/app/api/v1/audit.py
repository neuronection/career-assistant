"""Audit & monitoring surface (plan 151): the cross-stream observability
endpoints — overview KPIs, time-bucketed metrics, facet breakdowns, the
identity ``audit_events`` trail and the AI ledger. Admin-only (the desktop
implicit owner is admin by first-user provisioning)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import audit
from app.services.deps import require_admin

router = APIRouter(
    prefix="/admin/audit",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class AIGenerationOut(BaseModel):
    id: uuid.UUID
    task_type: str
    provider: str
    model: str
    prompt: str
    output: dict | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: float | None
    status: str
    error: str
    task_tier: str | None
    prompt_version: str | None
    pack_key: str | None
    pack_version: int | None
    run_id: uuid.UUID | None
    run_stage: str | None
    user_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/overview")
async def audit_overview(
    window: str = Query(default="24h", pattern="^(24h|7d|30d)$"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dashboard KPIs + recent failures, aggregated server-side."""
    return await audit.overview(db, window)


@router.get("/timeseries")
async def audit_timeseries(
    window: str = Query(default="24h", pattern="^(24h|7d|30d)$"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Time-bucketed call/error/token series (dialect-aware bucketing)."""
    return await audit.timeseries(db, window)


@router.get("/breakdown")
async def audit_breakdown(
    dimension: str = Query(default="task", pattern="^(task|provider)$"),
    window: str = Query(default="24h", pattern="^(24h|7d|30d)$"),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-key call/error/token splits — chart data AND filter facets."""
    return await audit.breakdown(db, dimension, window, limit=limit)


@router.get("/events")
async def audit_events(
    group: str = Query(default="all", pattern="^(all|auth|admin)$"),
    outcome: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    window: str = Query(default="7d", pattern="^(24h|7d|30d)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The identity ``audit_events`` trail — first read surface (plan 151)."""
    total, items = await audit.events(
        db,
        window=window,
        group=group,
        outcome=outcome,
        actor=actor,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": items}


@router.get("/ai/generations")
async def audit_generations(
    task: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    generation_status: str | None = Query(default=None, alias="status"),
    user_id: uuid.UUID | None = Query(default=None),
    run_id: uuid.UUID | None = Query(default=None),
    tier: str | None = Query(default=None),
    window: str | None = Query(default=None, pattern="^(24h|7d|30d)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The AI ledger with the full filter matrix (moved from
    /admin/ai/generations, extended — plan 151 D7)."""
    total, rows = await audit.generations(
        db,
        task=task,
        provider=provider,
        model=model,
        status=generation_status,
        user_id=str(user_id) if user_id else None,
        run_id=str(run_id) if run_id else None,
        tier=tier,
        window=window,
        query=q,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": [AIGenerationOut.model_validate(r) for r in rows]}
