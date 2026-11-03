"""Resumable, budget-capped vector backfill and reconciliation (plan 50 §5.7,
§11, P1d).

One pass per kind classifies source rows against the active space by
composing them (pure, no provider call) and comparing the composed hash to the
stored document's ``source_hash``:

* no document → **missing**;
* a different hash (or ``force``) → **stale**;
* an equal hash → **current**, costing zero embedding calls.

The scan is a **bounded keyset batch**, never the whole corpus: each kind is
read through :func:`~app.services.vector_index_service.list_sources` with an
exclusive ``(updated_at, id)`` cursor and at most ``scan_limit`` rows. Sources
are composed and indexed one at a time; no all-dirty ``work`` list of
``LoadedSource`` objects is held. A run's spend is still capped twice
(``limit`` documents, ``budget`` embed units); when a cap is hit mid-batch the
run stops *before* the next source and returns the cursor of the last fully
processed source, so a continuation resumes without skipping or re-indexing
work.

The ``VECTOR_RECONCILE`` handler chains partial results: it enqueues one
follow-up job with the returned ``after``/``carry``/``completed_kinds`` state
(unless ``auto_continue`` is false). The cursor lives in the job payload and
result, so there is no new table or ledger. A continuation job for the same
``(space, kind, cursor)`` is never duplicated.

Every kind writes one ``retrieval_coverage_snapshots`` row only when its scan
is **complete for the chain** — a partial batch never publishes a misleading
full-coverage point. Counters carried across the chain make a resumed
completion report the whole kind, not just its tail.

**Budget attribution.** The reconcile is system work: the handler passes no
``user_id`` to the gateway, so the embed calls land on the system path
(no per-user limiter, no arbitrary admin budget). An admin-triggered run is a
``background_jobs`` row like any other; the requester is recorded on the job,
never charged.

**No request-time work.** This module is only reached from the
``VECTOR_RECONCILE`` handler (and the CLI that enqueues it).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vector_model import RetrievalCoverageSnapshot
from app.services.vector_index_service import (
    CONTENT_SPACE,
    SourceRow,
    VectorIndexService,
    count_sources,
    list_sources,
    load_source,
)
from app.storage.vector_backends import VectorBackendError, VectorSpaceNotFound
from app.storage.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

RECONCILE_KINDS = ("posting", "job", "profile", "skill")
DEFAULT_LIMIT = 200
DEFAULT_BUDGET = 2000
DEFAULT_BATCH_SIZE = 10
DEFAULT_SCAN_LIMIT = 500
FAILED_IDS_CAP = 25
CARRY_FIELDS = ("seen", "missing", "stale", "failed", "embedded")

ProgressCb = Callable[[int, str], Awaitable[None]]
CancelledCb = Callable[[], Awaitable[bool]]
Cursor = tuple[datetime, str]


@dataclass(frozen=True)
class KindCoverage:
    """One kind's coverage at the moment the pass finished it."""

    kind: str
    total: int = 0
    missing: int = 0
    stale: int = 0
    failed: int = 0
    embedded: int = 0
    as_of: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "total": self.total,
            "missing": self.missing,
            "stale": self.stale,
            "failed": self.failed,
            "embedded": self.embedded,
            "as_of": self.as_of.isoformat(),
        }


