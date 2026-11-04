"""Composed retrieval-operations read model (plan 51 Q1a).

The read half of the one admin surface: overview, spaces, coverage, runs,
run detail, quality, query health, failures and usage. Every reader composes
the ledgers that already exist — ``ai_generations`` (task ``embed`` plus the
caller-supplied retrieval tags), ``background_jobs`` (stage/progress/result),
``audit_events`` (group ``vector``; tolerated empty until the Q1b emitter),
the vector tables and the two bounded rollup stores.

Rules this module keeps:

* **No raw text.** No statement selects the prompt column, the output
  column or any document/query text; every payload passes
  the contract's :func:`~app.storage.retrieval_ops.assert_no_raw_text`.
* **Truthful cold state.** Coverage reads the latest snapshot per
  ``(space, kind)``; no snapshot is ``never_reconciled``, never a fake 0 or
  100 %. ANN recall stays ``not sampled`` when the columns are null.
* **UTC + dialect-aware.** Windows snap to UTC, buckets use the shared
  ``date_trunc``/``strftime`` helpers and UUID tag joins normalize hyphens.
  No free-text search is exposed, so no user needle reaches a LIKE.
* **Bounded.** Runs, groups, usage series and run-detail ``failed_ids`` all
  carry explicit caps and truncation signals.

The Q1b action API, idempotency runtime, audit emitter and alerts are not
here: this module only reads.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budgets import window_start as budget_window_start
from app.core.errors import NotFoundError, ValidationError
from app.models.ai_model import AIBudget, AIGeneration
from app.models.background_job_model import BackgroundJob
from app.models.identity_model import AuditEvent
from app.models.vector_model import (
    RetrievalCoverageSnapshot,
    RetrievalQueryRollup,
    VectorDocument,
    VectorRecord,
)
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services.analytics.time_buckets import (
    bucket_expr,
    bucket_key,
    range_bounds,
    zero_filled,
)
from app.services.vector_composers import COMPOSER_VERSION
from app.services.vector_index_service import load_source
from app.storage import retrieval_ops as ops
from app.storage.vector_contract import (
    BACKEND_LINEAR,
    BACKEND_PGVECTOR,
    BACKEND_SQLITE_VEC,
)

READ_WINDOWS = ("24h", "7d", "30d", "90d")
DEFAULT_WINDOW = "24h"
RUN_PAGE_LIMIT = 50
RUN_PAGE_MAX = 200
FAILURE_GROUP_LIMIT = 50
FAILURE_DOCUMENT_IDS_LIMIT = 200
USAGE_GROUP_LIMIT = 100
RECENT_CHANGES_LIMIT = 5
ERROR_TEXT_LIMIT = 500
DEFAULT_SPACE_NAME = "content"
DOCUMENT_STATUS_LIMIT = 50
DOCUMENT_STATUS_KINDS = ("posting", "job", "skill", "profile")

#: Career's persisted vector job types mapped into the family run vocabulary.
#: ``vector_reconcile`` is the resumable backfill/reindex and ``vector_index``
#: a single-document reindex — both are ``VECTOR_REINDEX`` runs for the Runs
#: section. The uppercase names are accepted for a future Q1b handler that
#: enqueues them directly.
_JOB_TYPE_MAP = {
    "vector_reconcile": "VECTOR_REINDEX",
    "vector_index": "VECTOR_REINDEX",
    "vector_maintenance": "VECTOR_MAINTENANCE",
    "vector_cutover": "VECTOR_CUTOVER",
    "VECTOR_REINDEX": "VECTOR_REINDEX",
    "VECTOR_CUTOVER": "VECTOR_CUTOVER",
    "VECTOR_MAINTENANCE": "VECTOR_MAINTENANCE",
}
_VECTOR_DB_JOB_TYPES = tuple(_JOB_TYPE_MAP)
#: The actual index-writing runs; a maintenance/cutover action is not a
#: reindex when the Spaces card reports ``last_reindex_at``.
_REINDEX_JOB_TYPES = ("vector_reconcile", "vector_index")

_BACKEND_LABEL = {
    BACKEND_PGVECTOR: "PostgreSQL pgvector/HNSW",
    BACKEND_SQLITE_VEC: "SQLite sqlite-vec",
    BACKEND_LINEAR: "Linear fallback — desktop scale",
}


@dataclass(frozen=True)
class _Run:
    """One resolved vector run: the row plus the space/scope the DTO needs."""

    job: BackgroundJob
    job_type: str
    space: VectorSpaceRow
    scope: ops.RunScope
    budget_tokens: int | None


def _iso(value: datetime | None) -> str | None:
    """UTC ISO-8601 (``Z``) for a possibly naive SQLite datetime."""
    if value is None:
        return None
    moment = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return moment.isoformat().replace("+00:00", "Z")


def _window(window: str, now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """Validated preset window as ``(start, end, key)`` in UTC."""
    if window not in READ_WINDOWS:
        raise ValidationError(
            f"Unknown retrieval window {window!r}; expected one of {READ_WINDOWS}"
        )
    moment = now or datetime.now(UTC)
    start, _previous, _end = range_bounds(window, None, None, now=moment)
    return start, moment, window


def _window_payload(start: datetime, end: datetime, window: str) -> dict[str, Any]:
    return {"preset": window, "start": _iso(start), "end": _iso(end)}


def _backend_for(row: VectorSpaceRow | None, dialect: str) -> str:
    if row is None:
        return BACKEND_LINEAR
    if row.index_table is None:
        return BACKEND_LINEAR
    return BACKEND_PGVECTOR if dialect == "postgresql" else BACKEND_SQLITE_VEC


def _dialect(db: AsyncSession) -> str:
    return str(db.get_bind().dialect.name)


async def _all_spaces(db: AsyncSession) -> list[VectorSpaceRow]:
    return list(
        await db.scalars(
            select(VectorSpaceRow).order_by(VectorSpaceRow.name, VectorSpaceRow.created_at)
        )
    )


async def resolve_space(db: AsyncSession, ref: str | uuid.UUID | None) -> VectorSpaceRow:
    """Resolve a space id or name; a missing reference is a 404."""
    if ref is None or str(ref).strip() == "":
        raise ValidationError("space is required")
    value = str(ref).strip()
    try:
        space_id = uuid.UUID(value)
    except (TypeError, ValueError):
        row = await db.scalars(
            select(VectorSpaceRow)
            .where(VectorSpaceRow.name == value)
            .order_by(VectorSpaceRow.created_at.desc())
        )
        found = row.first()
        if found is None:
            raise NotFoundError(f"no vector space named {value!r}") from None
        return found
    found = await db.get(VectorSpaceRow, space_id)
    if found is None:
        raise NotFoundError(f"no vector space with id {value!r}")
    return found


async def default_space(db: AsyncSession) -> VectorSpaceRow | None:
    """The active ``content`` space, else the single active space, else None."""
    rows = await _all_spaces(db)
    active = [row for row in rows if row.status == ops.SpaceStatus.ACTIVE.value]
    preferred = next((row for row in active if row.name == DEFAULT_SPACE_NAME), None)
    if preferred is not None:
        return preferred
    if len(active) == 1:
        return active[0]
    return None


async def _latest_snapshots(
    db: AsyncSession, space_id: uuid.UUID, kinds: Sequence[str] | None = None
) -> dict[str, RetrievalCoverageSnapshot]:
    """The latest coverage snapshot per kind (oldest→newest wins)."""
    latest: dict[str, RetrievalCoverageSnapshot] = {}
    rows = await db.scalars(
        select(RetrievalCoverageSnapshot)
        .where(RetrievalCoverageSnapshot.space_id == space_id)
        .order_by(RetrievalCoverageSnapshot.as_of)
    )
    for row in rows:
        if kinds is None or row.kind in kinds:
            latest[row.kind] = row
    return latest


def _coverage_dto(space: VectorSpaceRow, snapshots: Mapping[str, RetrievalCoverageSnapshot]):
    """Aggregate the latest per-kind snapshots into the contract's one row."""
    if not snapshots:
        return ops.CoverageDTO(
            space_id=str(space.id),
            as_of=None,
            total=0,
            missing=0,
            stale=0,
            failed=0,
            embedded=0,
            coverage=None,
            gate=ops.GateStatus.UNKNOWN,
        )
    total = sum(int(row.total) for row in snapshots.values())
    embedded = sum(int(row.embedded) for row in snapshots.values())
    sampled = [row for row in snapshots.values() if row.ann_recall is not None]
    coverage = embedded / total if total > 0 else None
    gate = (
        ops.GateStatus.UNKNOWN
        if coverage is None
        else (ops.GateStatus.PASS if coverage >= ops.COVERAGE_GATE else ops.GateStatus.FAIL)
    )
    return ops.CoverageDTO(
        space_id=str(space.id),
        as_of=_iso(max(row.as_of for row in snapshots.values())),
        total=total,
        missing=sum(int(row.missing) for row in snapshots.values()),
        stale=sum(int(row.stale) for row in snapshots.values()),
        failed=sum(int(row.failed) for row in snapshots.values()),
        embedded=embedded,
        coverage=coverage,
        gate=gate,
        ann_recall=(
            round(sum(float(row.ann_recall or 0.0) for row in sampled) / len(sampled), 6)
            if sampled
            else None
        ),
        ann_recall_k=sampled[0].ann_recall_k if sampled else None,
        probe_size=sum(int(row.probe_size or 0) for row in sampled) if sampled else None,
    )


