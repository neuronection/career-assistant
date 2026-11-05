"""The one HTTP action seam for retrieval operations (plan 51 Q1b).

Every mutating action is admin-only at the router, idempotent through
:mod:`app.services.retrieval_jobs`, CSRF-protected and rate-limited by the
existing app middleware, and audited through the ``vector.*`` vocabulary.
Execution is never duplicated here: reindex and maintenance enqueue the same
``VECTOR_RECONCILE`` / ``VECTOR_MAINTENANCE`` handlers the worker already
owns, the lifecycle actions call :class:`VectorSpaceLifecycleService`, and
the quality compare runs the same retrieval service the live path uses.

Synchronous lifecycle/gate actions are recorded as completed
``VECTOR_CUTOVER`` / ``VECTOR_MAINTENANCE`` runs: the row is the replay
record, the per-space lock while it runs and the reproducible result
afterwards. They are not queued, so no request ever runs a long backfill or
issues DDL outside the lifecycle service's own seam.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services import retrieval_jobs as jobs
from app.services import retrieval_ops_reads as reads
from app.services import retrieval_quality as quality
from app.services.audit import emitter
from app.services.vector_reconcile_service import (
    RECONCILE_KINDS,
    parse_only,
    parse_since,
)
from app.services.vector_space_lifecycle import (
    SpaceCoverageError,
    SpaceLifecycleError,
    VectorSpaceLifecycleService,
)
from app.storage import retrieval_ops as ops
from app.storage.tokenizer_contract import ChunkConfig, TokenizerSpec
from app.storage.vector_contract import METRICS, V1_VIEWS
from app.storage.vector_store import VectorStoreService

VECTOR_RECONCILE = BackgroundJobType.VECTOR_RECONCILE.value
VECTOR_INDEX = BackgroundJobType.VECTOR_INDEX.value
VECTOR_MAINTENANCE = BackgroundJobType.VECTOR_MAINTENANCE.value
VECTOR_CUTOVER = BackgroundJobType.VECTOR_CUTOVER.value

VECTOR_RUN_TYPES = (VECTOR_RECONCILE, VECTOR_INDEX, VECTOR_MAINTENANCE, VECTOR_CUTOVER)
RETRYABLE_JOB_TYPES = (VECTOR_RECONCILE, VECTOR_INDEX, VECTOR_MAINTENANCE)
QUALITY_COMPARE_ACTION = "quality_compare"
RETRY_IDS_LIMIT = ops.FAILED_IDS_LIMIT


class RetrievalActionRefused(ConflictError):
    """A gate/state refusal carrying the structured body the router returns."""

    def __init__(self, message: str, payload: dict[str, Any]) -> None:
        super().__init__(message)
        self.payload = payload


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _auto_key(prefix: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:48]
    return f"{prefix}:{digest}"


def _name_lock_id(name: str) -> str:
    """A stable lock namespace for a not-yet-created building space.

    The contract's lock key is ``vector_space:<space_id>``; a build has no id
    before it creates one, so its name hashes into a stable UUID in a
    reserved namespace. Two concurrent builds of the same name serialize;
    different names proceed independently. Once the building row exists its
    real id takes over.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"career/vector-space-name/{name}"))


def _run_status(job: BackgroundJob, status: str | None = None) -> ops.RunStatus:
    return ops.RunStatus(status or job.status)


def _response(
    action: ops.RetrievalAction,
    job: BackgroundJob,
    *,
    audit_event: str,
    http_status: int,
    message: str,
    deduplicated: bool = False,
    extra: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    payload = ops.RetrievalActionResponse(
        action=action,
        accepted=True,
        audit_event=audit_event,
        http_status=http_status,
        deduplicated=deduplicated,
        run_id=str(job.id),
        status=_run_status(job, status),
        idempotency_key=job.idempotency_key,
        message=message,
    ).to_dict()
    if extra:
        payload.update(extra)
    return ops.assert_no_raw_text(payload)


def _refusal(
    action: ops.RetrievalAction,
    job: BackgroundJob,
    *,
    message: str,
    audit_event: str = "vector.gate.failed",
    extra: dict[str, Any] | None = None,
    status: str = "failed",
) -> RetrievalActionRefused:
    payload = ops.RetrievalActionResponse(
        action=action,
        accepted=False,
        audit_event=audit_event,
        http_status=409,
        deduplicated=False,
        run_id=str(job.id),
        status=_run_status(job, status),
        idempotency_key=job.idempotency_key,
        message=message,
    ).to_dict()
    if extra:
        payload.update(extra)
    return RetrievalActionRefused(message, ops.assert_no_raw_text(payload))


def _stored_response(job: BackgroundJob, *, deduplicated: bool = True) -> dict[str, Any] | None:
    stored = job.result if isinstance(job.result, dict) else {}
    response = stored.get("response")
    if isinstance(response, dict):
        payload = dict(response)
        payload["deduplicated"] = deduplicated
        return ops.assert_no_raw_text(payload)
    return None


def _replay_refusal(job: BackgroundJob) -> None:
    stored = job.result if isinstance(job.result, dict) else {}
    refusal = stored.get("refusal")
    if isinstance(refusal, dict):
        raise RetrievalActionRefused(
            str(stored.get("message") or "the action was refused"), refusal
        )
    if job.status == ops.RunStatus.FAILED.value:
        stored = job.result if isinstance(job.result, dict) else {}
        raise ConflictError(
            str(stored.get("message") or job.error or "the action previously failed")
        )


async def _space(db: AsyncSession, ref: str | uuid.UUID) -> VectorSpaceRow:
    return await reads.resolve_space(db, ref)


async def _active_space_for_name(db: AsyncSession, name: str) -> VectorSpaceRow | None:
    row = await db.scalars(
        select(VectorSpaceRow)
        .where(VectorSpaceRow.name == name, VectorSpaceRow.status == ops.SpaceStatus.ACTIVE.value)
        .order_by(VectorSpaceRow.created_at.desc())
        .limit(1)
    )
    return row.first()


async def _assert_no_name_build(db: AsyncSession, row: VectorSpaceRow) -> None:
    """Refuse an action on a space whose name is being provisioned.

    A build holds the stable name namespace lock (it has no space id until it
    creates one); a concurrent reindex/lifecycle action on the newly created
    row must not slip past the real-id lock. Once the build finishes, the
    building row's real-id lock takes over.
    """
    if row.status != ops.SpaceStatus.BUILDING.value:
        return
    name_lock = ops.run_lock_key(_name_lock_id(row.name))
    active = await db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.lock_key == name_lock,
            BackgroundJob.status.in_(jobs.ACTIVE_STATUSES),
        )
        .limit(1)
    )
    if active.first() is not None:
        raise ConflictError(f"space {row.name!r} is being built; wait for the build to finish")


