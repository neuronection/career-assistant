"""Progress callback contract and the bounded live-indexing detail (plan 52 T4).

Every background handler reports through one callback shape,
``progress(value, stage)``. Vector jobs pass an optional third argument: a
small counters document written in the *same* ``background_jobs`` UPDATE as
``progress``/``stage`` — never a second per-document write.

The detail is a closed, bounded shape: integers, a phase label and booleans
only. It never carries source ids, document text or arbitrary payloads, so a
leaked progress row cannot expose content. Callers that do not supply a
detail keep the existing two-argument semantics (the column is left alone).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from app.storage.retrieval_ops import RUN_PROGRESS_PHASES

logger = logging.getLogger(__name__)

MAX_PROGRESS_COUNTER = 2_147_483_647
MAX_PROGRESS_PHASE = 40
MAX_PROGRESS_DETAIL_BYTES = 2048

_COUNTER_KEYS = (
    "processed_documents",
    "total_documents",
    "processed_chunks",
    "pending_chunks",
    "embedded_chunks",
    "skipped_chunks",
    "failed_chunks",
    "embedded_documents",
    "skipped_documents",
    "failed_documents",
    "embed_calls",
)
_OPTIONAL_COUNTER_KEYS = ("total_chunks", "tokens")
_FLAG_KEYS = ("chunks_estimated", "tokens_estimated", "exact_tokenizer", "done")

PROGRESS_DETAIL_KEYS = frozenset({"phase", *_COUNTER_KEYS, *_OPTIONAL_COUNTER_KEYS, *_FLAG_KEYS})


class ProgressCb(Protocol):
    """The handler progress seam; the detail is optional for non-vector jobs."""

    async def __call__(
        self, value: int, stage: str, detail: dict[str, Any] | None = None
    ) -> None: ...


def _counter(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(value, MAX_PROGRESS_COUNTER))


def _optional_counter(value: Any) -> int | None:
    if value is None:
        return None
    return _counter(value)


def bound_progress_detail(detail: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Validate and bound a progress detail; ``None`` when it cannot be stored.

    Unknown keys are dropped (never persisted), counters are clamped to a
    non-negative 32-bit-ish range and the phase is a short enum value. The
    encoded document is capped; a caller that trips the cap gets ``None``
    rather than a write amplification bug.
    """
    if detail is None:
        return None
    if not isinstance(detail, Mapping):
        return None
    phase = str(detail.get("phase") or "queued").strip()[:MAX_PROGRESS_PHASE]
    if phase not in RUN_PROGRESS_PHASES:
        phase = "queued"
    bounded: dict[str, Any] = {"phase": phase}
    for key in _COUNTER_KEYS:
        bounded[key] = _counter(detail.get(key, 0))
    for key in _OPTIONAL_COUNTER_KEYS:
        bounded[key] = _optional_counter(detail.get(key))
    for key in _FLAG_KEYS:
        bounded[key] = bool(detail.get(key, False))
    if len(json.dumps(bounded, separators=(",", ":")).encode("utf-8")) > MAX_PROGRESS_DETAIL_BYTES:
        logger.warning("progress detail exceeded %s bytes; dropping it", MAX_PROGRESS_DETAIL_BYTES)
        return None
    return bounded


__all__ = [
    "MAX_PROGRESS_COUNTER",
    "MAX_PROGRESS_DETAIL_BYTES",
    "PROGRESS_DETAIL_KEYS",
    "ProgressCb",
    "bound_progress_detail",
]