@dataclass(frozen=True)
class ReconcileResult:
    """The ``background_jobs.result`` payload of one reconcile run."""

    space: str
    space_id: str | None = None
    kinds: tuple[KindCoverage, ...] = ()
    scanned: int = 0
    embedded: int = 0
    skipped: int = 0
    written: int = 0
    pruned: int = 0
    failed: int = 0
    failed_ids: tuple[str, ...] = ()
    failed_ids_truncated: bool = False
    deferred: int = 0
    orphans_removed: int = 0
    cancelled: bool = False
    budget_exhausted: bool = False
    degraded: str | None = None
    next_after: dict[str, dict[str, str] | None] = field(default_factory=dict)
    carry: dict[str, dict[str, int]] = field(default_factory=dict)
    completed_kinds: tuple[str, ...] = ()
    done: bool = True
    remaining: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "space": self.space,
            "space_id": self.space_id,
            "kinds": [coverage.as_dict() for coverage in self.kinds],
            "scanned": self.scanned,
            "embedded": self.embedded,
            "skipped": self.skipped,
            "written": self.written,
            "pruned": self.pruned,
            "failed": self.failed,
            "failed_ids": list(self.failed_ids),
            "failed_ids_truncated": self.failed_ids_truncated,
            "deferred": self.deferred,
            "orphans_removed": self.orphans_removed,
            "cancelled": self.cancelled,
            "budget_exhausted": self.budget_exhausted,
            "degraded": self.degraded,
            "next_after": {
                kind: (dict(cursor) if cursor is not None else None)
                for kind, cursor in self.next_after.items()
            },
            "carry": {kind: dict(stats) for kind, stats in self.carry.items()},
            "completed_kinds": list(self.completed_kinds),
            "done": self.done,
            "remaining": self.remaining,
        }


