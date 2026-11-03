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
from app.services.vector_status import read_health, read_space_statuses

router = APIRouter(
    prefix="/admin/retrieval", tags=["retrieval-admin"], dependencies=[Depends(require_admin)]
)

INDEXABLE_KINDS = ("posting", "skill", "profile")


class IndexRequest(BaseModel):
    """One document to (re)index; ``space`` defaults to the content space."""

    kind: str = Field(..., description="source kind: posting | skill | profile")
    source_id: str = Field(..., description="source row id (UUID)")
    space: str | None = Field(default=None, description="space name; defaults to content")
    force: bool = Field(default=False, description="re-embed even unchanged records")


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
