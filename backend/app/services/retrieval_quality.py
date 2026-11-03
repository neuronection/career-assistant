"""Versioned admin-authored golden-query sets (plan 51 Q1a).

The Quality section reads one versioned set per space from a repo-local
fixture — never from user traffic. Query text is lawful **only** in this
fixture; every Retrieval DTO carries query ids, expected/retrieved document
ids and scores, never the input text.

The shipped file is empty by default: a fresh install has no admin-authored
set, so ``/admin/retrieval/quality`` answers ``no_golden_set`` instead of
inventing a score. An operator (or the Q1b compare action's fixture flow)
records sets in the same camelCase shape as the family contract's
``quality.goldenSets`` fixture group. The shape itself is pinned by
``app/storage/retrieval_ops.GoldenQuerySet.from_fixture``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.storage.retrieval_ops import GoldenQuerySet

GOLDEN_QUERY_SET_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "retrieval" / "golden_queries.json"
)


def golden_query_path() -> Path:
    """The runtime golden-query fixture path (packaged with ``app/data``)."""
    return GOLDEN_QUERY_SET_PATH


def load_golden_sets(path: Path | None = None) -> tuple[GoldenQuerySet, ...]:
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
    return tuple(GoldenQuerySet.from_fixture(row) for row in rows)


__all__ = ["GOLDEN_QUERY_SET_PATH", "golden_query_path", "load_golden_sets"]