def _coverage_state(snapshots: Mapping[str, RetrievalCoverageSnapshot]) -> str:
    return "never_reconciled" if not snapshots else "ok"


# ---------------------------------------------------------------------------
# spaces
# ---------------------------------------------------------------------------


async def _counts_by_space(db: AsyncSession, column: Any) -> dict[uuid.UUID, int]:
    statement = select(column, func.count()).group_by(column)
    rows = (await db.execute(statement)).all()
    return {row[0]: int(row[1] or 0) for row in rows}


def _space_dto(
    row: VectorSpaceRow,
    *,
    dialect: str,
    documents: int,
    records: int,
    snapshots: Mapping[str, RetrievalCoverageSnapshot],
    last_run: BackgroundJob | None,
) -> ops.SpaceDTO:
    coverage = _coverage_dto(row, snapshots)
    return ops.SpaceDTO(
        space_id=str(row.id),
        name=row.name,
        status=ops.SpaceStatus(row.status),
        provider=row.provider,
        model=row.model,
        dim=int(row.dim),
        backend=_backend_for(row, dialect),
        metric=row.metric,
        index_table=row.index_table,
        documents=documents,
        records=records,
        coverage=coverage.coverage,
        stale=coverage.stale if snapshots else None,
        failed=coverage.failed if snapshots else None,
        created_at=_iso(row.created_at),
        activated_at=_iso(row.activated_at),
        retired_at=_iso(row.retired_at),
        last_reindex_at=_iso(last_run.created_at) if last_run is not None else None,
        last_error=(
            (last_run.error or "")[:ERROR_TEXT_LIMIT]
            if last_run is not None and last_run.status == "failed"
            else None
        ),
        gate=coverage.gate,
        as_of=coverage.as_of,
    )


async def read_spaces(db: AsyncSession) -> dict[str, Any]:
    """One ``SpaceDTO`` per persisted space plus the honest backend label."""
    dialects = _dialect(db)
    rows = await _all_spaces(db)
    documents = await _counts_by_space(db, VectorDocument.space_id)
    records = await _counts_by_space(db, VectorRecord.space_id)
    last_runs = await _last_run_per_space(db, [row.id for row in rows])
    spaces: list[dict[str, Any]] = []
    for row in rows:
        snapshots = await _latest_snapshots(db, row.id)
        spaces.append(
            _space_dto(
                row,
                dialect=dialects,
                documents=documents.get(row.id, 0),
                records=records.get(row.id, 0),
                snapshots=snapshots,
                last_run=last_runs.get(row.id),
            ).to_dict()
        )
    active = next((row for row in rows if row.status == "active"), None)
    backend = _backend_for(active, dialects)
    return {
        "state": "ok" if spaces else "empty",
        "count": len(spaces),
        "spaces": spaces,
        "backend": {
            "name": backend,
            "label": _BACKEND_LABEL[backend],
            "dialect": dialects,
            "semantic_available": backend != BACKEND_LINEAR,
        },
    }


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


def _contract_job_type(job_type: str) -> str | None:
    return _JOB_TYPE_MAP.get(job_type) or _JOB_TYPE_MAP.get(str(job_type).upper())


def _payload_scope(payload: Mapping[str, Any]) -> ops.RunScope:
    kind = payload.get("kind")
    kinds = payload.get("kinds")
    if not kind and isinstance(kinds, (list, tuple)) and len(kinds) == 1:
        kind = kinds[0]
    view = payload.get("view")
    since = payload.get("since")
    try:
        return ops.RunScope(
            kind=str(kind) if kind else None,
            view=str(view) if view in ops.V1_VIEWS else None,
            since=str(since) if since else None,
        )
    except ValueError:
        return ops.RunScope()


def _run_space(
    payload: Mapping[str, Any],
    *,
    by_id: Mapping[uuid.UUID, VectorSpaceRow],
    by_name: Mapping[str, VectorSpaceRow],
    fallback: VectorSpaceRow | None,
) -> VectorSpaceRow | None:
    raw_id = payload.get("space_id")
    if raw_id is not None:
        try:
            return by_id.get(uuid.UUID(str(raw_id)))
        except (TypeError, ValueError):
            return None
    raw_name = payload.get("space")
    if raw_name is not None:
        return by_name.get(str(raw_name))
    return fallback


