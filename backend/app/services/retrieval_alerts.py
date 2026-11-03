"""Bounded retrieval-operations alerts through the notification funnel (plan 51 Q1c).

One evaluator pass reads only the Q1 read model: the latest coverage
snapshot per ``(space, kind)``, the recent ``VECTOR_*`` runs, the persisted
quality compare, the 15-minute query rollups, the system embed assignment,
the physical pgvector state and the token-denominated embed budget. It never
scans the corpus or the full history, and every emission goes through
:meth:`app.services.notification_service.NotificationService.emit` — there is
no second delivery path.

Dedup and recovery are one operation. A kind's active keys are the keys whose
condition currently holds; any older notification carrying that kind's key
prefix but no longer active (or past its dedup TTL) has its ``dedup_key``
released, so a later recurrence is a new alert. The inbox history is kept.

Payloads carry ids, counts, scores, reasons and token usage only — never
document/query/prompt text (the family no-raw-text rule is asserted on every
emitted payload).

The kinds, thresholds, windows, dedup scopes, daily caps and manage URLs come
from the vendored contract's :data:`app.storage.retrieval_ops.ALERT_DEFAULTS`;
this module only computes whether each condition holds.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budgets import window_start as budget_window_start
from app.ai.providers.resolution import resolve_task_model
from app.models.ai_model import AIBudget, AIGeneration
from app.models.engagement_model import Notification
from app.models.enums import AITaskType, BackgroundJobStatus
from app.models.user_model import User
from app.models.vector_model import RetrievalCoverageSnapshot
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services import notification_service, retrieval_jobs
from app.services import retrieval_ops_reads as reads
from app.storage import retrieval_ops as ops

logger = logging.getLogger(__name__)

ALERT_KINDS: tuple[str, ...] = tuple(default.kind for default in ops.ALERT_DEFAULTS)
_ALERT_BY_KIND = {default.kind: default for default in ops.ALERT_DEFAULTS}

ADMIN_FANOUT_LIMIT = 20
RUN_WINDOW_DAYS = 30
RUN_SCAN_LIMIT = reads.RUN_PAGE_MAX * 4
DEDUP_ROW_LIMIT = 500
TERMINAL_STATUSES = (
    BackgroundJobStatus.SUCCEEDED.value,
    BackgroundJobStatus.FAILED.value,
    BackgroundJobStatus.CANCELLED.value,
)
RUN_BASED_KINDS = {"retrieval.reindex_failed", "retrieval.reindex_stalled"}

MANAGE_URLS = {default.kind: default.manage_url for default in ops.ALERT_DEFAULTS}
TITLES = {
    "retrieval.coverage_low": "Retrieval coverage below gate",
    "retrieval.reindex_failed": "Retrieval reindex failed",
    "retrieval.reindex_stalled": "Retrieval reindex stalled",
    "retrieval.quality_gate": "Retrieval quality below floor",
    "retrieval.query_slo": "Retrieval query latency above budget",
    "retrieval.degraded_rate": "Retrieval degraded query share high",
    "retrieval.provider_unassigned": "Embeddings provider not assigned",
    "retrieval.index_missing": "Retrieval index missing",
    "retrieval.budget_exhausted": "Embedding token budget exhausted",
    "retrieval.space_drop_pending": "Retired retrieval space waiting to drop",
}

RUNS_URL = "/settings/audit?tab=retrieval&section=runs"
QUALITY_URL = "/settings/audit?tab=retrieval&section=quality"
QUERY_HEALTH_URL = "/settings/audit?tab=retrieval&section=query-health"
USAGE_URL = "/settings/audit?tab=retrieval&section=usage"
TOOLS_URL = "/settings/tools?section=retrieval"


@dataclass(frozen=True)
class AlertCandidate:
    """One condition that currently holds and should be in the inbox."""

    kind: str
    dedup_key: str
    title: str
    body: str
    payload: dict[str, Any]
    source_ref: dict[str, Any] | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    moment = _as_utc(value)
    return moment.isoformat().replace("+00:00", "Z") if moment is not None else None


def _dedup(kind: str, *parts: Any) -> str:
    return ":".join([kind, *(str(part) for part in parts)])


def _is_postgres(db: AsyncSession) -> bool:
    return str(db.get_bind().dialect.name) == "postgresql"


async def pg_index_state(db: AsyncSession, index_table: str) -> tuple[bool, bool]:
    """``(extension_present, table_present)`` for one pgvector index table."""
    extension = await db.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    present = await db.scalar(
        text("SELECT to_regclass(:table) IS NOT NULL"), {"table": index_table}
    )
    return bool(extension), bool(present)


def _run_result_counts(run: Any) -> dict[str, int]:
    result = run.job.result if isinstance(run.job.result, Mapping) else {}
    counts: dict[str, int] = {}
    for key in ("scanned", "embedded", "skipped", "failed"):
        value = result.get(key)
        if isinstance(value, int):
            counts[key] = max(value, 0)
    return counts


class RetrievalAlertService:
    """Evaluate the ten contract alerts once and reconcile their dedup keys."""

    def __init__(self, db: AsyncSession, *, now: datetime | None = None):
        self.db = db
        self.now = _as_utc(now) or _utcnow()
        self._spaces: list[VectorSpaceRow] | None = None
        self._active_spaces: list[VectorSpaceRow] | None = None
        self._runs_truncated = False

    # ------------------------------------------------------------- entry

    async def evaluate(self, *, commit: bool = True) -> dict[str, Any]:
        """Run every evaluator; a failure in one kind never blocks the rest."""
        recipients = await self._admin_recipients()
        service = notification_service.NotificationService(self.db)
        summary: dict[str, Any] = {}
        emitted_total = 0
        for kind, evaluator in (
            ("retrieval.coverage_low", self._coverage_low),
            ("retrieval.reindex_failed", self._reindex_failed),
            ("retrieval.reindex_stalled", self._reindex_stalled),
            ("retrieval.quality_gate", self._quality_gate),
            ("retrieval.query_slo", self._query_slo),
            ("retrieval.degraded_rate", self._degraded_rate),
            ("retrieval.provider_unassigned", self._provider_unassigned),
            ("retrieval.index_missing", self._index_missing),
            ("retrieval.budget_exhausted", self._budget_exhausted),
            ("retrieval.space_drop_pending", self._space_drop_pending),
        ):
            try:
                candidates = await evaluator()
                result = await self._sync(kind, candidates, recipients, service=service)
            except Exception:
                logger.warning("retrieval alert evaluator %s failed", kind, exc_info=True)
                summary[kind] = {"state": "error", "active": 0, "emitted": 0, "released": 0}
                continue
            emitted_total += result["emitted"]
            summary[kind] = {"state": "ok", **result}
        if commit:
            await self.db.commit()
        return {
            "state": "ok",
            "checked_at": _iso(self.now),
            "kinds": summary,
            "emitted": emitted_total,
            "recipients": len(recipients),
        }

    # ----------------------------------------------------------- helpers

    async def _admin_recipients(self) -> list[uuid.UUID]:
        rows = await self.db.scalars(
            select(User.id)
            .where(User.is_admin.is_(True), User.is_active.is_(True))
            .order_by(User.created_at, User.id)
            .limit(ADMIN_FANOUT_LIMIT)
        )
        return list(rows)

    async def _all_spaces(self) -> list[VectorSpaceRow]:
        if self._spaces is None:
            self._spaces = await reads._all_spaces(self.db)
        return self._spaces

    async def _live_spaces(self) -> list[VectorSpaceRow]:
        """Spaces that are still managed (active/building), never retired."""
        if self._active_spaces is None:
            self._active_spaces = [
                space
                for space in await self._all_spaces()
                if space.status != ops.SpaceStatus.RETIRED.value
            ]
        return self._active_spaces

    async def _latest_snapshots(
        self, space_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, RetrievalCoverageSnapshot]]:
        """Latest snapshot per ``(space, kind)`` with one bounded query."""
        if not space_ids:
            return {}
        latest = (
            select(
                RetrievalCoverageSnapshot.space_id,
                RetrievalCoverageSnapshot.kind,
                func.max(RetrievalCoverageSnapshot.as_of).label("as_of"),
            )
            .where(RetrievalCoverageSnapshot.space_id.in_(space_ids))
            .group_by(RetrievalCoverageSnapshot.space_id, RetrievalCoverageSnapshot.kind)
            .subquery()
        )
        rows = await self.db.scalars(
            select(RetrievalCoverageSnapshot).join(
                latest,
                and_(
                    RetrievalCoverageSnapshot.space_id == latest.c.space_id,
                    RetrievalCoverageSnapshot.kind == latest.c.kind,
                    RetrievalCoverageSnapshot.as_of == latest.c.as_of,
                ),
            )
        )
        grouped: dict[uuid.UUID, dict[str, RetrievalCoverageSnapshot]] = {}
        for row in rows:
            grouped.setdefault(row.space_id, {})[row.kind] = row
        return grouped

    async def _runs_in_window(self) -> list[Any]:
        start = self.now - timedelta(days=RUN_WINDOW_DAYS)
        runs, _unattributed, truncated = await reads._vector_jobs(
            self.db, start=start, end=self.now
        )
        self._runs_truncated = bool(truncated) or len(runs) >= RUN_SCAN_LIMIT
        return runs[:RUN_SCAN_LIMIT]

    async def _sync(
        self,
        kind: str,
        candidates: Sequence[AlertCandidate],
        recipients: Sequence[uuid.UUID],
        *,
        service: notification_service.NotificationService,
    ) -> dict[str, int]:
        """Release recovered/expired dedup keys, then emit the active ones."""
        default = _ALERT_BY_KIND[kind]
        active = {candidate.dedup_key for candidate in candidates}
        prefix = f"{kind}:"
        allow_release = not (self._runs_truncated and kind in RUN_BASED_KINDS)
        released = 0
        rows = await self.db.scalars(
            select(Notification)
            .where(Notification.dedup_key.startswith(prefix, autoescape=True))
            .order_by(Notification.created_at.desc())
            .limit(DEDUP_ROW_LIMIT)
        )
        for row in rows:
            expires = _as_utc(row.dedup_expires_at)
            expired = expires is not None and expires <= self.now
            if row.dedup_key in active and not expired:
                continue
            if row.dedup_key not in active and not allow_release:
                continue
            row.dedup_key = None
            row.dedup_expires_at = None
            released += 1
        if released:
            await self.db.flush()

        emitted = 0
        for candidate in candidates:
            event = await service.emit(
                kind,
                list(recipients),
                title=candidate.title,
                body=candidate.body,
                payload=ops.assert_no_raw_text(dict(candidate.payload)),
                source_ref=candidate.source_ref,
                dedup_key=candidate.dedup_key,
                max_per_day=default.daily_cap,
            )
            if event is not None:
                emitted += 1
        return {"active": len(candidates), "emitted": emitted, "released": released}

    # --------------------------------------------------------- evaluators

    async def _coverage_low(self) -> list[AlertCandidate]:
        spaces = await self._live_spaces()
        if not spaces:
            return []
        snapshots = await self._latest_snapshots([space.id for space in spaces])
        candidates: list[AlertCandidate] = []
        for space in spaces:
            rows = snapshots.get(space.id)
            if not rows:
                continue
            coverage = reads._coverage_dto(space, rows)
            if coverage.coverage is None or coverage.coverage >= ops.COVERAGE_GATE:
                continue
            if await retrieval_jobs.active_run_for_space(self.db, space.id) is not None:
                continue
            candidates.append(
                AlertCandidate(
                    kind="retrieval.coverage_low",
                    dedup_key=_dedup("retrieval.coverage_low", space.id),
                    title=TITLES["retrieval.coverage_low"],
                    body=(
                        f"{space.name} is at {coverage.coverage:.2%} coverage "
                        f"(gate {ops.COVERAGE_GATE:.1%}) with no run building it."
                    ),
                    payload={
                        "link": TOOLS_URL,
                        "space_id": str(space.id),
                        "space": space.name,
                        "coverage": round(float(coverage.coverage), 6),
                        "gate": ops.COVERAGE_GATE,
                        "total": coverage.total,
                        "embedded": coverage.embedded,
                        "missing": coverage.missing,
                        "as_of": coverage.as_of,
                    },
                    source_ref={"kind": "retrieval_space", "space_id": str(space.id)},
                )
            )
        return candidates

    async def _reindex_failed(self) -> list[AlertCandidate]:
        latest: dict[tuple[uuid.UUID, str], Any] = {}
        for run in await self._runs_in_window():
            if run.job.status not in TERMINAL_STATUSES:
                continue
            alert_scope = run.scope.kind or run.job_type.lower()
            latest.setdefault((run.space.id, alert_scope), run)
        candidates: list[AlertCandidate] = []
        for (space_id, alert_scope), run in latest.items():
            if run.job.status != BackgroundJobStatus.FAILED.value:
                continue
            counts = _run_result_counts(run)
            detail = f"{RUNS_URL}&detail={run.job.id}"
            candidates.append(
                AlertCandidate(
                    kind="retrieval.reindex_failed",
                    dedup_key=_dedup("retrieval.reindex_failed", space_id, alert_scope),
                    title=TITLES["retrieval.reindex_failed"],
                    body=(f"A {run.job_type} run for {run.space.name} failed (run {run.job.id})."),
                    payload={
                        "link": detail,
                        "run_id": str(run.job.id),
                        "space_id": str(space_id),
                        "space": run.space.name,
                        "job_type": run.job_type,
                        "scope_kind": run.scope.kind,
                        "status": run.job.status,
                        **counts,
                    },
                    source_ref={"kind": "retrieval_run", "run_id": str(run.job.id)},
                )
            )
        return candidates

    async def _reindex_stalled(self) -> list[AlertCandidate]:
        cutoff = self.now - timedelta(seconds=ops.HEARTBEAT_STALE_SECONDS)
        candidates: list[AlertCandidate] = []
        for run in await self._runs_in_window():
            if run.job.status != BackgroundJobStatus.RUNNING.value:
                continue
            beat = (
                _as_utc(run.job.heartbeat_at)
                or _as_utc(run.job.claimed_at)
                or _as_utc(run.job.created_at)
            )
            if beat is None or beat >= cutoff:
                continue
            detail = f"{RUNS_URL}&detail={run.job.id}"
            candidates.append(
                AlertCandidate(
                    kind="retrieval.reindex_stalled",
                    dedup_key=_dedup("retrieval.reindex_stalled", run.job.id),
                    title=TITLES["retrieval.reindex_stalled"],
                    body=(
                        f"A {run.job_type} run for {run.space.name} has not reported "
                        f"progress for {ops.STALL_MINUTES} minutes (run {run.job.id})."
                    ),
                    payload={
                        "link": detail,
                        "run_id": str(run.job.id),
                        "space_id": str(run.space.id),
                        "space": run.space.name,
                        "job_type": run.job_type,
                        "stage": run.job.stage,
                        "progress": int(run.job.progress or 0),
                        "heartbeat_at": _iso(beat),
                        "stale_minutes": ops.STALL_MINUTES,
                    },
                    source_ref={"kind": "retrieval_run", "run_id": str(run.job.id)},
                )
            )
        return candidates

    async def _quality_gate(self) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for space in await self._live_spaces():
            persisted = await reads._latest_persisted_compare(self.db, space)
            if persisted is None:
                continue
            job, compare = persisted
            if compare.passed:
                continue
            candidates.append(
                AlertCandidate(
                    kind="retrieval.quality_gate",
                    dedup_key=_dedup("retrieval.quality_gate", space.id),
                    title=TITLES["retrieval.quality_gate"],
                    body=(
                        f"The golden-query compare for {space.name} missed the floor "
                        f"(recall {compare.new_recall_at_k:.2f}, "
                        f"precision {compare.new_precision_at_k:.2f})."
                    ),
                    payload={
                        "link": QUALITY_URL,
                        "space_id": str(space.id),
                        "space": space.name,
                        "run_id": str(job.id),
                        "set_version": compare.set_version,
                        "k": compare.k,
                        "recall_at_k": compare.new_recall_at_k,
                        "precision_at_k": compare.new_precision_at_k,
                        "floor_recall": compare.floor_recall,
                        "floor_precision": compare.floor_precision,
                    },
                    source_ref={"kind": "retrieval_quality", "run_id": str(job.id)},
                )
            )
        return candidates

    async def _window_rollups(self) -> list[tuple[VectorSpaceRow, dict[str, Any]]]:
        start = self.now - timedelta(minutes=ops.QUERY_SLO_WINDOW_MINUTES)
        rows: list[tuple[VectorSpaceRow, dict[str, Any]]] = []
        for space in await self._live_spaces():
            rollups = await reads._rollup_rows(
                self.db, start=start, end=self.now, space=space, kind=None
            )
            rows.append((space, reads._rollup_metrics(rollups)))
        return rows

    async def _query_slo(self) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for space, metrics in await self._window_rollups():
            p95 = metrics["p95_ms"]
            if not metrics["query_count"] or p95 is None or p95 <= ops.QUERY_SLO_P95_MS:
                continue
            candidates.append(
                AlertCandidate(
                    kind="retrieval.query_slo",
                    dedup_key=_dedup("retrieval.query_slo", space.id),
                    title=TITLES["retrieval.query_slo"],
                    body=(
                        f"Query p95 for {space.name} is {p95:.0f} ms over the last "
                        f"{ops.QUERY_SLO_WINDOW_MINUTES} minutes "
                        f"(budget {ops.QUERY_SLO_P95_MS} ms)."
                    ),
                    payload={
                        "link": QUERY_HEALTH_URL,
                        "space_id": str(space.id),
                        "space": space.name,
                        "p95_ms": p95,
                        "budget_ms": ops.QUERY_SLO_P95_MS,
                        "window_minutes": ops.QUERY_SLO_WINDOW_MINUTES,
                        "query_count": metrics["query_count"],
                    },
                    source_ref={"kind": "retrieval_space", "space_id": str(space.id)},
                )
            )
        return candidates

    async def _degraded_rate(self) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for space, metrics in await self._window_rollups():
            total = metrics["query_count"]
            if not total:
                continue
            for reason, count in metrics["degraded_reasons"].items():
                rate = count / total
                if rate <= ops.DEGRADED_RATE_THRESHOLD:
                    continue
                candidates.append(
                    AlertCandidate(
                        kind="retrieval.degraded_rate",
                        dedup_key=_dedup("retrieval.degraded_rate", space.id, reason),
                        title=TITLES["retrieval.degraded_rate"],
                        body=(
                            f"{reason} affected {rate:.1%} of queries for {space.name} "
                            f"over the last {ops.DEGRADED_RATE_WINDOW_MINUTES} minutes "
                            f"(threshold {ops.DEGRADED_RATE_THRESHOLD:.0%})."
                        ),
                        payload={
                            "link": QUERY_HEALTH_URL,
                            "space_id": str(space.id),
                            "space": space.name,
                            "reason": reason,
                            "rate": round(rate, 6),
                            "count": count,
                            "query_count": total,
                            "threshold": ops.DEGRADED_RATE_THRESHOLD,
                            "window_minutes": ops.DEGRADED_RATE_WINDOW_MINUTES,
                        },
                        source_ref={"kind": "retrieval_space", "space_id": str(space.id)},
                    )
                )
        return candidates

    async def _provider_unassigned(self) -> list[AlertCandidate]:
        resolved = await resolve_task_model(
            self.db, AITaskType.EMBED.value, None, allow_dev_bootstrap=False
        )
        if resolved is not None:
            return []
        return [
            AlertCandidate(
                kind="retrieval.provider_unassigned",
                dedup_key=_dedup("retrieval.provider_unassigned", "singleton"),
                title=TITLES["retrieval.provider_unassigned"],
                body=(
                    "Semantic indexing cannot run until an embeddings model is assigned "
                    "in Settings → AI Configuration."
                ),
                payload={
                    "link": TOOLS_URL,
                    "slot": AITaskType.EMBED.value,
                    "task_type": AITaskType.EMBED.value,
                    "assigned": False,
                },
                source_ref={"kind": "retrieval_provider", "slot": AITaskType.EMBED.value},
            )
        ]

    async def _index_missing(self) -> list[AlertCandidate]:
        if not _is_postgres(self.db):
            return []
        states: dict[str, tuple[bool, bool]] = {}
        candidates: list[AlertCandidate] = []
        for space in await self._live_spaces():
            if not space.index_table:
                continue
            state = states.get(space.index_table)
            if state is None:
                state = await pg_index_state(self.db, space.index_table)
                states[space.index_table] = state
            extension, table_present = state
            if extension and table_present:
                continue
            candidates.append(
                AlertCandidate(
                    kind="retrieval.index_missing",
                    dedup_key=_dedup("retrieval.index_missing", space.id),
                    title=TITLES["retrieval.index_missing"],
                    body=(
                        f"{space.name} declares index table {space.index_table}, but the "
                        "physical pgvector index is absent."
                    ),
                    payload={
                        "link": TOOLS_URL,
                        "space_id": str(space.id),
                        "space": space.name,
                        "index_table": space.index_table,
                        "extension_present": extension,
                        "table_present": table_present,
                    },
                    source_ref={"kind": "retrieval_space", "space_id": str(space.id)},
                )
            )
        return candidates

    async def _budget_exhausted(self) -> list[AlertCandidate]:
        budgets = list(
            await self.db.scalars(
                select(AIBudget)
                .where(
                    AIBudget.is_active.is_(True),
                    AIBudget.task_type == AITaskType.EMBED.value,
                    AIBudget.user_id.is_(None),
                )
                .order_by(AIBudget.name)
                .limit(20)
            )
        )
        candidates: list[AlertCandidate] = []
        for budget in budgets:
            try:
                start = budget_window_start(budget.window, self.now)
            except ValueError:
                continue
            used = (
                await self.db.execute(
                    select(
                        func.coalesce(func.sum(AIGeneration.tokens_in), 0)
                        + func.coalesce(func.sum(AIGeneration.tokens_out), 0)
                    ).where(
                        AIGeneration.task_type == AITaskType.EMBED.value,
                        AIGeneration.status == "ok",
                        AIGeneration.created_at >= start,
                    )
                )
            ).scalar() or 0
            max_tokens = int(budget.max_tokens or 0)
            if max_tokens <= 0 or int(used) < max_tokens:
                continue
            window_key = _iso(start) or budget.window
            candidates.append(
                AlertCandidate(
                    kind="retrieval.budget_exhausted",
                    dedup_key=_dedup(
                        "retrieval.budget_exhausted", budget.id, budget.window, window_key
                    ),
                    title=TITLES["retrieval.budget_exhausted"],
                    body=(
                        f"The {budget.window} embed budget is exhausted "
                        f"({int(used)}/{max_tokens} tokens)."
                    ),
                    payload={
                        "link": USAGE_URL,
                        "budget_id": str(budget.id),
                        "window": budget.window,
                        "window_start": window_key,
                        "used_tokens": int(used),
                        "max_tokens": max_tokens,
                    },
                    source_ref={"kind": "retrieval_budget", "budget_id": str(budget.id)},
                )
            )
        return candidates

    async def _space_drop_pending(self) -> list[AlertCandidate]:
        cutoff = self.now - timedelta(days=ops.SPACE_DROP_GRACE_DAYS)
        candidates: list[AlertCandidate] = []
        for space in await self._all_spaces():
            if space.status != ops.SpaceStatus.RETIRED.value:
                continue
            retired = _as_utc(space.retired_at)
            if retired is None or retired > cutoff:
                continue
            days = max((self.now - retired).days, 0)
            candidates.append(
                AlertCandidate(
                    kind="retrieval.space_drop_pending",
                    dedup_key=_dedup("retrieval.space_drop_pending", space.id),
                    title=TITLES["retrieval.space_drop_pending"],
                    body=(
                        f"{space.name} was retired {days} days ago and is past the "
                        f"{ops.SPACE_DROP_GRACE_DAYS}-day drop grace."
                    ),
                    payload={
                        "link": TOOLS_URL,
                        "space_id": str(space.id),
                        "space": space.name,
                        "retired_at": _iso(retired),
                        "days_retired": days,
                        "grace_days": ops.SPACE_DROP_GRACE_DAYS,
                    },
                    source_ref={"kind": "retrieval_space", "space_id": str(space.id)},
                )
            )
        return candidates


async def evaluate_retrieval_alerts(
    db: AsyncSession, *, now: datetime | None = None, commit: bool = True
) -> dict[str, Any]:
    """Convenience entry point for the scheduler job handler and tests."""
    return await RetrievalAlertService(db, now=now).evaluate(commit=commit)


__all__ = [
    "ADMIN_FANOUT_LIMIT",
    "ALERT_KINDS",
    "MANAGE_URLS",
    "TITLES",
    "AlertCandidate",
    "RetrievalAlertService",
    "evaluate_retrieval_alerts",
    "pg_index_state",
]