async def _building_space_for_name(db: AsyncSession, name: str) -> VectorSpaceRow | None:
    row = await db.scalars(
        select(VectorSpaceRow)
        .where(
            VectorSpaceRow.name == name,
            VectorSpaceRow.status == ops.SpaceStatus.BUILDING.value,
        )
        .order_by(VectorSpaceRow.created_at.desc())
        .limit(1)
    )
    return row.first()


def _job_space_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("space_id")
    return str(value) if value else None


async def _space_id_for_job(db: AsyncSession, payload: dict[str, Any]) -> str | None:
    direct = _job_space_id(payload)
    if direct is not None:
        return direct
    name = payload.get("space")
    if not name:
        return None
    row = await _space(db, str(name))
    return str(row.id)


def _job_for_space(job: BackgroundJob, space: VectorSpaceRow) -> bool:
    payload = job.payload or {}
    if payload.get("space_id") is not None:
        return str(payload["space_id"]) == str(space.id)
    if payload.get("space") is not None:
        return str(payload["space"]) == space.name
    return job.lock_key == ops.run_lock_key(str(space.id))


async def _lifecycle(db: AsyncSession) -> VectorSpaceLifecycleService:
    return VectorSpaceLifecycleService(db, store=VectorStoreService(_sync_engine()))


def _sync_engine():
    from app.core.database import sync_engine

    return sync_engine


# ---------------------------------------------------------------------------
# reindex
# ---------------------------------------------------------------------------


