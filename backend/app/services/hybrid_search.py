"""Hybrid retrieval: reciprocal rank fusion of the lexical
relevance ranking with the semantic (embedding cosine) ranking.

Discipline: semantic is a RANKING SIGNAL, never a filter gate — the
candidate set is always the SQL/lexically-filtered one, so a vector hit
can never resurrect a posting the user's hard filters excluded.
"""

from typing import Iterable, Sequence

RRF_K = 60  # standard k: dampens rank-position noise between lists


def rrf_merge(
    ranked_lists: Sequence[Sequence[str]], k: int = RRF_K
) -> dict[str, float]:
    """Reciprocal-rank-fusion scores for one merged ranking.

    score(d) = Σ over lists  1 / (k + position(d) in that list); items
    absent from a list simply don't earn that list's contribution.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for position, item_id in enumerate(ranked, start=1):
            scores[str(item_id)] = scores.get(str(item_id), 0.0) + 1.0 / (k + position)
    return scores


def fused_order(scores: dict[str, float]) -> list[str]:
    """Ids sorted by fused score, ties broken alphabetically (stable)."""
    return sorted(scores, key=lambda item: (-scores[item], item))


def hybrid_candidate_order(
    lexical_ranked: Iterable[str],
    semantic_ranked: Iterable[str],
    k: int = RRF_K,
) -> list[str]:
    """Merge the two rankings; the union keeps lexical-only entries (they
    simply earn no semantic contribution)."""
    return fused_order(rrf_merge([list(lexical_ranked), list(semantic_ranked)], k))