async def _vector_jobs(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    status: str | None = None,
    space_id: uuid.UUID | None = None,
) -> tuple[list[_Run], int, bool]:
    """Resolved vector runs in the window plus unattributed/truncation flags."""
    rows = await _all_spaces(db)
    by_id = {row.id: row for row in rows}
    by_name = {row.name: row for row in rows}
    fallback = await default_space(db)
    conditions: list[Any] = [
        BackgroundJob.job_type.in_(_VECTOR_DB_JOB_TYPES),
        BackgroundJob.created_at >= start,
        BackgroundJob.created_at < end,
    ]
    if status is not None:
        conditions.append(BackgroundJob.status == status)
    scan_limit = RUN_PAGE_MAX * 4
    jobs = list(
        await db.scalars(
            select(BackgroundJob)
            .where(*conditions)
            .order_by(BackgroundJob.created_at.desc())
            .limit(scan_limit)
        )
    )
    resolved: list[_Run] = []
    unattributed = 0
    for job in jobs:
        contract_type = _contract_job_type(job.job_type)
        if contract_type is None:
            continue
        space = _run_space(job.payload or {}, by_id=by_id, by_name=by_name, fallback=fallback)
        if space is None:
            unattributed += 1
            continue
        if space_id is not None and space.id != space_id:
            continue
        budget = job.payload.get("budget") or job.payload.get("budget_tokens")
        budget_tokens = int(budget) if isinstance(budget, int) and budget > 0 else None
        resolved.append(
            _Run(
                job=job,
                job_type=contract_type,
                space=space,
                scope=_payload_scope(job.payload or {}),
                budget_tokens=budget_tokens,
            )
        )
    return resolved, unattributed, len(jobs) >= scan_limit


def _progress_detail(job: BackgroundJob) -> ops.RunProgressDTO | None:
    """The stored live counters, validated through the family contract.

    ``None`` for jobs that never wrote a detail (every non-vector family) and
    for a malformed row; the run itself still reads normally.
    """
    raw = job.progress_detail
    if not isinstance(raw, Mapping):
        return None
    try:
        return ops.RunProgressDTO(**dict(raw))
    except (TypeError, ValueError):
        return None


def _run_dto(run: _Run) -> ops.RunDTO:
    job = run.job
    return ops.RunDTO(
        run_id=str(job.id),
        space_id=str(run.space.id),
        job_type=run.job_type,
        status=ops.RunStatus(job.status),
        progress=max(0, min(int(job.progress or 0), 100)),
        stage=job.stage,
        scope=run.scope,
        budget_tokens=run.budget_tokens,
        created_at=_iso(job.created_at),
        started_at=_iso(job.claimed_at),
        finished_at=_iso(job.finished_at),
        heartbeat_at=_iso(job.heartbeat_at),
        error=(job.error or "")[:ERROR_TEXT_LIMIT] if job.error else None,
        cancel_requested=bool(job.cancel_requested),
        idempotency_key=job.idempotency_key,
        lock_key=job.lock_key,
        progress_detail=_progress_detail(job),
    )


async def _last_run_per_space(
    db: AsyncSession, space_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, BackgroundJob]:
    """Newest vector job per space (the Spaces card's last reindex/error)."""
    if not space_ids:
        return {}
    rows = list(
        await db.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.job_type.in_(_REINDEX_JOB_TYPES))
            .order_by(BackgroundJob.created_at.desc())
            .limit(RUN_PAGE_MAX * 4)
        )
    )
    by_id = {row.id: row for row in await _all_spaces(db)}
    by_name = {row.name: row for row in by_id.values()}
    fallback = await default_space(db)
    latest: dict[uuid.UUID, BackgroundJob] = {}
    for job in rows:
        space = _run_space(job.payload or {}, by_id=by_id, by_name=by_name, fallback=fallback)
        if space is None or space.id not in space_ids:
            continue
        latest.setdefault(space.id, job)
    return latest