async def start_reindex(
    db: AsyncSession,
    *,
    space_ref: str,
    kind: str | None,
    view: str | None,
    since: str | None,
    budget: int,
    limit: int,
    batch_size: int,
    scan_limit: int,
    force: bool,
    auto_continue: bool,
    idempotency_key: str,
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Enqueue the existing ``VECTOR_RECONCILE`` handler for one bounded run."""
    row = await _space(db, space_ref)
    await _assert_no_name_build(db, row)
    if kind is not None and kind not in RECONCILE_KINDS:
        raise ValidationError(f"unknown retrieval kind {kind!r}; expected one of {RECONCILE_KINDS}")
    if view is not None and view not in V1_VIEWS:
        raise ValidationError(f"unknown view {view!r}; expected one of {V1_VIEWS}")
    try:
        parsed_since = parse_since(since)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    payload: dict[str, Any] = {
        "action": "reindex",
        "space": row.name,
        "space_id": str(row.id),
        "limit": int(limit),
        "budget": int(budget),
        "batch_size": int(batch_size),
        "scan_limit": int(scan_limit),
        "force": bool(force),
        "auto_continue": bool(auto_continue),
    }
    if kind is not None:
        payload["kinds"] = [kind]
    if view is not None:
        payload["view"] = view
    if parsed_since is not None:
        payload["since"] = parsed_since.isoformat()
    audit = emitter.audit_event(
        actor=actor,
        action="vector.reindex.started",
        resource_ref=emitter.resource(f"space:{row.id}", kind=kind, view=view),
    )
    job, deduplicated = await jobs.enqueue_retrieval_job(
        db,
        job_type=VECTOR_RECONCILE,
        payload=payload,
        idempotency_key=idempotency_key,
        user_id=actor,
        space_id=row.id,
        lock=True,
        audit=audit,
    )
    return _response(
        ops.RetrievalAction.REINDEX,
        job,
        audit_event="vector.reindex.started",
        http_status=202,
        message=("replay of " + str(job.idempotency_key) if deduplicated else "reindex queued"),
        deduplicated=deduplicated,
        extra={"space_id": str(row.id)},
    )


# ---------------------------------------------------------------------------
# cancel / retry
# ---------------------------------------------------------------------------


async def _vector_run(db: AsyncSession, run_id: str) -> BackgroundJob:
    try:
        identifier = uuid.UUID(str(run_id))
    except (TypeError, ValueError):
        raise NotFoundError(f"no retrieval run {run_id!r}") from None
    job = await db.get(BackgroundJob, identifier)
    if job is None or job.job_type not in VECTOR_RUN_TYPES:
        raise NotFoundError(f"no retrieval run {run_id!r}")
    return job


async def cancel_run(
    db: AsyncSession,
    *,
    run_id: str,
    idempotency_key: str,
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Request cancellation; the worker observes the flag, never a status write."""
    target = await _vector_run(db, run_id)
    payload = {"action": "cancel_run", "run_id": str(target.id)}
    action_job, deduplicated = await jobs.begin_action_run(
        db,
        job_type=VECTOR_MAINTENANCE,
        payload=payload,
        idempotency_key=idempotency_key,
        user_id=actor,
        space_id=None,
        lock=False,
    )
    if deduplicated:
        stored = _stored_response(action_job)
        if stored is not None:
            return stored
        if action_job.status == "running":
            return _response(
                ops.RetrievalAction.CANCEL_RUN,
                action_job,
                audit_event="vector.reindex.cancelled",
                http_status=202,
                message="cancellation is already in progress",
            )
    terminal = target.status in {
        ops.RunStatus.SUCCEEDED.value,
        ops.RunStatus.FAILED.value,
        ops.RunStatus.CANCELLED.value,
    }
    changed = False
    audit = None
    if not terminal and not target.cancel_requested:
        target.cancel_requested = True
        target.updated_at = _utcnow()
        changed = True
        audit = emitter.audit_event(
            actor=actor,
            action="vector.reindex.cancelled",
            resource_ref=emitter.resource(
                f"run:{target.id}", space=_job_space_id(target.payload or {})
            ),
        )
    result = {
        "action": "cancel_run",
        "run_id": str(target.id),
        "status": target.status,
        "cancel_requested": bool(target.cancel_requested),
        "changed": changed,
    }
    response = _response(
        ops.RetrievalAction.CANCEL_RUN,
        action_job,
        audit_event="vector.reindex.cancelled",
        http_status=200,
        message=("cancellation requested" if changed else f"run is already {target.status}"),
        deduplicated=deduplicated,
        status="succeeded",
        extra={
            "target_run_id": str(target.id),
            "target_status": target.status,
            "cancel_requested": bool(target.cancel_requested),
        },
    )
    await jobs.finish_action_run(
        db,
        action_job,
        result={"response": response, **result},
        audit=audit,
    )
    return response


async def retry_run(
    db: AsyncSession,
    *,
    run_id: str,
    idempotency_key: str,
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Bounded re-enqueue of a terminal run with a fresh idempotency scope."""
    target = await _vector_run(db, run_id)
    if target.job_type == VECTOR_CUTOVER:
        raise ConflictError(
            "cutover/gate evaluations are synchronous; re-run the action instead of retrying"
        )
    if target.job_type not in RETRYABLE_JOB_TYPES:
        raise ConflictError(f"run type {target.job_type!r} cannot be retried")
    if target.status not in {
        ops.RunStatus.FAILED.value,
        ops.RunStatus.CANCELLED.value,
    }:
        raise ConflictError(
            f"run {target.id} is {target.status}; only failed or cancelled runs retry"
        )
    payload = {
        key: value
        for key, value in (target.payload or {}).items()
        if key not in {"after", "carry", "completed_kinds", "continuation_key"}
    }
    payload["requeue_of"] = str(target.id)
    space_id = await _space_id_for_job(db, payload)
    if space_id is None and target.job_type != VECTOR_INDEX:
        try:
            content = await _space(db, "content")
        except NotFoundError:
            content = None
        if content is not None:
            space_id = str(content.id)
            payload["space_id"] = space_id
    lock = target.job_type != VECTOR_INDEX and space_id is not None
    if space_id is not None:
        try:
            target_row = await db.get(VectorSpaceRow, uuid.UUID(str(space_id)))
        except (TypeError, ValueError):
            target_row = None
        if target_row is not None:
            await _assert_no_name_build(db, target_row)
    audit = emitter.audit_event(
        actor=actor,
        action="vector.reindex.retried",
        resource_ref=emitter.resource(f"run:{target.id}", space=space_id),
    )
    job, deduplicated = await jobs.enqueue_retrieval_job(
        db,
        job_type=target.job_type,
        payload=payload,
        idempotency_key=idempotency_key,
        user_id=actor,
        space_id=space_id,
        lock=lock,
        max_attempts=target.max_attempts,
        audit=audit,
    )
    return _response(
        ops.RetrievalAction.RETRY_RUN,
        job,
        audit_event="vector.reindex.retried",
        http_status=202,
        message=(
            "replay of " + str(job.idempotency_key)
            if deduplicated
            else f"retry of {target.id} queued"
        ),
        deduplicated=deduplicated,
        extra={"retry_of": str(target.id), "space_id": space_id},
    )


# ---------------------------------------------------------------------------
# lifecycle actions
# ---------------------------------------------------------------------------


async def build_space(
    db: AsyncSession,
    *,
    name: str,
    provider: str,
    model: str,
    dim: int,
    metric: str,
    normalize: bool,
    query_prefix: str | None,
    document_prefix: str | None,
    idempotency_key: str,
    actor: uuid.UUID,
    tokenizer: TokenizerSpec | None = None,
    chunk: ChunkConfig | None = None,
) -> dict[str, Any]:
    """Provision a ``building`` space through the lifecycle service.

    A token-aware build passes **both** a pinned ``tokenizer`` and a
    ``chunk`` config; the lifecycle persists them and computes the v2 key.
    Omitting both keeps the legacy v1 identity. The HTTP request model and
    client are wired in plan 52 T3c.
    """
    if metric not in METRICS:
        raise ValidationError(f"unsupported metric {metric!r}; expected one of {METRICS}")
    payload = {
        "action": "build_space",
        "name": name,
        "provider": provider,
        "model": model,
        "dim": int(dim),
        "metric": metric,
        "normalize": bool(normalize),
        "query_prefix": query_prefix,
        "document_prefix": document_prefix,
    }
    if tokenizer is not None:
        payload["tokenizer"] = tokenizer.to_dict()
    if chunk is not None:
        payload["chunk"] = chunk.to_dict()
    existing_building = await _building_space_for_name(db, name)
    action_job, deduplicated = await jobs.begin_action_run(
        db,
        job_type=VECTOR_CUTOVER,
        payload=payload,
        idempotency_key=idempotency_key,
        user_id=actor,
        space_id=(existing_building.id if existing_building is not None else _name_lock_id(name)),
        lock=True,
    )
    if deduplicated:
        _replay_refusal(action_job)
        stored = _stored_response(action_job)
        if stored is not None:
            return stored
        return _response(
            ops.RetrievalAction.BUILD_SPACE,
            action_job,
            audit_event="vector.space.provisioned",
            http_status=202,
            message="space build is already in progress",
        )
    active = await _active_space_for_name(db, name)
    try:
        built = await (await _lifecycle(db)).build_space(
            name,
            provider=provider,
            model=model,
            dim=int(dim),
            metric=metric,
            normalize=bool(normalize),
            query_prefix=query_prefix,
            document_prefix=document_prefix,
            tokenizer=tokenizer,
            chunk=chunk,
        )
    except ValueError as exc:
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={"message": str(exc)[:500]},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.space.provisioned",
                resource_ref=emitter.resource("space:new", name=name),
                outcome="error",
            ),
        )
        raise ValidationError(str(exc)) from exc
    except SpaceLifecycleError as exc:
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={"message": str(exc)[:500]},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.space.provisioned",
                resource_ref=emitter.resource("space:new", name=name),
                outcome="error",
            ),
        )
        raise ConflictError(str(exc)) from exc
    except Exception as exc:
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={"message": str(exc)[:500]},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.space.provisioned",
                resource_ref=emitter.resource("space:new", name=name),
                outcome="error",
            ),
        )
        raise
    model_changed = bool(active is not None and active.space_key != built.space_key)
    audits = [
        emitter.audit_event(
            actor=actor,
            action="vector.space.provisioned",
            resource_ref=emitter.resource(f"space:{built.space_id}", name=name),
        )
    ]
    if model_changed:
        audits.append(
            emitter.audit_event(
                actor=actor,
                action="vector.model.changed",
                resource_ref=emitter.resource(
                    f"space:{built.space_id}",
                    model=f"{provider}/{model}",
                    dim=int(dim),
                ),
            )
        )
    response = _response(
        ops.RetrievalAction.BUILD_SPACE,
        action_job,
        audit_event="vector.space.provisioned",
        http_status=200,
        message="building space provisioned",
        status="succeeded",
        extra={"space": built.as_dict()},
    )
    result = {
        "response": response,
        "space": built.as_dict(),
        "model_changed": model_changed,
    }
    await jobs.finish_action_run(db, action_job, result=result, audit=audits)
    return response


def _coverage_status(coverage: dict[str, Any]) -> ops.GateStatus:
    try:
        return ops.GateStatus(str(coverage.get("gate") or "unknown"))
    except ValueError:
        return ops.GateStatus.UNKNOWN


async def _latest_persisted_compare(
    db: AsyncSession,
    *,
    candidate: VectorSpaceRow,
    active: VectorSpaceRow | None,
    golden: ops.GoldenQuerySet,
) -> ops.QualityCompareDTO | None:
    rows = list(
        await db.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.job_type == VECTOR_CUTOVER,
                BackgroundJob.status == ops.RunStatus.SUCCEEDED.value,
            )
            .order_by(BackgroundJob.created_at.desc())
            .limit(reads.RUN_PAGE_MAX)
        )
    )
    for job in rows:
        if (job.payload or {}).get("action") != QUALITY_COMPARE_ACTION:
            continue
        compare = quality.parse_persisted_compare(job.result)
        if compare is None:
            continue
        if compare.new_space_id != str(candidate.id):
            continue
        if compare.set_version != golden.set_version or compare.k != golden.k:
            continue
        expected_old = str(active.id) if active is not None else str(candidate.id)
        if compare.old_space_id != expected_old:
            continue
        return compare
    return None


async def _record_compare_run(
    db: AsyncSession,
    *,
    outcome: quality.QualityCompareOutcome,
    candidate: VectorSpaceRow,
    active: VectorSpaceRow | None,
    actor: uuid.UUID,
) -> ops.QualityCompareDTO | None:
    payload = {
        "action": QUALITY_COMPARE_ACTION,
        "space_id": str(candidate.id),
        "compare_space_id": str(active.id) if active is not None else str(candidate.id),
        "trigger": "activation",
    }
    job, deduplicated = await jobs.begin_action_run(
        db,
        job_type=VECTOR_CUTOVER,
        payload=payload,
        idempotency_key=_auto_key("activation-compare", payload),
        user_id=actor,
        space_id=None,
        lock=False,
    )
    if deduplicated and job.result:
        return quality.parse_persisted_compare(job.result)
    stored = quality.persisted_compare_payload(outcome, new_space=candidate)
    gate = ops.GateStatus.PASS.value if outcome.passed else ops.GateStatus.FAIL.value
    response = _response(
        ops.RetrievalAction.QUALITY_COMPARE,
        job,
        audit_event="vector.gate.failed",
        http_status=200,
        message="quality compare complete",
        status="succeeded",
        extra={
            "quality": outcome.compare.to_dict(),
            "space_id": str(candidate.id),
            "audit_emitted": not outcome.passed,
        },
    )
    audit = None
    if not outcome.passed:
        audit = emitter.audit_event(
            actor=actor,
            action="vector.gate.failed",
            resource_ref=emitter.resource(
                f"space:{candidate.id}", baseline=payload["compare_space_id"]
            ),
            outcome="error",
        )
    await jobs.finish_action_run(
        db,
        job,
        result={"response": response, **stored, "gate": gate},
        audit=audit,
    )
    return None


async def activate_space(
    db: AsyncSession,
    *,
    space_ref: str,
    idempotency_key: str,
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Activate a building space only when coverage **and** quality pass."""
    candidate = await _space(db, space_ref)
    await _assert_no_name_build(db, candidate)
    payload = {"action": "activate_space", "space_id": str(candidate.id)}
    active = await _active_space_for_name(db, candidate.name)
    already_active = active is not None and active.id == candidate.id
    action_job, deduplicated = await jobs.begin_action_run(
        db,
        job_type=VECTOR_CUTOVER,
        payload=payload,
        idempotency_key=idempotency_key,
        user_id=actor,
        space_id=candidate.id,
        lock=not already_active,
    )
    if deduplicated:
        _replay_refusal(action_job)
        stored = _stored_response(action_job)
        if stored is not None:
            return stored
        if action_job.status == ops.RunStatus.RUNNING.value:
            raise ConflictError(
                f"activation of {candidate.name!r} is already in progress ({action_job.id})"
            )
    if already_active:
        # Natural idempotency for an already-active space: no gate re-run and
        # no space lock (a running reindex must not make a no-op fail).
        response = _response(
            ops.RetrievalAction.ACTIVATE_SPACE,
            action_job,
            audit_event="vector.space.activated",
            http_status=200,
            message="space is already active",
            status="succeeded",
            extra={"space_id": str(candidate.id), "already_active": True},
        )
        await jobs.finish_action_run(
            db,
            action_job,
            result={
                "response": response,
                "gate": "pass",
                "activation_gate": {
                    "space_id": str(candidate.id),
                    "coverage": ops.GateStatus.UNKNOWN.value,
                    "quality": ops.GateStatus.UNKNOWN.value,
                    "allowed": True,
                    "reasons": ["already_active"],
                },
            },
            audit=emitter.audit_event(
                actor=actor,
                action="vector.space.activated",
                resource_ref=emitter.resource(f"space:{candidate.id}", already_active="true"),
            ),
        )
        return response
    try:
        sets = quality.load_golden_sets()
        golden = quality.select_golden_set(candidate, sets)
        if golden is None:
            raise quality.GoldenSetMissing(
                f"no versioned golden-query set for space {candidate.name!r}; "
                "quality is required for activation"
            )
        compare = await _latest_persisted_compare(
            db, candidate=candidate, active=active, golden=golden
        )
        if compare is None:
            outcome = await quality.compare_spaces(
                db,
                active,
                candidate,
                golden_sets=(golden,),
            )
            compare = (
                await _record_compare_run(
                    db, outcome=outcome, candidate=candidate, active=active, actor=actor
                )
                or outcome.compare
            )
        coverage = await reads.read_coverage(db, candidate)
        coverage_gate = _coverage_status(coverage["coverage"])
        quality_gate = ops.GateStatus.PASS if compare.passed else ops.GateStatus.FAIL
        reasons: list[str] = []
        if coverage_gate is not ops.GateStatus.PASS:
            reasons.append(f"coverage_{coverage_gate.value}")
        if quality_gate is not ops.GateStatus.PASS:
            reasons.append("quality_below_floor")
        gate = ops.ActivationGateDTO(
            space_id=str(candidate.id),
            coverage=coverage_gate,
            quality=quality_gate,
            allowed=not reasons,
            reasons=tuple(reasons),
        )
        if not gate.allowed:
            raise RetrievalActionRefused(
                "activation refused: coverage and quality must both pass",
                _refusal(
                    ops.RetrievalAction.ACTIVATE_SPACE,
                    action_job,
                    message="activation refused: coverage and quality must both pass",
                    extra={
                        "activation_gate": gate.to_dict(),
                        "quality": compare.to_dict(),
                        "coverage": coverage["coverage"],
                    },
                ).payload,
            )
        lifecycle = await _lifecycle(db)
        activated = await lifecycle.activate_space(
            candidate.id,
            coverage_gate=ops.COVERAGE_GATE,
            quality_gate=lambda _report: True,
        )
    except RetrievalActionRefused as exc:
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={
                "refusal": exc.payload,
                "message": str(exc),
                "gate": "fail",
                "activation_gate": exc.payload.get("activation_gate"),
                "quality": exc.payload.get("quality"),
            },
            audit=emitter.audit_event(
                actor=actor,
                action="vector.gate.failed",
                resource_ref=emitter.resource(f"space:{candidate.id}", action="activate"),
                outcome="error",
            ),
        )
        raise
    except quality.GoldenSetMissing as exc:
        gate = ops.ActivationGateDTO(
            space_id=str(candidate.id),
            coverage=ops.GateStatus.UNKNOWN,
            quality=ops.GateStatus.FAIL,
            allowed=False,
            reasons=("quality_no_golden_set",),
        )
        refusal = _refusal(
            ops.RetrievalAction.ACTIVATE_SPACE,
            action_job,
            message=str(exc),
            extra={"activation_gate": gate.to_dict()},
        )
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={
                "refusal": refusal.payload,
                "message": str(exc),
                "gate": "fail",
                "activation_gate": gate.to_dict(),
            },
            audit=emitter.audit_event(
                actor=actor,
                action="vector.gate.failed",
                resource_ref=emitter.resource(f"space:{candidate.id}", reason="no_golden_set"),
                outcome="error",
            ),
        )
        raise refusal from exc
    except SpaceLifecycleError as exc:
        gate = ops.ActivationGateDTO(
            space_id=str(candidate.id),
            coverage=(
                ops.GateStatus.FAIL
                if isinstance(exc, SpaceCoverageError)
                else ops.GateStatus.UNKNOWN
            ),
            quality=ops.GateStatus.UNKNOWN,
            allowed=False,
            reasons=(str(exc)[:300],),
        )
        refusal = _refusal(
            ops.RetrievalAction.ACTIVATE_SPACE,
            action_job,
            message=str(exc),
            extra={"activation_gate": gate.to_dict()},
        )
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={
                "refusal": refusal.payload,
                "message": str(exc),
                "gate": "fail",
                "activation_gate": gate.to_dict(),
            },
            audit=emitter.audit_event(
                actor=actor,
                action="vector.gate.failed",
                resource_ref=emitter.resource(f"space:{candidate.id}", action="activate"),
                outcome="error",
            ),
        )
        raise refusal from exc
    except Exception as exc:
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={"message": str(exc)[:500]},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.gate.failed",
                resource_ref=emitter.resource(f"space:{candidate.id}", action="activate"),
                outcome="error",
            ),
        )
        raise
    response = _response(
        ops.RetrievalAction.ACTIVATE_SPACE,
        action_job,
        audit_event="vector.space.activated",
        http_status=200,
        message="space activated",
        status="succeeded",
        extra={
            "space_id": str(candidate.id),
            "space": activated.as_dict(),
            "activation_gate": gate.to_dict(),
            "quality": compare.to_dict(),
            "coverage": coverage["coverage"],
        },
    )
    await jobs.finish_action_run(
        db,
        action_job,
        result={
            "response": response,
            "space": activated.as_dict(),
            "gate": "pass",
            "activation_gate": gate.to_dict(),
            "quality": compare.to_dict(),
        },
        audit=emitter.audit_event(
            actor=actor,
            action="vector.space.activated",
            resource_ref=emitter.resource(
                f"space:{candidate.id}",
                previous=activated.previous_space_id,
            ),
        ),
    )
    return response


