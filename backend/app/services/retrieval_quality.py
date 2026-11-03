"""Versioned admin-authored golden-query sets and the pre-cutover compare (plan 51).

The Quality section reads one versioned set per space from a repo-local
fixture — never from user traffic. Query text is lawful **only** in this
fixture; every Retrieval DTO carries query ids, expected/retrieved document
ids and scores, never the input text.

Q1b adds the bounded compare used by ``POST /admin/retrieval/quality/compare``
and by the activation gate: the same golden set is run against the active
(old) and candidate (building) space, recall/precision@k and per-query misses
are scored through the family contract, and the outcome is returned as a
``QualityCompareDTO``. A building space is searched by id through the same
retrieval service the live path uses — no second retrieval implementation.

The shipped file is empty by default: a fresh install has no admin-authored
set, so the compare honestly fails (activation requires quality). An operator
records sets in the family contract's camelCase shape; the shape is pinned by
``app/storage/retrieval_ops.GoldenQuerySet.from_fixture``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services.vector_retrieval_service import VectorRetrievalService
from app.storage import retrieval_ops as ops
from app.storage.vector_store import VectorStoreService

GOLDEN_QUERY_SET_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "retrieval" / "golden_queries.json"
)

RetrievedByQuery = Mapping[str, Sequence[str]]
RetrieverFactory = Callable[
    [VectorSpaceRow, ops.GoldenQuerySet],
    Awaitable[tuple[dict[str, list[str]], str | None]],
]


class GoldenSetMissing(ValidationError):
    """No versioned golden-query set exists for the space (quality is required)."""


def golden_query_path() -> Path:
    """The runtime golden-query fixture path (packaged with ``app/data``)."""
    return GOLDEN_QUERY_SET_PATH


def load_golden_sets(path: Path | None = None) -> tuple[ops.GoldenQuerySet, ...]:
    """Load the versioned sets, validating each through the family contract.

    A missing file is an honest empty install (no set). A malformed file
    raises ``ValueError`` — an admin fixture that does not validate must fail
    loudly, never degrade to a fabricated score.
    """
    target = path or GOLDEN_QUERY_SET_PATH
    if not target.is_file():
        return ()
    document = json.loads(target.read_text(encoding="utf-8"))
    rows = document.get("sets") or []
    return tuple(ops.GoldenQuerySet.from_fixture(row) for row in rows)


def select_golden_set(
    space: VectorSpaceRow,
    golden_sets: Sequence[ops.GoldenQuerySet],
) -> ops.GoldenQuerySet | None:
    """The newest set for this space: an exact id beats a name match."""
    exact = [item for item in golden_sets if item.space_id == str(space.id)]
    named = [item for item in golden_sets if item.space_id == space.name]
    candidates = exact or named
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.set_version)


def _iso(value: datetime | None = None) -> str:
    moment = value or datetime.now(UTC)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class QualityCompareOutcome:
    """A compare plus the two spaces' structured degradation states."""

    compare: ops.QualityCompareDTO
    set_version: int
    k: int
    old_degraded: str | None = None
    new_degraded: str | None = None
    no_baseline: bool = False

    @property
    def passed(self) -> bool:
        return bool(self.compare.passed)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "quality": self.compare.to_dict(),
            "set_version": self.set_version,
            "k": self.k,
            "old_degraded": self.old_degraded,
            "new_degraded": self.new_degraded,
            "no_baseline": self.no_baseline,
            "gate": ops.GateStatus.PASS.value if self.passed else ops.GateStatus.FAIL.value,
        }
        return ops.assert_no_raw_text(payload)


async def _retrieve(
    db: AsyncSession,
    space: VectorSpaceRow,
    golden: ops.GoldenQuerySet,
    *,
    store: VectorStoreService | None,
    retriever_factory: RetrieverFactory | None,
) -> tuple[dict[str, list[str]], str | None]:
    """Run the golden queries against one space (by id, active or building)."""
    if retriever_factory is not None:
        return await retriever_factory(space, golden)
    service = VectorRetrievalService(
        db,
        store=store,
        space_name=space.name,
        space_id=str(space.id),
    )
    retrieved: dict[str, list[str]] = {}
    degraded: str | None = None
    for query in golden.queries:
        result = await service.search_text(query.query, limit=golden.k)
        if result.degraded is not None and degraded is None:
            degraded = result.degraded.value
        retrieved[query.query_id] = [hit.document_id for hit in result.hits]
    return retrieved, degraded


