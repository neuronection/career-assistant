"""Admin retrieval reads and the plan-50 enqueues.

Plan 50 ships the status/health reads and the ``VECTOR_INDEX`` /
``VECTOR_RECONCILE`` triggers; plan 51 Q1a composes the full
audit/operations read model (overview, spaces, coverage, runs, run detail,
quality, query health, failures, usage) under the same admin-only
``/admin/retrieval`` namespace. The Q1b action API (reindex, cancel/retry,
space lifecycle, maintenance, quality compare), the audit emitter and the
alerts are deliberately absent here: every new endpoint in this module only
reads.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, sync_engine
from app.core.errors import ValidationError
from app.models.enums import BackgroundJobType
from app.models.user_model import User
from app.services import retrieval_ops_reads as reads
from app.services.deps import require_admin
from app.services.vector_reconcile_service import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BUDGET,
    DEFAULT_LIMIT,
    DEFAULT_SCAN_LIMIT,
    RECONCILE_KINDS,
    parse_kinds,
    parse_since,
)
from app.services.vector_status import read_health, read_space_statuses
from app.storage import retrieval_ops as ops

router = APIRouter(
    prefix="/admin/retrieval", tags=["retrieval-admin"], dependencies=[Depends(require_admin)]
)

INDEXABLE_KINDS = RECONCILE_KINDS

WINDOW_QUERY = Query(default=reads.DEFAULT_WINDOW, pattern="^(24h|7d|30d|90d)$")
SPACE_QUERY = Query(default=None, description="vector space id or name")
RUN_STATUS_QUERY = Query(default=None, pattern="^(queued|running|succeeded|failed|cancelled)$")
FAILURE_KIND_QUERY = Query(
    default=None, pattern="^(embed_provider|indexing|cutover_gate|maintenance)$"
)


def _guarded(payload: dict[str, Any]) -> dict[str, Any]:
    """Every read payload passes the family no-raw-text rule before it leaves."""
    return ops.assert_no_raw_text(payload)


async def _space_or_none(db: AsyncSession, space: str | None):
    if space is None:
        return await reads.default_space(db)
    return await reads.resolve_space(db, space)


class IndexRequest(BaseModel):
    """One document to (re)index; ``space`` defaults to the content space."""

    kind: str = Field(..., description="source kind: posting | job | skill | profile")
    source_id: str = Field(..., description="source row id (UUID)")
    space: str | None = Field(default=None, description="space name; defaults to content")
    force: bool = Field(default=False, description="re-embed even unchanged records")


class ReconcileRequest(BaseModel):
    """One backfill/reconcile run (a resumable, budget-capped batch)."""

    kinds: list[str] | None = Field(
        default=None, description="source kinds to reconcile; default all supported"
    )
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=5000, description="documents per run")
    budget: int = Field(default=DEFAULT_BUDGET, ge=0, le=100_000, description="embed units per run")
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=200)
    scan_limit: int = Field(
        default=DEFAULT_SCAN_LIMIT,
        ge=1,
        le=10_000,
        description="source rows per keyset batch",
    )
    since: str | None = Field(default=None, description="ISO timestamp — only rows updated since")
    force: bool = Field(default=False, description="re-embed even unchanged content")
    auto_continue: bool = Field(
        default=True,
        description="enqueue the next bounded batch when this one is partial",
    )


@router.get("/overview")
async def retrieval_overview(
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Instance-wide retrieval KPIs: spaces, coverage, queries, embed usage."""
    return _guarded(await reads.read_overview(db, window=window))


