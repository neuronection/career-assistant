"""Process-local query-embedding cache (plan 201 S6).

The family read-path rule (`guidelines/vector-retrieval.md §6`, item 2):
the query is embedded once per ``(space, prefix role, normalized text)`` and
**cached**. This module is that cache: a bounded, TTL'd, process-local LRU
used only by ``VectorRetrievalService._embed_query``.

Design:

- The key is ``(space_key, query_prefix, sha256(normalized text))`` — a
  digest, never the raw query text, so nothing sensitive is retained in
  memory beyond the request. ``space_key`` already encodes provider/model/
  dim/prefixes/chunker, so a new active space cannot serve stale vectors, and
  the query prefix separates asymmetric-prefix models by role.
- A hit makes no provider call and therefore writes no ``ai_generations`` row
  (the ledger counts calls, and a cache hit is not one).
- Bounded (512 entries) with a 60-minute TTL; both are module constants, not
  config: this is a pure latency optimization with correct-if-stale-free
  semantics (the space key invalidates on any identity change).
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from app.storage.vector_contract import normalize_text

MAX_ENTRIES = 512
TTL_SECONDS = 3600.0

_cache: OrderedDict[tuple[str, str, str], tuple[float, list[float]]] = OrderedDict()
hits = 0
misses = 0


def cache_key(space: Any, text: str) -> tuple[str, str, str]:
    """The cache identity for one query against one space.

    ``space`` is a ``VectorSpace``: the cache reads its ``key`` (the space's
    cutover identity, which already encodes provider/model/dim/prefixes/
    chunker) and its ``query_prefix`` explicitly, so the prefix role is
    separable per the family rule.
    """
    digest = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
    return (str(space.key), str(space.query_prefix or ""), digest)


def get(key: tuple[str, str, str]) -> list[float] | None:
    """The cached query vector, or ``None`` on miss/expiry (records the miss)."""
    global hits, misses
    entry = _cache.get(key)
    if entry is None:
        misses += 1
        return None
    stored_at, vector = entry
    if time.monotonic() - stored_at > TTL_SECONDS:
        _cache.pop(key, None)
        misses += 1
        return None
    _cache.move_to_end(key)
    hits += 1
    return list(vector)


def put(key: tuple[str, str, str], vector: Sequence[float]) -> None:
    """Cache one query vector, evicting the oldest entry past the bound."""
    _cache[key] = (time.monotonic(), [float(value) for value in vector])
    _cache.move_to_end(key)
    while len(_cache) > MAX_ENTRIES:
        _cache.popitem(last=False)


def clear() -> None:
    """Drop every entry (test isolation)."""
    _cache.clear()


def stats() -> tuple[int, int]:
    """``(hits, misses)`` since process start — for tracing spans only."""
    return (hits, misses)


__all__ = [
    "MAX_ENTRIES",
    "TTL_SECONDS",
    "cache_key",
    "clear",
    "get",
    "put",
    "stats",
]
