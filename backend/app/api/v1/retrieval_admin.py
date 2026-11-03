"""Admin retrieval reads, the plan-50 enqueues and the plan-51 action seam.

Plan 50 ships the status/health reads and the ``VECTOR_INDEX`` /
``VECTOR_RECONCILE`` triggers; plan 51 Q1a composes the full
audit/operations read model (overview, spaces, coverage, runs, run detail,
quality, query health, failures, usage) under the same admin-only
``/admin/retrieval`` namespace. Q1b adds the only write seam: reindex,
cancel/retry, space lifecycle, maintenance and the golden-query compare.
Every action is idempotent, space-locked where it mutates, audited under the
``vector.*`` group, and delegates to the existing services/handlers rather
than duplicating execution. Notifications (Q1c) and the UI (Q2) are not here.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, sync_engine
from app.core.errors import NotFoundError, ValidationError
from app.models.enums import BackgroundJobType
from app.models.user_model import User
from app.services import retrieval_actions as actions
from app.services import retrieval_jobs as retrieval_jobs
from app.services import retrieval_ops_reads as reads
from app.services.audit import emitter
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

IDEMPOTENCY_HEADER = Header(
    default=None,
    alias="Idempotency-Key",
    description=(
        "Client-generated replay key (8-120 chars); a repeat with the same body is a replay"
    ),
)


def _guarded(payload: dict[str, Any]) -> dict[str, Any]:
    """Every read payload passes the family no-raw-text rule before it leaves."""
    return ops.assert_no_raw_text(payload)


def _key(
    header: str | None,
    body: Any,
    *,
    required: bool,
    action: str,
) -> str | None:
    """Resolve the Idempotency-Key (header wins), validating its shape."""
    value = header or getattr(body, "idempotency_key", None)
    if value is None or str(value).strip() == "":
        if required:
            raise ValidationError(
                f"an Idempotency-Key header (or idempotency_key field) is required for {action}"
            )
        return None
    return retrieval_jobs.validate_key(value)


def _action_response(payload: dict[str, Any]) -> JSONResponse:
    """Honor the contract's http_status (202 queued, 200 sync)."""
    return JSONResponse(
        status_code=int(payload.get("http_status") or 200),
        content=payload,
    )


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
    idempotency_key: str | None = Field(
        default=None, description="optional replay key; the Idempotency-Key header also works"
    )


class ReindexRequest(BaseModel):
    """One bounded reindex of a space (the plan-50 reconcile handler)."""

    space: str = Field(..., description="vector space id or name")
    kind: str | None = Field(default=None, description="one source kind; default all")
    view: str | None = Field(default=None, description="run-scope view label")
    since: str | None = Field(default=None, description="ISO timestamp — only rows updated since")
    budget: int = Field(default=DEFAULT_BUDGET, ge=0, le=100_000, description="embed units")
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=5000, description="documents per run")
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=200)
    scan_limit: int = Field(default=DEFAULT_SCAN_LIMIT, ge=1, le=10_000)
    force: bool = Field(default=False)
    auto_continue: bool = Field(default=True)
    idempotency_key: str | None = Field(default=None)


class ActionKeyRequest(BaseModel):
    """Body for path-addressed actions; the header is preferred."""

    idempotency_key: str | None = Field(default=None)


class BuildSpaceRequest(BaseModel):
    """Provision a ``building`` space beside the active one."""

    name: str = Field(..., min_length=1, max_length=40)
    provider: str = Field(..., min_length=1, max_length=60)
    model: str = Field(..., min_length=1, max_length=120)
    dim: int = Field(..., ge=1, le=3072)
    metric: str = Field(default="cosine")
    normalize: bool = True
    query_prefix: str | None = Field(default=None, max_length=80)
    document_prefix: str | None = Field(default=None, max_length=80)
    idempotency_key: str | None = Field(default=None)


class TypedSpaceRequest(BaseModel):
    """Destructive lifecycle action: the typed space name is mandatory."""

    confirm_space_name: str = Field(..., min_length=1, max_length=40)
    idempotency_key: str | None = Field(default=None)


class DropSpaceRequest(TypedSpaceRequest):
    force: bool = Field(
        default=False,
        description="skip the retirement grace period; the typed name is still required",
    )


class MaintenanceRequest(BaseModel):
    """One typed maintenance action (or a scoped retry of failed documents)."""

    space: str = Field(..., description="vector space id or name")
    action: str = Field(
        ...,
        description="index-rebuild | vacuum | orphan-sweep | retry-failed",
    )
    dry_run: bool = Field(default=False)
    limit: int | None = Field(default=None, ge=1, le=5000)
    idempotency_key: str | None = Field(default=None)


