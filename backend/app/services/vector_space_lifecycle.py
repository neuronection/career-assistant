"""Embedding-space lifecycle: build, backfill, activate, retire, drop (plan 50 §3.4/§11, P2c.1).

A space is a versioned embedding configuration. Changing the provider,
model, dimension or prefixes is never an in-place rewrite: provision a
``building`` space beside the active one, backfill it through the ordinary
reconcile writer, pass the coverage gate, then flip the active pointer and
retire the previous space. Readers follow the active pointer, so the cutover
has no downtime.

The physical table is created here (service/CLI/job), never on a request
path. Activation is the one write that changes the pointer: it verifies the
physical index and the latest coverage snapshots for every selected kind,
flips the rows in one transaction, and — only when there was a previous
active space — calls :func:`~app.services.postings.mapping_remap.invalidate_mapping_space`
with that retired space's key. Manual and terminal mappings stay untouched
inside the remap handler.

The HTTP action surface (Runs, dashboards, quality compare, typed-confirm
dialogs) is plan 51; it wraps this service and must not duplicate it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.vector_model import (
    RetrievalCoverageSnapshot,
    VectorDocument,
    VectorRecord,
)
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services.vector_composers import CHUNKER_VERSION, COMPOSER_VERSION
from app.services.vector_reconcile_service import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BUDGET,
    DEFAULT_LIMIT,
    DEFAULT_SCAN_LIMIT,
    RECONCILE_KINDS,
    ReconcileResult,
    VectorReconcileService,
    parse_kinds,
    parse_since,
)
from app.services.vector_status import read_space_statuses
from app.storage.tokenizer_contract import ChunkConfig, TokenizerSpec
from app.storage.vector_contract import (
    BACKEND_LINEAR,
    COVERAGE_GATE,
    METRICS,
    SpaceStatus,
)
from app.storage.vector_provisioning import provision_space, space_status
from app.storage.vector_schema import validate_index_table
from app.storage.vector_store import VectorStoreService, canonical_space

logger = logging.getLogger(__name__)

#: Retired spaces are kept for this long before an explicit drop may remove them.
SPACE_DROP_GRACE = timedelta(days=7)
_QUALITY_GATE = Callable[[Mapping[str, Any]], bool]


class SpaceLifecycleError(RuntimeError):
    """A lifecycle transition was refused."""


class SpaceNotFound(SpaceLifecycleError):
    """No persisted space matches the reference."""


class SpaceStateError(SpaceLifecycleError):
    """The space is in a state that does not allow the requested transition."""


class SpaceCoverageError(SpaceLifecycleError):
    """The building space is not covered well enough to activate."""


@dataclass(frozen=True)
class SpaceBuildResult:
    """The outcome of provisioning one ``building`` space."""

    space_id: str
    name: str
    status: str
    space_key: str
    backend: str
    index_table: str | None
    dim: int
    created: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "space_id": self.space_id,
            "name": self.name,
            "status": self.status,
            "space_key": self.space_key,
            "backend": self.backend,
            "index_table": self.index_table,
            "dim": self.dim,
            "created": self.created,
        }


@dataclass(frozen=True)
class ActivationGate:
    """The evidence activation required and the coverage it measured."""

    coverage_gate: float
    kinds: tuple[str, ...]
    coverage: dict[str, float]
    snapshots: dict[str, dict[str, Any]]
    quality_ok: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "coverage_gate": self.coverage_gate,
            "kinds": list(self.kinds),
            "coverage": dict(self.coverage),
            "snapshots": self.snapshots,
            "quality_ok": self.quality_ok,
        }


@dataclass(frozen=True)
class ActivationResult:
    """One successful (or already-satisfied) activation."""

    space_id: str
    name: str
    space_key: str
    previous_space_id: str | None = None
    previous_space_key: str | None = None
    already_active: bool = False
    gate: ActivationGate | None = None
    remap_job_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "space_id": self.space_id,
            "name": self.name,
            "space_key": self.space_key,
            "previous_space_id": self.previous_space_id,
            "previous_space_key": self.previous_space_key,
            "already_active": self.already_active,
            "gate": self.gate.as_dict() if self.gate is not None else None,
            "remap_job_id": self.remap_job_id,
        }


def _as_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _resolve_row(
    session: Session,
    ref: str | uuid.UUID | VectorSpaceRow,
    *,
    statuses: Sequence[str] | None = None,
    prefer: Sequence[str] | None = None,
) -> VectorSpaceRow:
    """Resolve an id or a name; a name prefers ``prefer`` then the newest row."""
    if isinstance(ref, VectorSpaceRow):
        row = session.get(VectorSpaceRow, ref.id)
        if row is None:
            raise SpaceNotFound(f"vector space {ref.id} has no persisted row")
        return row
    as_uuid = _as_uuid(ref)
    if as_uuid is not None:
        row = session.get(VectorSpaceRow, as_uuid)
        if row is None:
            raise SpaceNotFound(f"vector space {ref!r} has no persisted row")
        if statuses is not None and row.status not in statuses:
            raise SpaceStateError(
                f"space {row.name!r} is {row.status!r}; expected one of {tuple(statuses)}"
            )
        return row
    base = select(VectorSpaceRow).where(VectorSpaceRow.name == str(ref))
    if prefer is not None:
        for status in prefer:
            row = session.scalars(
                base.where(VectorSpaceRow.status == status).order_by(
                    VectorSpaceRow.created_at.desc()
                )
            ).first()
            if row is not None:
                return row
    statement = base.order_by(VectorSpaceRow.created_at.desc())
    if statuses is not None:
        statement = statement.where(VectorSpaceRow.status.in_(tuple(statuses)))
    row = session.scalars(statement).first()
    if row is None:
        suffix = f" with status {tuple(statuses)}" if statuses is not None else ""
        raise SpaceNotFound(f"no vector space named {ref!r}{suffix}")
    return row


def _latest_snapshots(
    session: Session, space_id: uuid.UUID, kinds: Sequence[str]
) -> dict[str, RetrievalCoverageSnapshot]:
    """The latest coverage snapshot per selected kind (oldest→newest wins)."""
    latest: dict[str, RetrievalCoverageSnapshot] = {}
    rows = session.scalars(
        select(RetrievalCoverageSnapshot)
        .where(RetrievalCoverageSnapshot.space_id == space_id)
        .order_by(RetrievalCoverageSnapshot.as_of)
    )
    for row in rows:
        if row.kind in kinds:
            latest[row.kind] = row
    return latest


def _coverage_fraction(snapshot: RetrievalCoverageSnapshot) -> float:
    total = int(snapshot.total or 0)
    if total <= 0:
        return 1.0
    return int(snapshot.embedded or 0) / total


class VectorSpaceLifecycleService:
    """Own the space pointer and its physical tables (off the request path)."""

    def __init__(
        self,
        db: AsyncSession | None,
        *,
        store: VectorStoreService | None = None,
        provision_backend: str | None = None,
        embedder: Any = None,
    ) -> None:
        self.db = db
        if store is None:
            from app.core.database import sync_engine

            store = VectorStoreService(sync_engine)
        self.store = store
        self._provision_backend = provision_backend
        self._embedder = embedder

    # --------------------------------------------------------------- reads

    def list_spaces(self) -> list[dict[str, Any]]:
        """Every persisted space with status, physical health and coverage."""
        with self.store.session_factory() as session:
            return read_space_statuses(session)

    def status(self, ref: str | uuid.UUID) -> dict[str, Any]:
        """One space's status entry (by id or name)."""
        with self.store.session_factory() as session:
            row = _resolve_row(session, ref)
            space_id = str(row.id)
        for entry in self.list_spaces():
            if entry["space_id"] == space_id:
                return entry
        raise SpaceNotFound(f"vector space {ref!r} has no status entry")

    def resolve_space_id(self, ref: str | uuid.UUID) -> str:
        """Resolve a name/id to the persisted space id."""
        with self.store.session_factory() as session:
            return str(_resolve_row(session, ref).id)

    # -------------------------------------------------------------- build

    async def build_space(
        self,
        name: str,
        *,
        provider: str,
        model: str,
        dim: int,
        metric: str = METRICS[0],
        normalize: bool = True,
        query_prefix: str | None = None,
        document_prefix: str | None = None,
        chunker_version: str = CHUNKER_VERSION,
        composer_version: str = COMPOSER_VERSION,
        tokenizer: TokenizerSpec | None = None,
        chunk: ChunkConfig | None = None,
    ) -> SpaceBuildResult:
        """Create a ``building`` space beside the active one and provision it.

        The active row is never touched. A matching building space is reused
        idempotently; a different one is refused until it is retired/dropped.
        Passing ``tokenizer`` **and** ``chunk`` builds a token-aware v2 space
        (``chunker_version='2'`` and the v2 key); omitting both keeps the
        legacy v1 identity.
        """
        self._validate_configuration(
            name=name,
            provider=provider,
            model=model,
            dim=dim,
            metric=metric,
        )
        space = self.store.create_space(
            name=name,
            provider=provider,
            model=model,
            dim=dim,
            normalize=normalize,
            query_prefix=query_prefix,
            document_prefix=document_prefix,
            chunker_version=chunker_version,
            composer_version=composer_version,
            status=SpaceStatus.BUILDING,
            tokenizer=tokenizer,
            chunk=chunk,
        )
        with self.store.session_factory() as session:
            row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
            if row is None:  # pragma: no cover - create_space just wrote it
                raise SpaceLifecycleError(f"space {name!r} vanished after creation")
            provision = provision_space(
                session, row, backend=self._provision_backend or self.store.backend.name
            )
            session.refresh(row)
            canonical = canonical_space(row)
        return SpaceBuildResult(
            space_id=str(row.id),
            name=canonical.name,
            status=canonical.status.value,
            space_key=row.space_key,
            backend=provision.backend,
            index_table=provision.index_table,
            dim=canonical.dim,
            created=provision.created,
        )

    # ----------------------------------------------------------- backfill

    async def backfill_space(
        self,
        space_id: str | uuid.UUID,
        *,
        kinds: Sequence[str] | str | None = None,
        limit: int = DEFAULT_LIMIT,
        budget: int = DEFAULT_BUDGET,
        batch_size: int = DEFAULT_BATCH_SIZE,
        scan_limit: int = DEFAULT_SCAN_LIMIT,
        since: Any = None,
        force: bool = False,
        embedder: Any = None,
    ) -> ReconcileResult:
        """Index source rows into a ``building`` space (never the active one).

        This is the same bounded, resumable writer the reconcile job uses:
        it writes documents/records and coverage snapshots against the
        building space id, so the active space is untouched.
        """
        with self.store.session_factory() as session:
            row = _resolve_row(session, space_id, statuses=(SpaceStatus.BUILDING.value,))
            target_id = str(row.id)
            target_name = row.name
        parsed_kinds = parse_kinds(kinds)
        service = VectorReconcileService(
            self.db,  # type: ignore[arg-type]
            store=self.store,
            space_name=target_name,
            space_id=target_id,
            kinds=parsed_kinds,
            limit=limit,
            budget=budget,
            batch_size=batch_size,
            scan_limit=scan_limit,
            since=parse_since(since),
            force=force,
            provision_backend=self._provision_backend,
            embedder=embedder or self._embedder,
        )
        result = await service.run()
        self._record_backfill_progress(uuid.UUID(target_id), result)
        return result

    def _record_backfill_progress(self, space_id: uuid.UUID, result: ReconcileResult) -> None:
        if not result.kinds:
            return
        total = sum(coverage.total for coverage in result.kinds)
        done = sum(coverage.embedded for coverage in result.kinds)
        with self.store.session_factory() as session:
            row = session.get(VectorSpaceRow, space_id)
            if row is None:
                return
            row.backfill_total = total
            row.backfill_done = done
            session.commit()

    # ---------------------------------------------------------- activate

    async def activate_space(
        self,
        space_id: str | uuid.UUID,
        *,
        coverage_gate: float = COVERAGE_GATE,
        quality_gate: _QUALITY_GATE | None = None,
        kinds: Sequence[str] | str | None = None,
    ) -> ActivationResult:
        """Flip a fully covered ``building`` space to active; retire the old one.

        The physical index and the latest coverage snapshot of every selected
        kind are checked first. The row swap is one transaction (the partial
        unique index backs the one-active-per-name rule). After commit, a
        previous active space's key is passed to the single remap hook.
        """
        if not 0.0 <= float(coverage_gate) <= 1.0:
            raise ValueError("coverage_gate must be between 0 and 1")
        selected = tuple(parse_kinds(kinds) or RECONCILE_KINDS)
        with self.store.session_factory() as session:
            row = _resolve_row(
                session,
                space_id,
                prefer=(SpaceStatus.BUILDING.value, SpaceStatus.ACTIVE.value),
            )
            target_id = row.id
            target_name = row.name
            target_status = row.status
            target_key = row.space_key
            if target_status == SpaceStatus.RETIRED.value:
                raise SpaceStateError(f"space {target_name!r} is retired and cannot be activated")
            if target_status == SpaceStatus.BUILDING.value:
                self._assert_physical(session, row)
                gate = self._assert_coverage(session, row, selected, coverage_gate, quality_gate)
            else:
                gate = None
            if target_status != SpaceStatus.BUILDING.value:
                return ActivationResult(
                    space_id=str(target_id),
                    name=target_name,
                    space_key=target_key,
                    already_active=True,
                    gate=None,
                )

        now = datetime.now(UTC)
        with self.store.session_factory() as session:
            statement = select(VectorSpaceRow).where(VectorSpaceRow.name == target_name)
            if session.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update()
            rows = list(session.scalars(statement))
            target = next((candidate for candidate in rows if candidate.id == target_id), None)
            if target is None:  # pragma: no cover - deleted between the two sessions
                raise SpaceNotFound(f"vector space {target_id} vanished during activation")
            if target.status != SpaceStatus.BUILDING.value:
                return ActivationResult(
                    space_id=str(target.id),
                    name=target.name,
                    space_key=target.space_key,
                    already_active=target.status == SpaceStatus.ACTIVE.value,
                )
            previous = [
                candidate
                for candidate in rows
                if candidate.status == SpaceStatus.ACTIVE.value and candidate.id != target.id
            ]
            previous_keys = [candidate.space_key for candidate in previous]
            previous_ids = [str(candidate.id) for candidate in previous]
            if previous_keys and self.db is None:
                raise SpaceLifecycleError(
                    "activation with a previous active space needs an async session "
                    "for the POSTING_REMAP hook"
                )
            for candidate in previous:
                candidate.status = SpaceStatus.RETIRED.value
                candidate.retired_at = now
            # Flush the retirements before the activation update: the partial
            # unique index allows one active row per name, so the new row
            # cannot become active before the old one leaves.
            if previous:
                session.flush()
            target.status = SpaceStatus.ACTIVE.value
            target.activated_at = now
            target.retired_at = None
            session.commit()
            target_key = target.space_key

        remap_ids: list[str] = []
        for old_key in dict.fromkeys(previous_keys):
            job = await self._invalidate(old_key)
            remap_ids.append(str(job.id))
        return ActivationResult(
            space_id=str(target_id),
            name=target_name,
            space_key=target_key,
            previous_space_id=previous_ids[0] if previous_ids else None,
            previous_space_key=previous_keys[0] if previous_keys else None,
            gate=gate,
            remap_job_id=remap_ids[0] if remap_ids else None,
        )

    async def _invalidate(self, space_key: str) -> Any:
        from app.services.postings.mapping_remap import invalidate_mapping_space

        assert self.db is not None  # guarded by the caller
        return await invalidate_mapping_space(self.db, space_key=space_key)

    def _assert_physical(self, session: Session, row: VectorSpaceRow) -> None:
        physical = space_status(session, row)
        if row.index_table is None:
            if physical.backend != BACKEND_LINEAR:
                raise SpaceStateError(
                    f"space {row.name!r} declares no index table but reports {physical.backend!r}"
                )
            return
        if not physical.table_exists:
            raise SpaceStateError(
                f"space {row.name!r} has no physical index {row.index_table!r}; provision it first"
            )
        if physical.table_dim != row.dim:
            raise SpaceStateError(
                f"index {row.index_table!r} is dim {physical.table_dim}, "
                f"space {row.name!r} needs {row.dim}"
            )
        if not physical.index_present:
            raise SpaceStateError(
                f"index {row.index_table!r} is missing its ANN index; rebuild it before activation"
            )

    def _assert_coverage(
        self,
        session: Session,
        row: VectorSpaceRow,
        kinds: Sequence[str],
        coverage_gate: float,
        quality_gate: _QUALITY_GATE | None,
    ) -> ActivationGate:
        snapshots = _latest_snapshots(session, row.id, kinds)
        missing = [kind for kind in kinds if kind not in snapshots]
        if missing:
            raise SpaceCoverageError(
                f"space {row.name!r} has no coverage snapshot for {missing}; backfill it first"
            )
        coverage = {kind: _coverage_fraction(snapshots[kind]) for kind in kinds}
        below = {kind: value for kind, value in coverage.items() if value < coverage_gate}
        if below:
            detail = ", ".join(f"{kind}={value:.4f}" for kind, value in sorted(below.items()))
            raise SpaceCoverageError(
                f"space {row.name!r} is below the coverage gate {coverage_gate:.4f}: {detail}"
            )
        quality_ok: bool | None = None
        if quality_gate is not None:
            report = {
                "space_id": str(row.id),
                "name": row.name,
                "coverage": coverage,
                "snapshots": {
                    kind: {
                        "as_of": snapshot.as_of.isoformat(),
                        "total": snapshot.total,
                        "embedded": snapshot.embedded,
                        "missing": snapshot.missing,
                        "stale": snapshot.stale,
                        "failed": snapshot.failed,
                        "ann_recall": snapshot.ann_recall,
                    }
                    for kind, snapshot in snapshots.items()
                    if kind in coverage
                },
            }
            quality_ok = bool(quality_gate(report))
            if not quality_ok:
                raise SpaceCoverageError(
                    f"space {row.name!r} failed the quality gate; activation refused"
                )
        return ActivationGate(
            coverage_gate=float(coverage_gate),
            kinds=tuple(kinds),
            coverage=coverage,
            snapshots={
                kind: {
                    "as_of": snapshot.as_of.isoformat(),
                    "total": snapshot.total,
                    "embedded": snapshot.embedded,
                    "missing": snapshot.missing,
                    "stale": snapshot.stale,
                    "failed": snapshot.failed,
                }
                for kind, snapshot in snapshots.items()
                if kind in coverage
            },
            quality_ok=quality_ok,
        )

    # ------------------------------------------------------------ retire

    async def retire_space(self, space_id: str | uuid.UUID) -> dict[str, Any]:
        """Retire a non-active space (a ``building`` or already retired one)."""
        now = datetime.now(UTC)
        with self.store.session_factory() as session:
            row = _resolve_row(
                session,
                space_id,
                prefer=(SpaceStatus.BUILDING.value, SpaceStatus.RETIRED.value),
            )
            if row.status == SpaceStatus.ACTIVE.value:
                raise SpaceStateError(
                    f"space {row.name!r} is active; activate its replacement instead of retiring it"
                )
            if row.status == SpaceStatus.RETIRED.value:
                return self._retired_summary(row)
            row.status = SpaceStatus.RETIRED.value
            row.retired_at = now
            session.commit()
            return self._retired_summary(row)

    @staticmethod
    def _retired_summary(row: VectorSpaceRow) -> dict[str, Any]:
        return {
            "space_id": str(row.id),
            "name": row.name,
            "status": row.status,
            "index_table": row.index_table,
            "retired_at": row.retired_at.isoformat() if row.retired_at is not None else None,
        }

    # -------------------------------------------------------------- drop

    async def drop_space(
        self,
        space_id: str | uuid.UUID,
        *,
        force: bool = False,
        confirm: str | None = None,
        grace: timedelta = SPACE_DROP_GRACE,
    ) -> dict[str, Any]:
        """Drop a retired space's physical table and metadata.

        The active space can never be dropped (even with ``force``); a
        building space must be retired first. Without ``force`` the space
        must have been retired for the grace period. ``force`` still
        requires the typed space name in ``confirm`` — no TTY prompt.
        """
        now = datetime.now(UTC)
        with self.store.session_factory() as session:
            row = _resolve_row(
                session,
                space_id,
                prefer=(SpaceStatus.RETIRED.value, SpaceStatus.BUILDING.value),
            )
            if row.status == SpaceStatus.ACTIVE.value:
                raise SpaceStateError("the active space cannot be dropped; activate a replacement")
            if row.status == SpaceStatus.BUILDING.value:
                raise SpaceStateError(
                    f"space {row.name!r} is still building; retire it before drop"
                )
            if row.status != SpaceStatus.RETIRED.value:
                raise SpaceStateError(
                    f"space {row.name!r} is {row.status!r}; only retired spaces drop"
                )
            if force:
                if confirm != row.name:
                    raise SpaceStateError(
                        f"drop --force requires --confirm {row.name!r} (the typed space name)"
                    )
            else:
                if row.retired_at is None:
                    raise SpaceStateError(
                        f"space {row.name!r} has no retirement timestamp; use --force --confirm"
                    )
                age = now - row.retired_at
                if age < grace:
                    remaining = grace - age
                    raise SpaceStateError(
                        f"space {row.name!r} is within its {grace.days}-day grace period "
                        f"({remaining.days}d {remaining.seconds // 3600}h left); "
                        "use --force --confirm to drop now"
                    )
            dropped_id = str(row.id)
            dropped_name = row.name
            table = row.index_table
            if table is not None:
                validate_index_table(table)
            dialect = session.get_bind().dialect.name
            if table is not None:
                if dialect == "sqlite":
                    session.execute(
                        text(
                            "DELETE FROM vector_entry_ids WHERE record_id IN "
                            "(SELECT id FROM vector_records WHERE space_id = :space_id)"
                        ),
                        {"space_id": str(row.id)},
                    )
                suffix = " CASCADE" if dialect == "postgresql" else ""
                session.execute(text(f"DROP TABLE IF EXISTS {table}{suffix}"))
            session.execute(delete(VectorRecord).where(VectorRecord.space_id == row.id))
            session.execute(delete(VectorDocument).where(VectorDocument.space_id == row.id))
            session.execute(delete(VectorSpaceRow).where(VectorSpaceRow.id == row.id))
            session.commit()
        logger.info("dropped retired vector space %s (%s)", dropped_id, table)
        return {
            "space_id": dropped_id,
            "name": dropped_name,
            "dropped": True,
            "index_table": table,
        }

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _validate_configuration(
        *,
        name: str,
        provider: str,
        model: str,
        dim: int,
        metric: str,
    ) -> None:
        if not name or len(name) > 40:
            raise ValueError("space name must be 1-40 characters")
        if not provider or not model:
            raise ValueError("provider and model are required")
        if int(dim) < 1:
            raise ValueError("dim must be positive")
        if metric not in METRICS:
            raise ValueError(f"unsupported metric {metric!r}; expected one of {METRICS}")


__all__ = [
    "SPACE_DROP_GRACE",
    "ActivationGate",
    "ActivationResult",
    "SpaceBuildResult",
    "SpaceCoverageError",
    "SpaceLifecycleError",
    "SpaceNotFound",
    "SpaceStateError",
    "VectorSpaceLifecycleService",
]
