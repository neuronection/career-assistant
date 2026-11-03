"""Minimal admin reads and the one index trigger for retrieval (plan 50 §11).

Plan 50 ships the reads and the ``VECTOR_INDEX`` job; the action surface,
Runs view, dashboards, alerts and quality gates are plan 51 and deliberately
absent here. The trigger only enqueues the job — the handler owns composing,
provisioning and embedding, so every mutation is a ``background_jobs`` row
and no request path issues DDL.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, sync_engine
from app.core.errors import ValidationError
from app.models.enums import BackgroundJobType
from app.models.user_model import User
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

router = APIRouter(
    prefix="/admin/retrieval", tags=["retrieval-admin"], dependencies=[Depends(require_admin)]
)

INDEXABLE_KINDS = RECONCILE_KINDS


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
