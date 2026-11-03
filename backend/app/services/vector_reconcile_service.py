"""Resumable, budget-capped vector backfill and reconciliation (plan 50 §5.7,
§11, P1d).

One pass per kind classifies every source row against the active space by
composing it (pure, no provider call) and comparing the composed hash to the
stored document's ``source_hash``:

* no document → **missing**;
* a different hash (or ``force``) → **stale**;
* an equal hash → **current**, costing zero embedding calls.

The documents that need work are then indexed through
:class:`~app.services.vector_index_service.VectorIndexService` — the same
writer the ``VECTOR_INDEX`` job uses, so there is no second write path. A
run's embedding spend is capped twice (``limit`` documents, ``budget`` embed
units); whatever the caps defer is still missing/stale on the next run, which
is what makes the pass resumable without a fragile cursor: a rerun of
unchanged content embeds nothing and only picks up the remainder.

Every pass writes one ``retrieval_coverage_snapshots`` row per kind — the
P1d read model the admin status surface consumes (plan 51 owns the dashboards
built on them).

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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vector_model import RetrievalCoverageSnapshot
from app.services.vector_index_service import (
    CONTENT_SPACE,
    LoadedSource,
    SourceRow,
    VectorIndexService,
    count_sources,
    list_sources,
    load_source,
)
from app.storage.vector_backends import VectorBackendError, VectorSpaceNotFound
from app.storage.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

RECONCILE_KINDS = ("posting", "profile", "skill")
DEFAULT_LIMIT = 200
DEFAULT_BUDGET = 2000
DEFAULT_BATCH_SIZE = 10
FAILED_IDS_CAP = 25

ProgressCb = Callable[[int, str], Awaitable[None]]
CancelledCb = Callable[[], Awaitable[bool]]


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "space": self.space,
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
        }


@dataclass
class _Work:
    """One source that needs indexing, with the bucket it started in."""

    row: SourceRow
    loaded: LoadedSource
    state: str


class VectorReconcileService:
    """Classify every document against its source and index what drifted."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        store: VectorStoreService | None = None,
        space_name: str = CONTENT_SPACE,
        kinds: Sequence[str] | None = None,
        limit: int = DEFAULT_LIMIT,
        budget: int = DEFAULT_BUDGET,
        batch_size: int = DEFAULT_BATCH_SIZE,
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
        self.kinds = selected
        self.limit = max(int(limit), 1)
        self.budget = max(int(budget), 0)
        self.batch_size = max(int(batch_size), 1)
        self.since = since
        self.force = force
        self._run = run
        self._indexer = VectorIndexService(
            db,
            store=store,
            space_name=space_name,
            embedder=embedder,
            provision_backend=provision_backend,
            run=run,
        )
        self._units = 0
        self._hashes: dict[str, dict[str, str]] | None = None

    async def run(
        self,
        *,
        progress: ProgressCb | None = None,
        cancelled: CancelledCb | None = None,
    ) -> ReconcileResult:
        """Classify + index one pass; never raises for a per-document failure."""
        scanned = embedded = skipped = written = pruned = 0
        failed = deferred = orphans = 0
        failed_ids: list[str] = []
        truncated = withdrew = budget_exhausted = False
        coverages: list[KindCoverage] = []
        degraded: str | None = None
        population = sum(
            [await count_sources(self.db, kind, since=self.since) for kind in self.kinds]
        )
        done = 0
        for kind in self.kinds:
            sources = await list_sources(self.db, kind, since=self.since)
            current = kind_failed = 0
            work: list[_Work] = []
            for row in sources:
                done += 1
                await self._report(progress, self._percent(done, population), f"scanning {kind}")
                if cancelled is not None and await cancelled():
                    withdrew = True
                    break
                loaded = await load_source(self.db, kind, row.source_id)
                if loaded is None:
                    orphans += await self._drop_orphan(kind, row.source_id)
                    scanned += 1
                    continue
                scanned += 1
                if loaded.composed.is_empty:
                    current += 1
                    continue
                stored = self._stored_hash(kind, row.source_id)
                if stored == loaded.composed.source_hash and not self.force:
                    current += 1
                    skipped += 1
                    continue
                work.append(
                    _Work(row=row, loaded=loaded, state="missing" if stored is None else "stale")
                )
            for item in work:
                if withdrew or embedded >= self.limit or self._units >= self.budget:
                    budget_exhausted = budget_exhausted or self._units >= self.budget
                    deferred += 1
                    continue
                if cancelled is not None and await cancelled():
                    withdrew = True
                    deferred += 1
                    continue
                try:
                    outcome = await self._indexer.index_composed(
                        item.loaded, kind=kind, source_id=item.row.source_id, force=self.force
                    )
                except Exception:
                    failed += 1
                    kind_failed += 1
                    truncated = (
                        self._record_failure(failed_ids, kind, item.row.source_id) or truncated
                    )
                    logger.warning(
                        "vector reconcile failed for %s %s", kind, item.row.source_id, exc_info=True
                    )
                    continue
                if outcome.degraded is not None:
                    degraded = outcome.degraded
                    if outcome.degraded == "provider_unassigned":
                        deferred += 1
                    else:
                        failed += 1
                        kind_failed += 1
                        truncated = (
                            self._record_failure(failed_ids, kind, item.row.source_id) or truncated
                        )
                    continue
                item.state = "indexed"
                current += 1
                embedded += 1
                written += outcome.written
                pruned += outcome.pruned
                self._units += outcome.embedded
                if embedded % self.batch_size == 0:
                    await self._report(
                        progress,
                        self._percent(done, population),
                        f"indexed {embedded} document(s)",
                    )
            dirty = {"missing": 0, "stale": 0}
            for item in work:
                if item.state in dirty:
                    dirty[item.state] += 1
            if self.since is None:
                orphans += await self._sweep_orphans(kind, {row.source_id for row in sources})
            coverage = KindCoverage(
                kind=kind,
                total=len(sources),
                missing=dirty["missing"],
                stale=dirty["stale"],
                failed=kind_failed,
                embedded=current,
                as_of=datetime.now(UTC),
            )
            await self._write_snapshot(coverage)
            coverages.append(coverage)
            if withdrew:
                break
        await self._report(progress, 100, "reconciled")
        return ReconcileResult(
            space=self.space_name,
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
        )

    # ----------------------------------------------------------- internals

    def _space(self):
        try:
            return self.store.active_space(self.space_name)
        except (VectorSpaceNotFound, VectorBackendError):
            return None

    def _stored_hash(self, kind: str, source_id: str) -> str | None:
        space = self._space()
        if space is None:
            return None
        if self._hashes is None:
            self._hashes = {
                kind_name: self.store.document_hashes(space, kind=kind_name)
                for kind_name in self.kinds
            }
        return self._hashes.get(kind, {}).get(str(source_id))

    async def _sweep_orphans(self, kind: str, known: set[str]) -> int:
        """Delete documents whose source no longer resolves (bounded sweep).

        The polymorphic document has no FK to its source, so this is the
        safety net after a hard delete. A windowed (``since``) pass never
        sweeps: its source list is not the population.
        """
        space = self._space()
        if space is None:
            return 0
        removed = 0
        for info in self.store.lookup_documents(space, kind=kind).values():
            if info.source_id in known:
                continue
            if await load_source(self.db, kind, info.source_id) is not None:
                continue
            removed += 1 if self.store.delete_document(space, info.document_id) else 0
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


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_BUDGET",
    "DEFAULT_LIMIT",
    "FAILED_IDS_CAP",
    "RECONCILE_KINDS",
    "KindCoverage",
    "ReconcileResult",
    "VectorReconcileService",
    "parse_kinds",
    "parse_since",
]