async def retire_space(
    db: AsyncSession,
    *,
    space_ref: str,
    confirm_space_name: str,
    idempotency_key: str,
    actor: uuid.UUID,
) -> dict[str, Any]:
    row = await _space(db, space_ref)
    if confirm_space_name != row.name:
        raise ValidationError(f"typed confirmation must equal the space name {row.name!r}")
    payload = {"action": "retire_space", "space_id": str(row.id)}
    action_job, deduplicated = await jobs.begin_action_run(
        db,
        job_type=VECTOR_MAINTENANCE,
        payload=payload,
        idempotency_key=idempotency_key,
        user_id=actor,
        space_id=row.id,
        lock=True,
    )
    if deduplicated:
        _replay_refusal(action_job)
        stored = _stored_response(action_job)
        if stored is not None:
            return stored
        if action_job.status == ops.RunStatus.RUNNING.value:
            raise ConflictError(f"retirement of {row.name!r} is already in progress")
    try:
        retired = await (await _lifecycle(db)).retire_space(row.id)
    except SpaceLifecycleError as exc:
        refusal = _refusal(
            ops.RetrievalAction.RETIRE_SPACE,
            action_job,
            message=str(exc),
        )
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={"refusal": refusal.payload, "message": str(exc)},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.space.retired",
                resource_ref=emitter.resource(f"space:{row.id}"),
                outcome="error",
            ),
        )
        raise refusal from exc
    except Exception as exc:
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={"message": str(exc)[:500]},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.space.retired",
                resource_ref=emitter.resource(f"space:{row.id}"),
                outcome="error",
            ),
        )
        raise
    response = _response(
        ops.RetrievalAction.RETIRE_SPACE,
        action_job,
        audit_event="vector.space.retired",
        http_status=200,
        message="space retired",
        status="succeeded",
        extra={"space": retired},
    )
    await jobs.finish_action_run(
        db,
        action_job,
        result={"response": response, "space": retired},
        audit=emitter.audit_event(
            actor=actor,
            action="vector.space.retired",
            resource_ref=emitter.resource(f"space:{row.id}"),
        ),
    )
    return response