async def read_runs(
    db: AsyncSession,
    *,
    space: VectorSpaceRow | None = None,
    kind: str | None = None,
    status: str | None = None,
    window: str = DEFAULT_WINDOW,
    limit: int = RUN_PAGE_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """The Runs section: vector runs in the window, newest first."""
    start, end, key = _window(window)
    if status is not None and status not in {member.value for member in ops.RunStatus}:
        raise ValidationError(f"Unknown run status {status!r}")
    if limit < 1 or limit > RUN_PAGE_MAX:
        raise ValidationError(f"limit must be between 1 and {RUN_PAGE_MAX}")
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    runs, unattributed, scan_truncated = await _vector_jobs(
        db, start=start, end=end, status=status, space_id=space.id if space else None
    )
    if kind is not None:
        runs = [run for run in runs if run.scope.kind == kind]
    total = len(runs)
    page = runs[offset : offset + limit]
    return {
        "state": "ok" if page else "empty",
        "window": _window_payload(start, end, key),
        "total": total,
        "limit": limit,
        "offset": offset,
        "unattributed_runs": unattributed,
        "scan_truncated": scan_truncated,
        "runs": [_run_dto(run).to_dict() for run in page],
    }


def _run_result(raw: Any) -> tuple[ops.RunResultDTO | None, str]:
    """Parse the handler result contract, bounding ``failed_ids`` at 500."""
    if not isinstance(raw, Mapping):
        return None, "absent"
    allowed = {
        "scanned",
        "embedded",
        "skipped",
        "failed",
        "failed_ids",
        "failed_ids_truncated",
        "gate",
    }
    payload = {key: raw[key] for key in allowed if key in raw}
    if "failed_ids" in payload:
        ids = payload["failed_ids"]
        if isinstance(ids, (list, tuple)):
            bounded, truncated = ops.truncate_failed_ids([str(item) for item in ids])
            payload["failed_ids"] = list(bounded)
            payload["failed_ids_truncated"] = bool(payload.get("failed_ids_truncated")) or truncated
    try:
        return ops.RunResultDTO(**payload), "ok"
    except (TypeError, ValueError):
        return None, "invalid"


async def read_run(db: AsyncSession, run_id: str) -> dict[str, Any]:
    """One run with stage/progress/result counters and bounded failed ids."""
    try:
        identifier = uuid.UUID(str(run_id))
    except (TypeError, ValueError):
        raise NotFoundError(f"no retrieval run {run_id!r}") from None
    job = await db.get(BackgroundJob, identifier)
    if job is None or _contract_job_type(job.job_type) is None:
        raise NotFoundError(f"no retrieval run {run_id!r}")
    spaces = await _all_spaces(db)
    space = _run_space(
        job.payload or {},
        by_id={row.id: row for row in spaces},
        by_name={row.name: row for row in spaces},
        fallback=await default_space(db),
    )
    if space is None:
        raise NotFoundError(f"retrieval run {run_id!r} has no resolvable space; it cannot be shown")
    budget = job.payload.get("budget") or job.payload.get("budget_tokens")
    run = _Run(
        job=job,
        job_type=_contract_job_type(job.job_type) or "VECTOR_REINDEX",
        space=space,
        scope=_payload_scope(job.payload or {}),
        budget_tokens=int(budget) if isinstance(budget, int) and budget > 0 else None,
    )
    result, result_state = _run_result(job.result)
    started = job.claimed_at or job.created_at
    finished = job.finished_at or datetime.now(UTC)
    duration = max((finished - started).total_seconds(), 0.0)
    detail = ops.RunDetailDTO(run=_run_dto(run), result=result, duration_seconds=duration)
    payload = detail.to_dict()
    action = (job.payload or {}).get("action")
    if action:
        payload["action"] = str(action)
    raw_result = job.result if isinstance(job.result, Mapping) else {}
    gate_payload = raw_result.get("activation_gate")
    if isinstance(gate_payload, Mapping):
        try:
            payload["activation_gate"] = ops.ActivationGateDTO(**dict(gate_payload)).to_dict()
        except (TypeError, ValueError):
            payload["activation_gate"] = None
    if raw_result.get("quality") is not None:
        from app.services.retrieval_quality import parse_persisted_compare

        compare = parse_persisted_compare(raw_result)
        payload["quality"] = compare.to_dict() if compare is not None else None
    return {
        "state": "ok" if result_state != "invalid" else "degraded",
        "detail": payload,
        "result_state": result_state,
        "failed_ids_limit": ops.FAILED_IDS_LIMIT,
    }


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


async def read_coverage(db: AsyncSession, space: VectorSpaceRow) -> dict[str, Any]:
    """Latest snapshot per kind plus the aggregate; cold space is explicit."""
    snapshots = await _latest_snapshots(db, space.id)
    kinds = set(
        await db.scalars(
            select(VectorDocument.kind).where(VectorDocument.space_id == space.id).distinct()
        )
    )
    per_kind: list[dict[str, Any]] = []
    for kind, row in snapshots.items():
        per_kind.append({"kind": kind, "coverage": _coverage_dto(space, {kind: row}).to_dict()})
    aggregate = _coverage_dto(space, snapshots)
    return {
        "state": _coverage_state(snapshots),
        "space_id": str(space.id),
        "name": space.name,
        "coverage": aggregate.to_dict(),
        "kinds": per_kind,
        "document_kinds": sorted(kinds),
        "missing_kinds": sorted(kinds - set(snapshots)),
        "ann_sampled": aggregate.sampled,
        "as_of": aggregate.as_of,
    }


# ---------------------------------------------------------------------------
# query health
# ---------------------------------------------------------------------------


def _json_text(column: Any, key: str, dialect: str) -> Any:
    """Dialect-aware JSON string extraction (JSONB operator / ``json_extract``)."""
    if dialect == "postgresql":
        return column[key].as_string()
    return func.json_extract(column, f"$.{key}")


def _normalized_uuid(value: Any) -> Any:
    return func.replace(func.lower(value), "-", "")


def _canonical_space_id(raw: Any, spaces: Sequence[VectorSpaceRow]) -> str:
    """Map a tagged space id to the persisted canonical form when known."""
    value = str(raw)
    normalized = value.replace("-", "").lower()
    for row in spaces:
        if str(row.id).replace("-", "").lower() == normalized:
            return str(row.id)
    return value


def _merge_histograms(rows: Sequence[RetrievalQueryRollup]) -> dict[float, int]:
    """Merge the bounded latency histograms into ``{upper_bound_ms: count}``.

    The payload is the contract's cumulative ``le`` map (plus an overflow
    entry); a list of ``{le, count}`` rows is accepted too. An unrecognizable
    payload is ignored rather than guessed.
    """
    merged: dict[float, int] = {}
    for row in rows:
        payload = row.latency_buckets
        if isinstance(payload, Mapping):
            items = payload.items()
        elif isinstance(payload, list):
            items = [
                (item.get("le"), item.get("count")) for item in payload if isinstance(item, Mapping)
            ]
        else:
            continue
        for raw_key, raw_count in items:
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            if count < 0:
                continue
            try:
                overflow = str(raw_key).lower() in {"inf", "+inf", "overflow"}
                bound = float("inf") if overflow else float(raw_key)
            except (TypeError, ValueError):
                continue
            merged[bound] = merged.get(bound, 0) + count
    return merged


def _histogram_percentile(merged: Mapping[float, int], fraction: float) -> float | None:
    """Bucket upper bound at ``fraction`` (histogram resolution, not exact)."""
    if not merged:
        return None
    ordered = sorted(merged)
    finite = [bound for bound in ordered if math.isfinite(bound)]
    overflow = merged.get(float("inf"), 0)
    total = (merged.get(finite[-1], 0) if finite else 0) + overflow
    if total <= 0:
        return None
    target = total * fraction
    for bound in finite:
        if merged.get(bound, 0) >= target:
            return bound
    return finite[-1] if finite else None


async def _rollup_rows(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    space: VectorSpaceRow | None,
    kind: str | None,
) -> list[RetrievalQueryRollup]:
    conditions: list[Any] = [
        RetrievalQueryRollup.bucket_start >= start,
        RetrievalQueryRollup.bucket_start < end,
    ]
    if space is not None:
        conditions.append(RetrievalQueryRollup.space_id == space.id)
    if kind is not None:
        conditions.append(RetrievalQueryRollup.kind == kind)
    return list(await db.scalars(select(RetrievalQueryRollup).where(*conditions)))


def _rollup_metrics(
    rows: Sequence[RetrievalQueryRollup],
) -> dict[str, Any]:
    total = sum(int(row.count) for row in rows)
    zero_results = sum(int(row.zero_results) for row in rows)
    degraded = sum(int(row.count) for row in rows if row.degraded_reason is not None)
    reasons: dict[str, int] = {}
    views: dict[str, int] = {}
    for row in rows:
        if row.degraded_reason is not None:
            reasons[row.degraded_reason] = reasons.get(row.degraded_reason, 0) + int(row.count)
        if row.view is not None:
            views[row.view] = views.get(row.view, 0) + int(row.count)
    histogram = _merge_histograms(rows)
    candidates = sum(int(row.candidates_sum) for row in rows)
    return {
        "query_count": total,
        "zero_result_rate": zero_results / total if total else None,
        "degraded_rate": degraded / total if total else None,
        "degraded_reasons": reasons,
        "per_view_hits": views,
        "p50_ms": _histogram_percentile(histogram, 0.50),
        "p95_ms": _histogram_percentile(histogram, 0.95),
        "candidates_avg": candidates / total if total else None,
        "histogram": histogram,
    }


async def read_query_health(
    db: AsyncSession,
    *,
    space: VectorSpaceRow | None,
    kind: str | None,
    window: str,
) -> dict[str, Any]:
    """Query-health aggregates from ``retrieval_query_rollups`` (never text)."""
    start, end, key = _window(window)
    if space is None:
        return {
            "state": "empty",
            "reason": "no_space_selected",
            "window": _window_payload(start, end, key),
            "query_health": None,
        }
    rows = await _rollup_rows(db, start=start, end=end, space=space, kind=kind)
    metrics = _rollup_metrics(rows)
    snapshots = await _latest_snapshots(db, space.id, [kind] if kind else None)
    sampled_rows = [row for row in snapshots.values() if row.ann_recall is not None]
    dto = ops.QueryHealthDTO(
        space_id=str(space.id),
        window_start=_iso(start) or "",
        window_end=_iso(end) or "",
        p50_ms=metrics["p50_ms"],
        p95_ms=metrics["p95_ms"],
        candidate_p50=None,
        candidate_p95=None,
        zero_result_rate=metrics["zero_result_rate"],
        degraded_rate=metrics["degraded_rate"],
        degraded_reasons=metrics["degraded_reasons"],
        per_view_hits=metrics["per_view_hits"],
        ann_recall=(
            round(sum(float(row.ann_recall or 0.0) for row in sampled_rows) / len(sampled_rows), 6)
            if sampled_rows
            else None
        ),
        ann_recall_k=sampled_rows[0].ann_recall_k if sampled_rows else None,
        probe_size=sum(int(row.probe_size or 0) for row in sampled_rows) if sampled_rows else None,
        sampled=bool(sampled_rows),
        sample_size=metrics["query_count"],
        query_count=metrics["query_count"],
    )
    state = "ok" if metrics["query_count"] else ("not_sampled" if dto.sampled else "empty")
    return {
        "state": state,
        "window": _window_payload(start, end, key),
        "query_health": dto.to_dict(),
        "candidates_avg": metrics["candidates_avg"],
        "candidate_percentiles": "unavailable" if metrics["query_count"] else "not_sampled",
        "latency_percentiles": (
            "histogram_bucket_upper_bound" if metrics["p95_ms"] else "not_sampled"
        ),
    }


# ---------------------------------------------------------------------------
# failures
# ---------------------------------------------------------------------------


async def _embed_failure_groups(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    space: VectorSpaceRow | None,
    spaces: Sequence[VectorSpaceRow],
) -> list[ops.FailureGroupDTO]:
    dialect = _dialect(db)
    space_expr = _json_text(AIGeneration.metadata_json, "space_id", dialect)
    document_expr = _json_text(AIGeneration.metadata_json, "document_id", dialect)
    conditions: list[Any] = [
        AIGeneration.task_type == "embed",
        AIGeneration.status == "error",
        AIGeneration.created_at >= start,
        AIGeneration.created_at < end,
        space_expr.is_not(None),
    ]
    if space is not None:
        conditions.append(_normalized_uuid(space_expr) == str(space.id).replace("-", ""))
    rows = (
        await db.execute(
            select(
                space_expr,
                func.count(AIGeneration.id),
                func.max(AIGeneration.created_at),
            )
            .where(*conditions)
            .group_by(space_expr)
        )
    ).all()
    groups: list[ops.FailureGroupDTO] = []
    for raw_space, count, last_seen in rows:
        if not raw_space:
            continue
        document_ids: list[str] = []
        if space is not None:
            ids: Any = await db.scalars(
                select(document_expr)
                .where(*conditions, document_expr.is_not(None))
                .distinct()
                .limit(FAILURE_DOCUMENT_IDS_LIMIT)
            )
            document_ids = [str(value) for value in ids.all() if value]
        groups.append(
            ops.FailureGroupDTO(
                kind=ops.FailureKind.EMBED_PROVIDER,
                space_id=_canonical_space_id(raw_space, spaces),
                count=int(count or 0),
                last_seen=_iso(last_seen),
                document_ids=tuple(document_ids),
                reason=ops.DegradedReason.EMBED_FAILED,
                retryable=True,
            )
        )
    return groups


def _failure_space_id(run: _Run) -> str:
    return str(run.space.id)


async def read_failures(
    db: AsyncSession,
    *,
    space: VectorSpaceRow | None,
    kind: str | None,
    window: str,
) -> dict[str, Any]:
    """Failure groups by kind: embed provider, indexing, gate and maintenance."""
    start, end, key = _window(window)
    if kind is not None and kind not in {member.value for member in ops.FailureKind}:
        raise ValidationError(f"Unknown failure kind {kind!r}")
    wanted = {kind} if kind else {member.value for member in ops.FailureKind}
    groups: list[ops.FailureGroupDTO] = []
    spaces = await _all_spaces(db)
    if ops.FailureKind.EMBED_PROVIDER.value in wanted:
        groups.extend(
            await _embed_failure_groups(db, start=start, end=end, space=space, spaces=spaces)
        )

    runs, _unattributed, _truncated = await _vector_jobs(
        db, start=start, end=end, status="failed", space_id=space.id if space else None
    )
    for run in runs:
        result, _state = _run_result(run.job.result)
        gate_failed = result is not None and result.gate is ops.GateStatus.FAIL
        if run.job_type == "VECTOR_MAINTENANCE" and "maintenance" in wanted:
            groups.append(
                ops.FailureGroupDTO(
                    kind=ops.FailureKind.MAINTENANCE,
                    space_id=_failure_space_id(run),
                    count=1,
                    last_seen=_iso(run.job.finished_at or run.job.created_at),
                    reason=None,
                    retryable=True,
                    run_id=str(run.job.id),
                )
            )
        elif run.job_type == "VECTOR_CUTOVER" and gate_failed and "cutover_gate" in wanted:
            groups.append(
                ops.FailureGroupDTO(
                    kind=ops.FailureKind.CUTOVER_GATE,
                    space_id=_failure_space_id(run),
                    count=1,
                    last_seen=_iso(run.job.finished_at or run.job.created_at),
                    reason=None,
                    retryable=False,
                    run_id=str(run.job.id),
                )
            )
        elif run.job_type == "VECTOR_REINDEX" and "indexing" in wanted:
            failed_ids = list(result.failed_ids) if result is not None else []
            count = max(len(failed_ids), int(result.failed) if result is not None else 1, 1)
            groups.append(
                ops.FailureGroupDTO(
                    kind=ops.FailureKind.INDEXING,
                    space_id=_failure_space_id(run),
                    count=count,
                    last_seen=_iso(run.job.finished_at or run.job.created_at),
                    document_ids=tuple(failed_ids[:FAILURE_DOCUMENT_IDS_LIMIT]),
                    reason=None,
                    retryable=True,
                    run_id=str(run.job.id),
                )
            )
    groups.sort(key=lambda group: group.last_seen or "", reverse=True)
    bounded = groups[:FAILURE_GROUP_LIMIT]
    return {
        "state": "ok" if bounded else "empty",
        "window": _window_payload(start, end, key),
        "groups": [group.to_dict() for group in bounded],
        "truncated": len(groups) > FAILURE_GROUP_LIMIT,
    }


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------

_USAGE_MEASURES = {"calls": 0, "tokens_in": 0, "tokens_out": 0}


def _usage_row(
    day: str, space_id: str, kind: str, calls: int, tokens_in: int, tokens_out: int, reindex: int
) -> ops.UsageRowDTO:
    return ops.UsageRowDTO(
        day=day,
        space_id=space_id,
        kind=kind,
        calls=calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        reindex_calls=reindex,
    )


async def _read_budget(
    db: AsyncSession,
) -> tuple[ops.BudgetDTO | None, dict[str, Any] | None]:
    budget = await db.scalars(
        select(AIBudget)
        .where(
            AIBudget.is_active.is_(True),
            AIBudget.task_type == "embed",
            AIBudget.user_id.is_(None),
        )
        .order_by(AIBudget.name)
        .limit(1)
    )
    row = budget.first()
    if row is None:
        return None, None
    try:
        start = budget_window_start(row.window)
    except ValueError:
        return None, None
    used = (
        await db.execute(
            select(
                func.coalesce(func.sum(AIGeneration.tokens_in), 0)
                + func.coalesce(func.sum(AIGeneration.tokens_out), 0)
            ).where(
                AIGeneration.task_type == "embed",
                AIGeneration.status == "ok",
                AIGeneration.created_at >= start,
            )
        )
    ).scalar() or 0
    return (
        ops.BudgetDTO(window=row.window, max_tokens=int(row.max_tokens), used_tokens=int(used)),
        {"name": row.name, "exhausted": int(used) >= int(row.max_tokens)},
    )


async def read_usage(
    db: AsyncSession,
    *,
    space: VectorSpaceRow | None,
    kind: str | None,
    window: str,
) -> dict[str, Any]:
    """Embed calls/tokens by day, space and kind, plus the token budget."""
    start, end, key = _window(window)
    dialect = _dialect(db)
    space_expr = _json_text(AIGeneration.metadata_json, "space_id", dialect)
    kind_expr = _json_text(AIGeneration.metadata_json, "kind", dialect)
    day_expr = bucket_expr(dialect, AIGeneration.created_at, "day")
    conditions: list[Any] = [
        AIGeneration.task_type == "embed",
        AIGeneration.created_at >= start,
        AIGeneration.created_at < end,
    ]
    tagged_conditions = [*conditions, space_expr.is_not(None)]
    if space is not None:
        tagged_conditions.append(_normalized_uuid(space_expr) == str(space.id).replace("-", ""))
    if kind is not None:
        tagged_conditions.append(kind_expr == kind)
    rows = (
        await db.execute(
            select(
                day_expr.label("day"),
                space_expr.label("space_id"),
                kind_expr.label("kind"),
                func.count(AIGeneration.id),
                func.coalesce(func.sum(AIGeneration.tokens_in), 0),
                func.coalesce(func.sum(AIGeneration.tokens_out), 0),
            )
            .where(*tagged_conditions)
            .group_by(day_expr, space_expr, kind_expr)
            .order_by(day_expr)
        )
    ).all()
    untagged = (
        await db.execute(
            select(func.count(AIGeneration.id)).where(
                *conditions,
                AIGeneration.task_type == "embed",
                space_expr.is_(None),
            )
        )
    ).scalar() or 0

    runs, _unattributed, _truncated = await _vector_jobs(
        db, start=start, end=end, space_id=space.id if space else None
    )
    reindex: dict[tuple[str, str, str], int] = {}
    for run in runs:
        if run.scope.kind is None:
            continue
        run_day = run.job.created_at.astimezone(UTC).strftime("%Y-%m-%d")
        bucket = (run_day, str(run.space.id), run.scope.kind)
        reindex[bucket] = reindex.get(bucket, 0) + 1

    spaces = await _all_spaces(db)
    by_group: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
    for day, raw_space, raw_kind, calls, tokens_in, tokens_out in rows:
        if not raw_space:
            continue
        space_key = _canonical_space_id(raw_space, spaces)
        kind_key = str(raw_kind) if raw_kind else "unattributed"
        day_key = bucket_key(day, "day")
        group = by_group.setdefault((space_key, kind_key), {})
        group[day_key] = {
            "calls": int(calls or 0),
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
        }

    series: list[ops.UsageRowDTO] = []
    for (space_key, kind_key), by_day in list(by_group.items())[:USAGE_GROUP_LIMIT]:
        for point in zero_filled(by_day, start, end, "day", dict(_USAGE_MEASURES)):
            series.append(
                _usage_row(
                    day=str(point["bucket"]),
                    space_id=space_key,
                    kind=kind_key,
                    calls=int(point["calls"]),
                    tokens_in=int(point["tokens_in"]),
                    tokens_out=int(point["tokens_out"]),
                    reindex=reindex.get((str(point["bucket"]), space_key, kind_key), 0),
                )
            )
    budget, budget_meta = await _read_budget(db)
    usage = ops.UsageDTO(
        window_start=_iso(start) or "",
        window_end=_iso(end) or "",
        rows=tuple(series),
        budget=budget,
    )
    return {
        "state": "ok" if series else "empty",
        "window": _window_payload(start, end, key),
        "usage": usage.to_dict(),
        "untagged_calls": int(untagged),
        "groups_truncated": len(by_group) > USAGE_GROUP_LIMIT,
        "budget": budget_meta,
        "units": "tokens/calls",
    }


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------


def _quality_set_summary(golden: ops.GoldenQuerySet) -> dict[str, Any]:
    """The versioned set without query text (ids, k and floors only)."""
    return {
        "space_id": golden.space_id,
        "set_version": golden.set_version,
        "k": golden.k,
        "floor_recall": golden.floor_recall,
        "floor_precision": golden.floor_precision,
        "query_count": len(golden.queries),
        "query_ids": [query.query_id for query in golden.queries],
        "revision_key": golden.revision_key,
    }


async def _latest_persisted_compare(
    db: AsyncSession, space: VectorSpaceRow
) -> tuple[BackgroundJob, ops.QualityCompareDTO] | None:
    """The newest stored ``quality_compare`` cutover evaluation for a space."""
    rows = list(
        await db.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.job_type.in_(["vector_cutover", "VECTOR_CUTOVER"]),
                BackgroundJob.status == "succeeded",
            )
            .order_by(BackgroundJob.created_at.desc())
            .limit(RUN_PAGE_MAX)
        )
    )
    from app.services.retrieval_quality import parse_persisted_compare

    for job in rows:
        if (job.payload or {}).get("action") != "quality_compare":
            continue
        compare = parse_persisted_compare(job.result)
        if compare is None or compare.new_space_id != str(space.id):
            continue
        return job, compare
    return None