@router.get("/spaces")
async def retrieval_spaces(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """One row per persisted space with counts, coverage and backend label."""
    return _guarded(await reads.read_spaces(db))


@router.get("/coverage")
async def retrieval_coverage(
    space: str = Query(..., description="vector space id or name"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Latest coverage snapshot per kind; a cold space is ``never_reconciled``."""
    row = await reads.resolve_space(db, space)
    return _guarded(await reads.read_coverage(db, row))


@router.get("/runs")
async def retrieval_runs(
    space: str | None = SPACE_QUERY,
    kind: str | None = Query(default=None, description="run scope source kind"),
    status: str | None = RUN_STATUS_QUERY,
    window: str = WINDOW_QUERY,
    limit: int = Query(default=reads.RUN_PAGE_LIMIT, ge=1, le=reads.RUN_PAGE_MAX),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reindex/backfill/cutover/maintenance runs from ``background_jobs``."""
    row = await reads.resolve_space(db, space) if space is not None else None
    return _guarded(
        await reads.read_runs(
            db, space=row, kind=kind, status=status, window=window, limit=limit, offset=offset
        )
    )


@router.get("/runs/{run_id}")
async def retrieval_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """One run's stage/progress/result counters and bounded ``failed_ids``."""
    return _guarded(await reads.read_run(db, run_id))


@router.get("/quality")
async def retrieval_quality(
    space: str | None = SPACE_QUERY,
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The versioned golden-query set; ``not_sampled`` until a compare exists."""
    row = await _space_or_none(db, space)
    if row is None:
        raise ValidationError("no vector space to score; pass ?space=<id|name>")
    return _guarded(await reads.read_quality(db, space=row, window=window))


@router.get("/query-health")
async def retrieval_query_health(
    space: str | None = SPACE_QUERY,
    kind: str | None = Query(default=None, description="source kind"),
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Latency/candidate/zero-result/degraded aggregates from the rollups."""
    row = await _space_or_none(db, space)
    return _guarded(await reads.read_query_health(db, space=row, kind=kind, window=window))


@router.get("/failures")
async def retrieval_failures(
    space: str | None = SPACE_QUERY,
    kind: str | None = FAILURE_KIND_QUERY,
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Failure groups: embed provider, indexing, cutover gate, maintenance."""
    row = await reads.resolve_space(db, space) if space is not None else None
    return _guarded(await reads.read_failures(db, space=row, kind=kind, window=window))


@router.get("/usage")
async def retrieval_usage(
    space: str | None = SPACE_QUERY,
    kind: str | None = Query(default=None, description="source kind"),
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Embed calls/tokens by day, space and kind, plus the token budget."""
    row = await reads.resolve_space(db, space) if space is not None else None
    return _guarded(await reads.read_usage(db, space=row, kind=kind, window=window))


@router.get("/status")
async def retrieval_status(user: User = Depends(require_admin)) -> list[dict[str, Any]]:
    """Per-space documents/records, coverage snapshot and last reindex."""
    with Session(sync_engine) as session:
        return read_space_statuses(session)


@router.get("/health")
async def retrieval_health(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Backend, extension version, capability caps and per-space health."""
    from app.storage.vector_store import VectorStoreService

    with Session(sync_engine) as session:
        return read_health(session, store=VectorStoreService(sync_engine))


@router.post("/index")
async def enqueue_index(
    request: IndexRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue a ``VECTOR_INDEX`` run for one document."""
    from app.services.job_worker import enqueue

    if request.kind not in INDEXABLE_KINDS:
        raise ValidationError(
            f"Unknown retrieval kind: {request.kind!r} (expected one of {INDEXABLE_KINDS})"
        )
    try:
        source_id = str(uuid.UUID(request.source_id))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"source_id must be a UUID, got {request.source_id!r}") from exc
    payload: dict[str, Any] = {
        "kind": request.kind,
        "source_id": source_id,
        "force": bool(request.force),
    }
    if request.space:
        payload["space"] = request.space
    job = await enqueue(
        db,
        BackgroundJobType.VECTOR_INDEX.value,
        payload,
        user_id=user.id,
    )
    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "payload": payload,
    }


@router.post("/reconcile")
async def enqueue_reconcile(
    request: ReconcileRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue a ``VECTOR_RECONCILE`` run (backfill / drift repair).

    Thin enqueue: the handler owns composing, classification, the embed
    budget and the coverage snapshots, so the run is a ``background_jobs``
    row (plan 51's Runs view reads it) and the embed spend lands on the system
    path rather than the requesting admin's budget.
    """
    from app.services.job_worker import enqueue

    try:
        payload: dict[str, Any] = {
            "limit": request.limit,
            "budget": request.budget,
            "batch_size": request.batch_size,
            "scan_limit": request.scan_limit,
            "force": bool(request.force),
            "auto_continue": bool(request.auto_continue),
        }
        kinds = parse_kinds(request.kinds)
        if kinds is not None:
            unknown = [kind for kind in kinds if kind not in INDEXABLE_KINDS]
            if unknown:
                raise ValidationError(
                    f"Unknown retrieval kind(s): {unknown} (expected {sorted(INDEXABLE_KINDS)})"
                )
            payload["kinds"] = list(kinds)
        since = parse_since(request.since)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if since is not None:
        payload["since"] = since.isoformat()
    job = await enqueue(
        db,
        BackgroundJobType.VECTOR_RECONCILE.value,
        payload,
        user_id=user.id,
    )
    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "payload": payload,
    }