async def drop_space(
    db: AsyncSession,
    *,
    space_ref: str,
    confirm_space_name: str,
    force: bool,
    idempotency_key: str,
    actor: uuid.UUID,
) -> dict[str, Any]:
    row = await _space(db, space_ref)
    if confirm_space_name != row.name:
        raise ValidationError(f"typed confirmation must equal the space name {row.name!r}")
    payload = {"action": "drop_space", "space_id": str(row.id), "force": bool(force)}
    action_job, deduplicated = await jobs.begin_action_run(
        db,
        job_type=VECTOR_MAINTENANCE,
        payload=payload,
        idempotency_key=idempotency_key,
        user_id=actor,
        space_id=row.id,
        lock=True,
    )
    if deduplicated:
        _replay_refusal(action_job)
        stored = _stored_response(action_job)
        if stored is not None:
            return stored
        if action_job.status == ops.RunStatus.RUNNING.value:
            raise ConflictError(f"drop of {row.name!r} is already in progress")
    try:
        dropped = await (await _lifecycle(db)).drop_space(
            row.id, force=bool(force), confirm=row.name
        )
    except SpaceLifecycleError as exc:
        refusal = _refusal(
            ops.RetrievalAction.DROP_SPACE,
            action_job,
            message=str(exc),
        )
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={"refusal": refusal.payload, "message": str(exc)},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.space.dropped",
                resource_ref=emitter.resource(f"space:{row.id}"),
                outcome="error",
            ),
        )
        raise refusal from exc
    except Exception as exc:
        await jobs.fail_action_run(
            db,
            action_job,
            error=str(exc),
            result={"message": str(exc)[:500]},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.space.dropped",
                resource_ref=emitter.resource(f"space:{row.id}"),
                outcome="error",
            ),
        )
        raise
    response = _response(
        ops.RetrievalAction.DROP_SPACE,
        action_job,
        audit_event="vector.space.dropped",
        http_status=200,
        message="space dropped",
        status="succeeded",
        extra={"space": dropped},
    )
    await jobs.finish_action_run(
        db,
        action_job,
        result={"response": response, "space": dropped},
        audit=emitter.audit_event(
            actor=actor,
            action="vector.space.dropped",
            resource_ref=emitter.resource(f"space:{row.id}"),
        ),
    )
    return response