class QualityCompareRequest(BaseModel):
    """Score the versioned golden set on the old and new space."""

    space: str = Field(..., description="candidate/new space id or name")
    compare_space: str = Field(..., description="baseline/old space id or name")
    idempotency_key: str | None = Field(default=None)


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
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue a ``VECTOR_RECONCILE`` run (backfill / drift repair).

    Thin enqueue: the handler owns composing, classification, the embed
    budget and the coverage snapshots, so the run is a ``background_jobs``
    row (plan 51's Runs view reads it) and the embed spend lands on the system
    path rather than the requesting admin's budget. The legacy endpoint now
    rides the same replay/lock/audit seam as ``POST /reindex``: an optional
    key makes it replay-deduped, and the run always takes the space lock.
    """
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
    key = _key(idempotency_key, request, required=False, action="reconcile")
    if key is None:
        key = f"auto:{uuid.uuid4().hex}"
    try:
        space = await reads.resolve_space(db, "content")
    except NotFoundError:
        # The handler's default is the content space; if it does not exist
        # yet, there is no space to lock (the first index creates it).
        space = None
    audit = emitter.audit_event(
        actor=user.id,
        action="vector.reindex.started",
        resource_ref=emitter.resource(
            f"space:{space.id}" if space is not None else "space:content",
            trigger="reconcile",
        ),
    )
    job, deduplicated = await retrieval_jobs.enqueue_retrieval_job(
        db,
        job_type=BackgroundJobType.VECTOR_RECONCILE.value,
        payload=payload,
        idempotency_key=key,
        user_id=user.id,
        space_id=space.id if space is not None else None,
        lock=space is not None,
        audit=audit,
    )
    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "payload": payload,
        "idempotency_key": job.idempotency_key,
        "deduplicated": deduplicated,
    }


# ---------------------------------------------------------------------------
# the plan-51 Q1b action surface
# ---------------------------------------------------------------------------


@router.post("/reindex")
async def retrieval_reindex(
    request: ReindexRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Queue the existing ``VECTOR_RECONCILE`` handler for one bounded run."""
    key = _key(idempotency_key, request, required=True, action="reindex")
    payload = await actions.start_reindex(
        db,
        space_ref=request.space,
        kind=request.kind,
        view=request.view,
        since=request.since,
        budget=request.budget,
        limit=request.limit,
        batch_size=request.batch_size,
        scan_limit=request.scan_limit,
        force=request.force,
        auto_continue=request.auto_continue,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/runs/{run_id}/cancel")
async def retrieval_cancel_run(
    run_id: str,
    request: ActionKeyRequest | None = None,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Request cancellation; the running work observes the flag itself."""
    key = _key(idempotency_key, request, required=True, action="cancel")
    payload = await actions.cancel_run(db, run_id=run_id, idempotency_key=str(key), actor=user.id)
    return _action_response(payload)


@router.post("/runs/{run_id}/retry")
async def retrieval_retry_run(
    run_id: str,
    request: ActionKeyRequest | None = None,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Bounded re-enqueue of a terminal run under a fresh idempotency scope."""
    key = _key(idempotency_key, request, required=True, action="retry")
    payload = await actions.retry_run(db, run_id=run_id, idempotency_key=str(key), actor=user.id)
    return _action_response(payload)


@router.post("/spaces")
async def retrieval_build_space(
    request: BuildSpaceRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Provision a ``building`` space through the lifecycle service."""
    key = _key(idempotency_key, request, required=True, action="build")
    payload = await actions.build_space(
        db,
        name=request.name,
        provider=request.provider,
        model=request.model,
        dim=request.dim,
        metric=request.metric,
        normalize=request.normalize,
        query_prefix=request.query_prefix,
        document_prefix=request.document_prefix,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/spaces/{space_id}/activate")
async def retrieval_activate_space(
    space_id: str,
    request: ActionKeyRequest | None = None,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Activate only when coverage **and** the golden-query quality gate pass."""
    key = _key(idempotency_key, request, required=True, action="activate")
    payload = await actions.activate_space(
        db, space_ref=space_id, idempotency_key=str(key), actor=user.id
    )
    return _action_response(payload)


@router.post("/spaces/{space_id}/retire")
async def retrieval_retire_space(
    space_id: str,
    request: TypedSpaceRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Retire a non-active space; the typed name must match exactly."""
    key = _key(idempotency_key, request, required=True, action="retire")
    payload = await actions.retire_space(
        db,
        space_ref=space_id,
        confirm_space_name=request.confirm_space_name,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/spaces/{space_id}/drop")
async def retrieval_drop_space(
    space_id: str,
    request: DropSpaceRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Drop a retired space; the typed name is mandatory (never a boolean)."""
    key = _key(idempotency_key, request, required=True, action="drop")
    payload = await actions.drop_space(
        db,
        space_ref=space_id,
        confirm_space_name=request.confirm_space_name,
        force=request.force,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/maintenance")
async def retrieval_maintenance(
    request: MaintenanceRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Queue one typed maintenance action (index-rebuild/vacuum/orphan/retry)."""
    key = _key(idempotency_key, request, required=True, action="maintenance")
    payload = await actions.run_maintenance(
        db,
        space_ref=request.space,
        action=request.action,
        dry_run=request.dry_run,
        limit=request.limit,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/quality/compare")
async def retrieval_quality_compare(
    request: QualityCompareRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run the versioned golden set on old vs new space; persist the result."""
    key = _key(idempotency_key, request, required=False, action="quality compare")
    payload = await actions.compare_quality(
        db,
        space_ref=request.space,
        compare_space_ref=request.compare_space,
        idempotency_key=key,
        actor=user.id,
    )
    return _action_response(payload)