def _quality_from_compare(compare: ops.QualityCompareDTO, *, space_id: str) -> ops.QualityDTO:
    """The candidate's own score block behind a persisted compare."""
    return ops.QualityDTO(
        space_id=space_id,
        set_version=compare.set_version,
        k=compare.k,
        recall_at_k=compare.new_recall_at_k,
        precision_at_k=compare.new_precision_at_k,
        passed=compare.passed,
        queries=compare.queries,
        floor_recall=compare.floor_recall,
        floor_precision=compare.floor_precision,
        generated_at=compare.generated_at,
    )


async def read_quality(
    db: AsyncSession,
    *,
    space: VectorSpaceRow,
    golden_sets: Sequence[ops.GoldenQuerySet] | None = None,
    retrieved_by_query: Mapping[str, Sequence[str]] | None = None,
    window: str = DEFAULT_WINDOW,
) -> dict[str, Any]:
    """The versioned golden-query set and, when a compare exists, its scores.

    Q1b persists every ``quality_compare`` outcome on a completed
    ``VECTOR_CUTOVER`` evaluation run. This reader shows the newest one for
    the space so the Dashboard/Quality section reports the same evidence the
    activation gate used — still ids and scores only, never query text.
    """
    start, end, key = _window(window)
    window_payload = _window_payload(start, end, key)
    if golden_sets is None:
        from app.services.retrieval_quality import load_golden_sets

        golden_sets = load_golden_sets()
    from app.services.retrieval_quality import select_golden_set

    golden = select_golden_set(space, golden_sets)
    if golden is None:
        return {
            "state": "no_golden_set",
            "space_id": str(space.id),
            "name": space.name,
            "sampled": False,
            "set": None,
            "quality": None,
            "window": window_payload,
        }
    summary = _quality_set_summary(golden)
    if retrieved_by_query is not None:
        quality = ops.evaluate_quality_set(golden, retrieved_by_query)
        return {
            "state": "ok",
            "space_id": str(space.id),
            "name": space.name,
            "sampled": True,
            "set": summary,
            "quality": quality.to_dict(),
            "activation_gate": str(quality.activation_gate),
            "window": window_payload,
        }
    persisted = await _latest_persisted_compare(db, space)
    if persisted is not None:
        job, compare = persisted
        quality = _quality_from_compare(compare, space_id=str(space.id))
        fresh = compare.set_version == golden.set_version and compare.k == golden.k
        return {
            "state": "sampled" if fresh else "stale_compare",
            "space_id": str(space.id),
            "name": space.name,
            "sampled": True,
            "set": summary,
            "quality": quality.to_dict(),
            "compare": compare.to_dict(),
            "activation_gate": (
                str(quality.activation_gate) if fresh else str(ops.GateStatus.UNKNOWN)
            ),
            "compare_run_id": str(job.id),
            "compare_set_version": compare.set_version,
            "window": window_payload,
        }
    return {
        "state": "not_sampled",
        "space_id": str(space.id),
        "name": space.name,
        "sampled": False,
        "set": summary,
        "quality": None,
        "reason": "compare_not_run",
        "window": window_payload,
    }


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------