class VectorReconcileService:
    """Classify every document against its source and index what drifted."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        store: VectorStoreService | None = None,
        space_name: str = CONTENT_SPACE,
        space_id: str | uuid.UUID | None = None,
        kinds: Sequence[str] | None = None,
        limit: int = DEFAULT_LIMIT,
        budget: int = DEFAULT_BUDGET,
        batch_size: int = DEFAULT_BATCH_SIZE,
        scan_limit: int = DEFAULT_SCAN_LIMIT,
        after: Mapping[str, Any] | None = None,
        carry: Mapping[str, Any] | None = None,
        completed_kinds: Sequence[str] | None = None,
        since: datetime | None = None,
        force: bool = False,
        provision_backend: str | None = None,
        embedder: Any = None,
        run: Any = None,
    ) -> None:
        if store is None:
            from app.core.database import sync_engine

            store = VectorStoreService(sync_engine)
        selected = tuple(kinds) if kinds else RECONCILE_KINDS
        unknown = [kind for kind in selected if kind not in RECONCILE_KINDS]
        if unknown:
            raise ValueError(f"unknown reconcile kind(s): {unknown}")
        self.db = db
        self.store = store
        self.space_name = space_name
        self.space_id = str(space_id) if space_id is not None else None
        self.kinds = selected
        self.limit = max(int(limit), 1)
        self.budget = max(int(budget), 0)
        self.batch_size = max(int(batch_size), 1)
        self.scan_limit = max(int(scan_limit), 1)
        self.since = since
        self.force = force
        self._run = run
        self._after = parse_after(after)
        self._carry = parse_carry(carry)
        self._completed = set(parse_completed_kinds(completed_kinds))
        self._indexer = VectorIndexService(
            db,
            store=store,
            space_name=space_name,
            space_id=space_id,
            embedder=embedder,
            provision_backend=provision_backend,
            run=run,
        )
        self._units = 0

    async def run(
        self,
        *,
        progress: ProgressCb | None = None,
        cancelled: CancelledCb | None = None,
    ) -> ReconcileResult:
        """Classify + index one bounded batch; never raises for a document failure."""
        scanned = embedded = skipped = written = pruned = 0
        failed = deferred = orphans = 0
        failed_ids: list[str] = []
        truncated = withdrew = budget_exhausted = False
        coverages: list[KindCoverage] = []
        degraded: str | None = None
        next_after: dict[str, dict[str, str] | None] = {}
        next_carry: dict[str, dict[str, int]] = {}
        completed = set(self._completed)
        remaining = 0

        population_by_kind = {
            kind: await count_sources(self.db, kind, since=self.since) for kind in self.kinds
        }
        population = sum(population_by_kind.values())
        done_global = sum(
            population_by_kind.get(kind, 0) for kind in self._completed if kind in self.kinds
        ) + sum(
            self._carry.get(kind, {}).get("seen", 0)
            for kind in self.kinds
            if kind not in self._completed
        )

        for kind in self.kinds:
            if kind in completed:
                continue
            state = _empty_carry()
            state.update(self._carry.get(kind, {}))
            cursor = self._after.get(kind)
            sources = await list_sources(
                self.db,
                kind,
                since=self.since,
                after=cursor,
                limit=self.scan_limit,
            )
            hashes = self._stored_hashes(kind, [row.source_id for row in sources])
            kind_total = population_by_kind.get(kind, 0)
            last_processed: SourceRow | None = None
            kind_complete = True

            for row in sources:
                if cancelled is not None and await cancelled():
                    withdrew = True
                    kind_complete = False
                    break
                if embedded >= self.limit or self._units >= self.budget:
                    budget_exhausted = budget_exhausted or self._units >= self.budget
                    kind_complete = False
                    break
                done_global += 1
                await self._report(
                    progress, self._percent(done_global, population), f"scanning {kind}"
                )
                loaded = await load_source(self.db, kind, row.source_id)
                if loaded is None:
                    orphans += await self._drop_orphan(kind, row.source_id)
                    scanned += 1
                    state["seen"] += 1
                    last_processed = row
                    continue
                scanned += 1
                if loaded.composed.is_empty:
                    state["embedded"] += 1
                    state["seen"] += 1
                    last_processed = row
                    continue
                stored = hashes.get(row.source_id)
                if stored == loaded.composed.source_hash and not self.force:
                    state["embedded"] += 1
                    skipped += 1
                    state["seen"] += 1
                    last_processed = row
                    continue
                dirty = "missing" if stored is None else "stale"
                if cancelled is not None and await cancelled():
                    withdrew = True
                    kind_complete = False
                    break
                try:
                    outcome = await self._indexer.index_composed(
                        loaded, kind=kind, source_id=row.source_id, force=self.force
                    )
                except Exception:
                    failed += 1
                    state["failed"] += 1
                    state[dirty] += 1
                    truncated = self._record_failure(failed_ids, kind, row.source_id) or truncated
                    logger.warning(
                        "vector reconcile failed for %s %s", kind, row.source_id, exc_info=True
                    )
                    state["seen"] += 1
                    last_processed = row
                    continue
                if outcome.degraded is not None:
                    degraded = outcome.degraded
                    if outcome.degraded == "provider_unassigned":
                        deferred += 1
                        state[dirty] += 1
                    else:
                        failed += 1
                        state["failed"] += 1
                        state[dirty] += 1
                        truncated = (
                            self._record_failure(failed_ids, kind, row.source_id) or truncated
                        )
                    state["seen"] += 1
                    last_processed = row
                    continue
                state["embedded"] += 1
                state["seen"] += 1
                embedded += 1
                written += outcome.written
                pruned += outcome.pruned
                self._units += outcome.embedded
                last_processed = row
                if embedded % self.batch_size == 0:
                    await self._report(
                        progress,
                        self._percent(done_global, population),
                        f"indexed {embedded} document(s)",
                    )

            if kind_complete and len(sources) >= self.scan_limit:
                kind_complete = False

            if kind_complete:
                coverage = KindCoverage(
                    kind=kind,
                    total=kind_total,
                    missing=state["missing"],
                    stale=state["stale"],
                    failed=state["failed"],
                    embedded=state["embedded"],
                    as_of=datetime.now(UTC),
                )
                await self._write_snapshot(coverage)
                coverages.append(coverage)
                completed.add(kind)
                next_after[kind] = None
                continue

            next_cursor = (
                self._cursor_from_row(last_processed) if last_processed is not None else cursor
            )
            kind_remaining = (
                await count_sources(self.db, kind, since=self.since, after=next_cursor)
                if next_cursor is not None
                else kind_total
            )
            remaining += kind_remaining
            deferred += kind_remaining
            next_after[kind] = self._cursor_dict(next_cursor)
            next_carry[kind] = state
            coverages.append(
                KindCoverage(
                    kind=kind,
                    total=kind_total,
                    missing=state["missing"] + kind_remaining,
                    stale=state["stale"],
                    failed=state["failed"],
                    embedded=state["embedded"],
                    as_of=datetime.now(UTC),
                )
            )
            if withdrew:
                break

        done = all(kind in completed for kind in self.kinds)
        if done and self.since is None:
            for kind in self.kinds:
                orphans += await self._sweep_orphans(kind)
        await self._report(progress, 100, "reconciled" if done else "batch reconciled")
        return ReconcileResult(
            space=self.space_name,
            space_id=self.space_id,
            kinds=tuple(coverages),
            scanned=scanned,
            embedded=embedded,
            skipped=skipped,
            written=written,
            pruned=pruned,
            failed=failed,
            failed_ids=tuple(failed_ids),
            failed_ids_truncated=truncated,
            deferred=deferred,
            orphans_removed=orphans,
            cancelled=withdrew,
            budget_exhausted=budget_exhausted,
            degraded=degraded,
            next_after=next_after,
            carry=next_carry,
            completed_kinds=tuple(kind for kind in self.kinds if kind in completed),
            done=done,
            remaining=remaining,
        )

    # ----------------------------------------------------------- internals

    def _space(self):
        try:
            if self.space_id is not None:
                return self.store.resolve_space(self.space_id)
            return self.store.active_space(self.space_name)
        except (VectorSpaceNotFound, VectorBackendError):
            return None

    def _stored_hashes(self, kind: str, source_ids: Sequence[str]) -> dict[str, str]:
        space = self._space()
        if space is None:
            return {}
        return self.store.document_hashes(space, kind=kind, source_ids=source_ids)

    @staticmethod
    def _cursor_from_row(row: SourceRow | None) -> Cursor | None:
        if row is None or row.updated_at is None:
            return None
        return (row.updated_at, row.source_id)

    @staticmethod
    def _cursor_dict(cursor: Cursor | None) -> dict[str, str] | None:
        if cursor is None:
            return None
        updated, source_id = cursor
        value = (
            updated.astimezone(UTC).isoformat() if isinstance(updated, datetime) else str(updated)
        )
        return {"updated_at": value, "id": str(source_id)}

    async def _sweep_orphans(self, kind: str) -> int:
        """Delete documents whose source no longer resolves, page by page.

        The polymorphic document has no FK to its source, so this is the
        safety net after a hard delete. It only runs after a full pass (never
        on a partial batch), and each page holds at most ``scan_limit``
        documents; the ``after_id`` cursor walks every page so an orphan past
        the first page is still reached. A windowed (``since``) pass never
        sweeps: its source list is not the population.
        """
        space = self._space()
        if space is None:
            return 0
        removed = 0
        after_id: str | None = None
        while True:
            page = list(
                self.store.lookup_documents(
                    space,
                    kind=kind,
                    after_id=after_id,
                    limit=self.scan_limit,
                ).values()
            )
            if not page:
                break
            for info in page:
                if await load_source(self.db, kind, info.source_id) is not None:
                    continue
                removed += 1 if self.store.delete_document(space, info.document_id) else 0
            after_id = page[-1].document_id
            if len(page) < self.scan_limit:
                break
        return removed

    async def _drop_orphan(self, kind: str, source_id: str) -> int:
        """Delete the document of a source row that no longer resolves."""
        space = self._space()
        if space is None:
            return 0
        document_id = self.store.find_document(space, kind=kind, source_id=source_id)
        if document_id is None:
            return 0
        return 1 if self.store.delete_document(space, document_id) else 0

    async def _write_snapshot(self, coverage: KindCoverage) -> None:
        """Commit the coverage point through the store's own session.

        A coverage snapshot is a store fact: writing it beside the documents
        keeps it visible to the sync-engine status reads immediately, and
        never ties it to the caller's request transaction.
        """
        space = self._space()
        if space is None or space.space_id is None:
            return
        with self.store.session_factory() as session:
            session.add(
                RetrievalCoverageSnapshot(
                    id=uuid.uuid4(),
                    space_id=uuid.UUID(str(space.space_id)),
                    kind=coverage.kind,
                    as_of=coverage.as_of,
                    total=coverage.total,
                    missing=coverage.missing,
                    stale=coverage.stale,
                    failed=coverage.failed,
                    embedded=coverage.embedded,
                )
            )
            session.commit()

    @staticmethod
    def _record_failure(failed_ids: list[str], kind: str, source_id: str) -> bool:
        """Append a bounded failure id; True when the list overflowed."""
        if len(failed_ids) < FAILED_IDS_CAP:
            failed_ids.append(f"{kind}:{source_id}")
            return False
        return True

    @staticmethod
    def _percent(done: int, total: int) -> int:
        if total <= 0:
            return 5
        return min(95, max(5, int(95 * done / total)))

    @staticmethod
    async def _report(progress: ProgressCb | None, value: int, stage: str) -> None:
        if progress is not None:
            await progress(value, stage)


def _empty_carry() -> dict[str, int]:
    return dict.fromkeys(CARRY_FIELDS, 0)


def parse_kinds(value: Any) -> tuple[str, ...] | None:
    """Payload ``kinds`` → a validated tuple (``None`` = all supported kinds)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("kinds must be a non-empty list")
    selected = tuple(str(kind) for kind in value)
    unknown = [kind for kind in selected if kind not in RECONCILE_KINDS]
    if unknown:
        raise ValueError(f"unknown reconcile kind(s): {unknown}")
    return selected