async def compare_spaces(
    db: AsyncSession,
    old_space: VectorSpaceRow | None,
    new_space: VectorSpaceRow,
    *,
    golden_sets: Sequence[ops.GoldenQuerySet] | None = None,
    store: VectorStoreService | None = None,
    retriever_factory: RetrieverFactory | None = None,
) -> QualityCompareOutcome:
    """Score the versioned golden set on the old and new space.

    ``old_space=None`` is the first activation: the candidate is scored on its
    own and the compare reports no baseline (the two score columns match).
    Missing golden set raises :class:`GoldenSetMissing`; the caller refuses
    instead of inventing a score. Query text never leaves this function.
    """
    sets = tuple(golden_sets) if golden_sets is not None else load_golden_sets()
    golden = select_golden_set(new_space, sets) or (
        select_golden_set(old_space, sets) if old_space is not None else None
    )
    if golden is None:
        raise GoldenSetMissing(
            f"no versioned golden-query set for space {new_space.name!r}; "
            "quality is required for activation"
        )
    generated_at = _iso()
    new_retrieved, new_degraded = await _retrieve(
        db, new_space, golden, store=store, retriever_factory=retriever_factory
    )
    if old_space is None:
        new_quality = ops.evaluate_quality_set(golden, new_retrieved, generated_at=generated_at)
        compare = ops.QualityCompareDTO(
            old_space_id=str(new_space.id),
            new_space_id=str(new_space.id),
            set_version=golden.set_version,
            k=golden.k,
            old_recall_at_k=new_quality.recall_at_k,
            old_precision_at_k=new_quality.precision_at_k,
            new_recall_at_k=new_quality.recall_at_k,
            new_precision_at_k=new_quality.precision_at_k,
            passed=new_quality.passed,
            floor_recall=new_quality.floor_recall,
            floor_precision=new_quality.floor_precision,
            queries=new_quality.queries,
            generated_at=generated_at,
        )
        outcome = QualityCompareOutcome(
            compare=compare,
            set_version=golden.set_version,
            k=golden.k,
            old_degraded=new_degraded,
            new_degraded=new_degraded,
            no_baseline=True,
        )
        ops.assert_no_raw_text(outcome.to_dict())
        return outcome

    old_retrieved, old_degraded = await _retrieve(
        db, old_space, golden, store=store, retriever_factory=retriever_factory
    )
    compare = ops.evaluate_quality_compare(
        str(old_space.id),
        str(new_space.id),
        golden.set_version,
        golden.queries,
        old_retrieved,
        new_retrieved,
        k=golden.k,
        generated_at=generated_at,
    )
    outcome = QualityCompareOutcome(
        compare=compare,
        set_version=golden.set_version,
        k=golden.k,
        old_degraded=old_degraded,
        new_degraded=new_degraded,
    )
    ops.assert_no_raw_text(outcome.to_dict())
    return outcome


def persisted_compare_payload(
    outcome: QualityCompareOutcome, *, new_space: VectorSpaceRow
) -> dict[str, Any]:
    """The run-result block stored on a ``VECTOR_CUTOVER`` evaluation row."""
    return {
        "space_id": str(new_space.id),
        "quality": outcome.compare.to_dict(),
        "set_version": outcome.set_version,
        "k": outcome.k,
        "old_degraded": outcome.old_degraded,
        "new_degraded": outcome.new_degraded,
        "no_baseline": outcome.no_baseline,
    }


def parse_persisted_compare(payload: Any) -> ops.QualityCompareDTO | None:
    """Rebuild the compare DTO from a stored run result (validated, no text)."""
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("quality")
    if not isinstance(raw, Mapping):
        return None
    try:
        return ops.QualityCompareDTO(**dict(raw))
    except (TypeError, ValueError):
        return None


__all__ = [
    "GOLDEN_QUERY_SET_PATH",
    "GoldenSetMissing",
    "QualityCompareOutcome",
    "compare_spaces",
    "golden_query_path",
    "load_golden_sets",
    "parse_persisted_compare",
    "persisted_compare_payload",
    "select_golden_set",
]