async def read_overview(db: AsyncSession, *, window: str = DEFAULT_WINDOW) -> dict[str, Any]:
    """Instance-wide KPIs composed from every source the surface reads."""
    start, end, key = _window(window)
    dialect = _dialect(db)
    spaces = await _all_spaces(db)
    active = next((row for row in spaces if row.status == ops.SpaceStatus.ACTIVE.value), None)
    backend = _backend_for(active, dialect)
    live_ids = [row.id for row in spaces if row.status != ops.SpaceStatus.RETIRED.value]
    if live_ids:
        documents = (
            await db.execute(
                select(func.count())
                .select_from(VectorDocument)
                .where(VectorDocument.space_id.in_(live_ids))
            )
        ).scalar() or 0
        records = (
            await db.execute(
                select(func.count())
                .select_from(VectorRecord)
                .where(VectorRecord.space_id.in_(live_ids))
            )
        ).scalar() or 0
    else:
        documents = records = 0
    snapshots: dict[tuple[uuid.UUID, str], RetrievalCoverageSnapshot] = {}
    for row in await db.scalars(
        select(RetrievalCoverageSnapshot).order_by(RetrievalCoverageSnapshot.as_of)
    ):
        if row.space_id in live_ids:
            snapshots[(row.space_id, row.kind)] = row
    total_documents = sum(int(row.total) for row in snapshots.values())
    embedded = sum(int(row.embedded) for row in snapshots.values())
    stale = sum(int(row.stale) for row in snapshots.values())
    failed = sum(int(row.failed) for row in snapshots.values())
    sampled = [row for row in snapshots.values() if row.ann_recall is not None]
    coverage = (
        {
            "state": "snapshot",
            "coverage": embedded / total_documents if total_documents else None,
            "total": total_documents,
            "embedded": embedded,
            "stale": stale,
            "failed": failed,
            "as_of": _iso(max((row.as_of for row in snapshots.values()), default=None)),
            "ann_sampled": bool(sampled),
        }
        if snapshots
        else {
            "state": "never_reconciled",
            "coverage": None,
            "total": 0,
            "embedded": 0,
            "stale": None,
            "failed": None,
            "as_of": None,
            "ann_sampled": False,
        }
    )

    rollups = await _rollup_rows(db, start=start, end=end, space=None, kind=None)
    metrics = _rollup_metrics(rollups)
    embed = (
        await db.execute(
            select(
                func.count(AIGeneration.id),
                func.sum(case((AIGeneration.status == "error", 1), else_=0)),
                func.coalesce(func.sum(AIGeneration.tokens_in), 0),
                func.coalesce(func.sum(AIGeneration.tokens_out), 0),
            ).where(
                AIGeneration.task_type == "embed",
                AIGeneration.created_at >= start,
                AIGeneration.created_at < end,
            )
        )
    ).one()
    runs, unattributed, scan_truncated = await _vector_jobs(db, start=start, end=end)
    latest = next((run for run in runs if run.job.job_type in _REINDEX_JOB_TYPES), None)
    audit_rows = (
        await db.execute(
            select(
                func.count(AuditEvent.id),
            ).where(
                AuditEvent.action.like("vector.%"),
                AuditEvent.created_at >= start,
                AuditEvent.created_at < end,
            )
        )
    ).scalar() or 0
    changes = list(
        await db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.action.like("vector.%"),
                AuditEvent.created_at >= start,
                AuditEvent.created_at < end,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(RECENT_CHANGES_LIMIT)
        )
    )

    return {
        "state": "ok" if spaces else "empty",
        "window": _window_payload(start, end, key),
        "spaces": {
            "total": len(spaces),
            "active": sum(1 for row in spaces if row.status == "active"),
            "building": sum(1 for row in spaces if row.status == "building"),
            "retired": sum(1 for row in spaces if row.status == "retired"),
        },
        "backend": {
            "name": backend,
            "label": _BACKEND_LABEL[backend],
            "dialect": dialect,
            "semantic_available": backend != BACKEND_LINEAR,
        },
        "documents": int(documents),
        "records": int(records),
        "coverage": coverage,
        "queries": {
            "count": metrics["query_count"],
            "p50_ms": metrics["p50_ms"],
            "p95_ms": metrics["p95_ms"],
            "zero_result_rate": metrics["zero_result_rate"],
            "degraded_rate": metrics["degraded_rate"],
            "ann_sampled": bool(sampled),
            "latency_percentiles": (
                "histogram_bucket_upper_bound" if metrics["p95_ms"] else "not_sampled"
            ),
        },
        "embed": {
            "calls": int(embed[0] or 0),
            "errors": int(embed[1] or 0),
            "tokens_in": int(embed[2] or 0),
            "tokens_out": int(embed[3] or 0),
        },
        "runs": {
            "total": len(runs),
            "active": sum(1 for run in runs if _run_dto(run).active),
            "unattributed": unattributed,
            "scan_truncated": scan_truncated,
            "last_reindex_at": _iso(latest.job.created_at) if latest is not None else None,
            "last_status": latest.job.status if latest is not None else None,
        },
        "changes": {
            "state": "ok" if int(audit_rows) else "empty",
            "reason": None if int(audit_rows) else "audit_emitter_pending",
            "count": int(audit_rows),
            "recent": [
                {
                    "action": row.action,
                    "actor": row.actor,
                    "resource": row.resource,
                    "outcome": row.outcome,
                    "created_at": _iso(row.created_at),
                }
                for row in changes
            ],
        },
        "window_end": _iso(end),
    }