def parse_since(value: Any) -> datetime | None:
    """Payload ``since`` → an aware UTC datetime (``None`` = the whole corpus)."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_after(value: Any) -> dict[str, Cursor]:
    """Payload ``after`` → per-kind exclusive ``(updated_at, id)`` cursors.

    The JSON shape is ``{"<kind>": {"updated_at": ISO, "id": UUID}}``. An
    empty/missing map starts every kind at the beginning.
    """
    if value in (None, "", {}):
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("after must be an object keyed by kind")
    cursors: dict[str, Cursor] = {}
    for kind, entry in value.items():
        if kind not in RECONCILE_KINDS:
            raise ValueError(f"unknown reconcile kind in after: {kind}")
        if entry is None:
            continue
        if not isinstance(entry, Mapping):
            raise ValueError(f"after[{kind}] must be an object")
        updated = parse_since(entry.get("updated_at"))
        source_id = entry.get("id")
        if updated is None or source_id in (None, ""):
            raise ValueError(f"after[{kind}] requires updated_at and id")
        cursors[str(kind)] = (updated, str(source_id))
    return cursors


def parse_carry(value: Any) -> dict[str, dict[str, int]]:
    """Payload ``carry`` → cumulative per-kind counters for a chained scan."""
    if value in (None, "", {}):
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("carry must be an object keyed by kind")
    carried: dict[str, dict[str, int]] = {}
    for kind, entry in value.items():
        if kind not in RECONCILE_KINDS:
            raise ValueError(f"unknown reconcile kind in carry: {kind}")
        if not isinstance(entry, Mapping):
            raise ValueError(f"carry[{kind}] must be an object")
        carried[str(kind)] = {name: max(int(entry.get(name) or 0), 0) for name in CARRY_FIELDS}
    return carried


def parse_completed_kinds(value: Any) -> tuple[str, ...]:
    """Payload ``completed_kinds`` → kinds already complete in this chain."""
    if value in (None, "", []):
        return ()
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, (list, tuple)):
        raise ValueError("completed_kinds must be a list")
    completed = tuple(str(kind) for kind in value)
    unknown = [kind for kind in completed if kind not in RECONCILE_KINDS]
    if unknown:
        raise ValueError(f"unknown completed kind(s): {unknown}")
    return completed


__all__ = [
    "CARRY_FIELDS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_BUDGET",
    "DEFAULT_LIMIT",
    "DEFAULT_SCAN_LIMIT",
    "FAILED_IDS_CAP",
    "RECONCILE_KINDS",
    "KindCoverage",
    "ReconcileResult",
    "VectorReconcileService",
    "parse_after",
    "parse_carry",
    "parse_completed_kinds",
    "parse_kinds",
    "parse_since",
]
