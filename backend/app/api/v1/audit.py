"""Audit & monitoring surface (plans 151-152): the cross-stream
observability endpoints — overview KPIs, time-bucketed metrics, facet
breakdowns, the identity ``audit_events`` trail, the AI ledger, the
admin-wide jobs/source-run/journal views and CSV export. Admin-only (the
desktop implicit owner is admin by first-user provisioning)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
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

WINDOW_QUERY = Query(default="24h", pattern="^(24h|7d|30d)$")


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
    window: str = WINDOW_QUERY,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dashboard KPIs + recent failures, aggregated server-side. An
    explicit ``from``/``to`` range overrides the preset window."""
    return await audit.overview(db, window, date_from=date_from, date_to=date_to)


@router.get("/timeseries")
async def audit_timeseries(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Time-bucketed call/error/token series (dialect-aware bucketing;
    custom ranges bucket hourly up to 48h, then daily)."""
    return await audit.timeseries(db, window, date_from=date_from, date_to=date_to)


@router.get("/breakdown")
async def audit_breakdown(
    dimension: str = Query(default="task", pattern="^(task|provider|model)$"),
    window: str = WINDOW_QUERY,
    limit: int = Query(default=20, ge=1, le=200),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-key call/error/token splits — chart data AND filter facets."""
    return await audit.breakdown(
        db, dimension, window, limit=limit, date_from=date_from, date_to=date_to
    )


@router.get("/events")
async def audit_events(
    group: str = Query(default="all", pattern="^(all|auth|admin)$"),
    outcome: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    window: str = Query(default="7d", pattern="^(24h|7d|30d)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
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
        date_from=date_from,
        date_to=date_to,
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
    generation_id: uuid.UUID | None = Query(default=None, alias="id"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
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
        generation_id=str(generation_id) if generation_id else None,
        limit=limit,
        offset=offset,
        date_from=date_from,
        date_to=date_to,
    )
    return {"total": total, "items": [AIGenerationOut.model_validate(r) for r in rows]}


@router.get("/production")
async def audit_production(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Content-production throughput (plan 153): postings, skills,
    companies and catalog jobs created/processed in the range."""
    return await audit.production(db, window, date_from=date_from, date_to=date_to)


@router.get("/jobs")
async def audit_jobs(
    status: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    window: str | None = Query(default=None, pattern="^(24h|7d|30d)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The admin-wide background-jobs view (plan 152)."""
    total, items = await audit.jobs(
        db,
        status=status,
        job_type=job_type,
        user_id=str(user_id) if user_id else None,
        window=window,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": items}


@router.get("/jobs/facets")
async def audit_job_facets(
    window: str | None = Query(default=None, pattern="^(24h|7d|30d)$"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """job_type counts for the jobs filter dropdown (plan 152)."""
    return {"rows": await audit.job_facets(db, window=window, date_from=date_from, date_to=date_to)}


@router.get("/source-runs")
async def audit_source_runs(
    status: str | None = Query(default=None),
    trigger: str | None = Query(default=None, pattern="^(manual|scheduled)$"),
    window: str | None = Query(default=None, pattern="^(24h|7d|30d)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The cross-source ingestion run ledger (plan 152)."""
    total, items = await audit.source_runs(
        db,
        status=status,
        trigger=trigger,
        window=window,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": items}


@router.get("/changes")
async def audit_changes(
    entity: str = Query(default="postings", pattern="^(postings|skills)$"),
    actor_kind: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    event: str | None = Query(default=None),
    window: str | None = Query(default=None, pattern="^(24h|7d|30d)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The cross-entity data-change journal (plan 152)."""
    total, items = await audit.changes(
        db,
        entity=entity,
        actor_kind=actor_kind,
        outcome=outcome,
        event=event,
        window=window,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"entity": entity, "total": total, "items": items}


@router.get("/export")
async def audit_export(
    stream: str = Query(default="ai", pattern="^(ai|events|jobs)$"),
    window: str | None = Query(default=None, pattern="^(24h|7d|30d)$"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    task: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    group: str = Query(default="all", pattern="^(all|auth|admin)$"),
    outcome: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The filtered ledger as CSV (plan 152), capped at 10 000 rows —
    carries the same filters as the stream's list endpoint."""
    csv_text, truncated = await audit.export_csv(
        db,
        stream,
        window=window,
        date_from=date_from,
        date_to=date_to,
        task=task,
        provider=provider,
        status=status,
        query=q,
        group=group,
        outcome=outcome,
        actor=actor,
        job_type=job_type,
    )
    headers = {"Content-Disposition": f'attachment; filename="audit-{stream}.csv"'}
    if truncated:
        headers["X-Audit-Truncated"] = "true"
    return Response(content=csv_text, media_type="text/csv", headers=headers)