# ---------------------------------------------------------------------------
# maintenance
# ---------------------------------------------------------------------------


async def _latest_failed_ids(
    db: AsyncSession, space: VectorSpaceRow
) -> tuple[BackgroundJob | None, list[str], bool]:
    rows = list(
        await db.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.job_type.in_((VECTOR_RECONCILE, VECTOR_MAINTENANCE)),
                BackgroundJob.result.is_not(None),
            )
            .order_by(BackgroundJob.created_at.desc())
            .limit(reads.RUN_PAGE_MAX)
        )
    )
    for job in rows:
        if not _job_for_space(job, space):
            continue
        result = job.result if isinstance(job.result, dict) else {}
        ids = [str(item) for item in (result.get("failed_ids") or [])]
        if ids:
            return job, ids[:RETRY_IDS_LIMIT], bool(result.get("failed_ids_truncated"))
    return None, [], False


async def run_maintenance(
    db: AsyncSession,
    *,
    space_ref: str,
    action: str,
    dry_run: bool,
    limit: int | None,
    idempotency_key: str,
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Queue one typed maintenance action (or a scoped retry of failed docs)."""
    try:
        maintenance = ops.MaintenanceAction(action)
    except ValueError as exc:
        raise ValidationError(
            f"unknown maintenance action {action!r}; expected one of "
            f"{[member.value for member in ops.MaintenanceAction]}"
        ) from exc
    row = await _space(db, space_ref)
    await _assert_no_name_build(db, row)
    if maintenance is ops.MaintenanceAction.RETRY_FAILED:
        source_job, failed_ids, truncated = await _latest_failed_ids(db, row)
        if not failed_ids or source_job is None:
            raise ConflictError(
                f"no failed documents recorded for space {row.name!r}; run a reconcile first"
            )
        try:
            only = parse_only(failed_ids)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        kinds = sorted(only or {})
        payload: dict[str, Any] = {
            "action": "retry_failed",
            "space": row.name,
            "space_id": str(row.id),
            "kinds": kinds,
            "source_ids": failed_ids,
            "limit": min(len(failed_ids), RETRY_IDS_LIMIT),
            "budget": max(len(failed_ids), 1) * 8,
            "scan_limit": max(len(failed_ids), 1),
            "force": False,
            "auto_continue": False,
            "retry_of": str(source_job.id),
        }
        if dry_run:
            preview_job, deduplicated = await jobs.begin_action_run(
                db,
                job_type=VECTOR_MAINTENANCE,
                payload=payload,
                idempotency_key=idempotency_key,
                user_id=actor,
                space_id=None,
                lock=False,
            )
            if deduplicated:
                stored = _stored_response(preview_job)
                if stored is not None:
                    return stored
            response = _response(
                ops.RetrievalAction.MAINTENANCE,
                preview_job,
                audit_event="vector.maintenance.started",
                http_status=200,
                message="retry-failed dry run",
                status="succeeded",
                extra={
                    "dry_run": True,
                    "source_run_id": str(source_job.id),
                    "retry_count": len(failed_ids),
                    "failed_ids_truncated": truncated,
                    "space_id": str(row.id),
                },
            )
            await jobs.finish_action_run(
                db,
                preview_job,
                result={
                    "response": response,
                    "dry_run": True,
                    "retry_count": len(failed_ids),
                    "source_run_id": str(source_job.id),
                },
            )
            return response
        audit = emitter.audit_event(
            actor=actor,
            action="vector.maintenance.started",
            resource_ref=emitter.resource(
                f"space:{row.id}", action="retry-failed", count=len(failed_ids)
            ),
        )
        job, deduplicated = await jobs.enqueue_retrieval_job(
            db,
            job_type=VECTOR_RECONCILE,
            payload=payload,
            idempotency_key=idempotency_key,
            user_id=actor,
            space_id=row.id,
            lock=True,
            audit=audit,
        )
        return _response(
            ops.RetrievalAction.MAINTENANCE,
            job,
            audit_event="vector.maintenance.started",
            http_status=202,
            message=(
                "replay of " + str(job.idempotency_key)
                if deduplicated
                else f"retry of {len(failed_ids)} failed document(s) queued"
            ),
            deduplicated=deduplicated,
            extra={
                "space_id": str(row.id),
                "source_run_id": str(source_job.id),
                "retry_count": len(failed_ids),
                "failed_ids_truncated": truncated,
            },
        )
    payload = {
        "action": maintenance.value,
        "space": row.name,
        "space_id": str(row.id),
        "dry_run": bool(dry_run),
        "limit": int(limit) if limit is not None else None,
    }
    audit = emitter.audit_event(
        actor=actor,
        action="vector.maintenance.started",
        resource_ref=emitter.resource(
            f"space:{row.id}", action=maintenance.value, dry_run=str(bool(dry_run)).lower()
        ),
    )
    job, deduplicated = await jobs.enqueue_retrieval_job(
        db,
        job_type=VECTOR_MAINTENANCE,
        payload=payload,
        idempotency_key=idempotency_key,
        user_id=actor,
        space_id=row.id,
        lock=True,
        audit=audit,
    )
    return _response(
        ops.RetrievalAction.MAINTENANCE,
        job,
        audit_event="vector.maintenance.started",
        http_status=202,
        message=(
            "replay of " + str(job.idempotency_key)
            if deduplicated
            else ("dry run queued" if dry_run else "maintenance queued")
        ),
        deduplicated=deduplicated,
        extra={"space_id": str(row.id), "maintenance_action": maintenance.value},
    )


# ---------------------------------------------------------------------------
# quality compare
# ---------------------------------------------------------------------------


async def compare_quality(
    db: AsyncSession,
    *,
    space_ref: str,
    compare_space_ref: str,
    idempotency_key: str | None,
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Run the versioned golden set against old and new space; persist the result."""
    new_space = await _space(db, space_ref)
    old_space = await _space(db, compare_space_ref)
    if new_space.id == old_space.id:
        raise ValidationError("compare spaces must differ")
    payload = {
        "action": QUALITY_COMPARE_ACTION,
        "space_id": str(new_space.id),
        "compare_space_id": str(old_space.id),
    }
    key = idempotency_key or _auto_key("quality-compare", payload)
    job, deduplicated = await jobs.begin_action_run(
        db,
        job_type=VECTOR_CUTOVER,
        payload=payload,
        idempotency_key=key,
        user_id=actor,
        space_id=None,
        lock=False,
    )
    if deduplicated:
        stored = _stored_response(job)
        if stored is not None:
            return stored
        if job.status == ops.RunStatus.RUNNING.value:
            raise ConflictError("this quality compare is already running")
    try:
        outcome = await quality.compare_spaces(db, old_space, new_space)
    except quality.GoldenSetMissing as exc:
        refusal = _refusal(
            ops.RetrievalAction.QUALITY_COMPARE,
            job,
            message=str(exc),
        )
        await jobs.fail_action_run(
            db,
            job,
            error=str(exc),
            result={"refusal": refusal.payload, "message": str(exc)},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.gate.failed",
                resource_ref=emitter.resource(
                    f"space:{new_space.id}", baseline=str(old_space.id), reason="no_golden_set"
                ),
                outcome="error",
            ),
        )
        raise refusal from exc
    except Exception as exc:
        await jobs.fail_action_run(
            db,
            job,
            error=str(exc),
            result={"message": str(exc)[:500]},
            audit=emitter.audit_event(
                actor=actor,
                action="vector.gate.failed",
                resource_ref=emitter.resource(f"space:{new_space.id}", baseline=str(old_space.id)),
                outcome="error",
            ),
        )
        raise
    stored = quality.persisted_compare_payload(outcome, new_space=new_space)
    gate = ops.GateStatus.PASS.value if outcome.passed else ops.GateStatus.FAIL.value
    response = _response(
        ops.RetrievalAction.QUALITY_COMPARE,
        job,
        audit_event="vector.gate.failed",
        http_status=200,
        message="quality compare complete",
        status="succeeded",
        extra={
            "quality": outcome.compare.to_dict(),
            "space_id": str(new_space.id),
            "baseline_space_id": str(old_space.id),
            "gate": gate,
            "audit_emitted": not outcome.passed,
        },
    )
    audit = None
    if not outcome.passed:
        audit = emitter.audit_event(
            actor=actor,
            action="vector.gate.failed",
            resource_ref=emitter.resource(f"space:{new_space.id}", baseline=str(old_space.id)),
            outcome="error",
        )
    await jobs.finish_action_run(
        db,
        job,
        result={"response": response, **stored, "gate": gate},
        audit=audit,
    )
    return response


__all__ = [
    "QUALITY_COMPARE_ACTION",
    "RETRYABLE_JOB_TYPES",
    "VECTOR_RUN_TYPES",
    "RetrievalActionRefused",
    "activate_space",
    "build_space",
    "cancel_run",
    "compare_quality",
    "drop_space",
    "retire_space",
    "retry_run",
    "run_maintenance",
    "start_reindex",
]