def _document_status_row(
    source_id: str,
    state: str,
    reason: str | None,
    records: int,
    indexed_at: str | None,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "state": state,
        "reason": reason,
        "records": records,
        "indexed_at": indexed_at,
    }


async def read_document_status(
    db: AsyncSession, *, kind: str, source_ids: Sequence[str]
) -> dict[str, Any]:
    """Per-source index state for the active content space.

    Aggregate-only: the payload carries the requested source ids, the state
    of each, record counts, timestamps and the space facts — never document
    text. An unknown ``kind``, an empty list, more than
    ``DOCUMENT_STATUS_LIMIT`` ids or a non-UUID id raises
    :class:`ValidationError` (the caller caps itself; a silent truncation
    would lie about what it checked).
    """
    if kind not in DOCUMENT_STATUS_KINDS:
        raise ValidationError(
            f"Unknown document kind {kind!r}; expected one of {DOCUMENT_STATUS_KINDS}"
        )
    if not source_ids:
        raise ValidationError("at least one source id is required")
    if len(source_ids) > DOCUMENT_STATUS_LIMIT:
        raise ValidationError(
            f"at most {DOCUMENT_STATUS_LIMIT} source ids per request; "
            "split the request instead of relying on truncation"
        )
    canonical: list[str] = []
    for raw in source_ids:
        try:
            value = str(uuid.UUID(str(raw).strip()))
        except (TypeError, ValueError):
            raise ValidationError(f"source id {raw!r} is not a UUID") from None
        if value not in canonical:
            canonical.append(value)

    space = await default_space(db)
    if space is None:
        return {
            "kind": kind,
            "space": None,
            "documents": [
                _document_status_row(value, "off", "no_active_space", 0, None)
                for value in canonical
            ],
        }

    rows = list(
        await db.scalars(
            select(VectorDocument).where(
                VectorDocument.space_id == space.id,
                VectorDocument.kind == kind,
                VectorDocument.source_id.in_(canonical),
            )
        )
    )
    by_source = {row.source_id: row for row in rows}
    counts: dict[uuid.UUID, int] = {}
    if by_source:
        count_rows = (
            await db.execute(
                select(VectorRecord.document_id, func.count())
                .where(VectorRecord.document_id.in_([row.id for row in by_source.values()]))
                .group_by(VectorRecord.document_id)
            )
        ).all()
        counts = {document_id: int(total or 0) for document_id, total in count_rows}

    documents: list[dict[str, Any]] = []
    for source_id in canonical:
        document = by_source.get(source_id)
        if document is None:
            documents.append(
                _document_status_row(source_id, "missing", "document_missing", 0, None)
            )
            continue
        records = counts.get(document.id, 0)
        indexed_at = _iso(document.updated_at)
        if records == 0:
            documents.append(
                _document_status_row(source_id, "incomplete", "no_records", 0, indexed_at)
            )
            continue
        loaded = await load_source(db, kind, source_id)
        if loaded is None:
            documents.append(
                _document_status_row(
                    source_id, "missing", "source_unavailable", records, indexed_at
                )
            )
            continue
        if document.schema_version != int(COMPOSER_VERSION):
            documents.append(
                _document_status_row(
                    source_id, "stale", "schema_version_mismatch", records, indexed_at
                )
            )
            continue
        if document.source_hash != loaded.composed.source_hash:
            documents.append(
                _document_status_row(
                    source_id, "stale", "source_hash_mismatch", records, indexed_at
                )
            )
            continue
        if records != len(loaded.composed.records):
            documents.append(
                _document_status_row(
                    source_id, "incomplete", "record_count_mismatch", records, indexed_at
                )
            )
            continue
        documents.append(_document_status_row(source_id, "current", None, records, indexed_at))

    return {
        "kind": kind,
        "space": {
            "space_id": str(space.id),
            "name": space.name,
            "status": space.status,
            "backend": _backend_for(space, _dialect(db)),
            "model": space.model,
            "dim": int(space.dim),
        },
        "documents": documents,
    }


__all__ = [
    "DOCUMENT_STATUS_KINDS",
    "DOCUMENT_STATUS_LIMIT",
    "READ_WINDOWS",
    "RUN_PAGE_LIMIT",
    "RUN_PAGE_MAX",
    "default_space",
    "read_coverage",
    "read_document_status",
    "read_failures",
    "read_overview",
    "read_quality",
    "read_query_health",
    "read_run",
    "read_runs",
    "read_spaces",
    "read_usage",
    "resolve_space",
]
