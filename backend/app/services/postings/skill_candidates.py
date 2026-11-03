"""Deterministic skill-candidate matcher (plan 153 slice 1).

Pass-1 extraction emits taxonomy-blind raw labels; this module proposes
the existing skills each label might belong to before one batched
pass-2 resolver call adjudicates ``match_key | new`` per label. The
pipeline is layered and deterministic: exact ``_taxonomy_index`` hit
(score 1.0, terminal, plan-138 precedence law honored) → trigram
similarity over key/label/aliases → the indexed skill document's cosine
ranking over the same candidate set (plan 50's vector store). Semantic
order is a ranking signal only — missing or failed vectors degrade to the
lexical (trigram) order, never gate which candidates are offered. Deprecated
rows participate as fallback exact matches only (never shadows); proposed +
active rows are full candidates.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.taxonomy_model import Skill
from app.services.catalog.organization_service import trigram_similarity
from app.services.postings.postings_service import _norm, _taxonomy_index_rows


@dataclass(frozen=True)
class Candidate:
    """One proposed (skill, signal) pair for a raw label.

    ``signal`` names the layer that produced ``score``: ``exact``
    (alias/label/key index hit, terminal), ``embedding`` (cosine against
    the stored skill vector) or ``trigram`` (lexical fallback).
    """

    skill_id: UUID
    key: str
    label: str
    status: str
    score: float
    signal: str


def _match_texts(skill: Skill) -> list[str]:
    parts = [skill.key, skill.label, *(str(alias) for alias in skill.aliases or [])]
    return [part for part in parts if part]


async def _semantic_scores(db: AsyncSession, label: str, *, k: int) -> dict[UUID, float]:
    """Cosine scores from the indexed skill documents; empty when degraded.

    The retrieval service owns the provider pre-flight, the query embedding
    and every failure mode, so an unconfigured provider, a missing index or a
    failed call simply leaves the lexical (trigram) order intact.
    """
    from app.services.vector_retrieval_service import VectorRetrievalService

    try:
        result = await VectorRetrievalService(db).search_text(
            label, kind="skill", views=("summary",), limit=max(k * 3, k)
        )
    except Exception:
        return {}
    scores: dict[UUID, float] = {}
    for hit in result.hits:
        if hit.score <= 0.0:
            continue
        try:
            scores[UUID(hit.source_id)] = float(hit.score)
        except (TypeError, ValueError):  # pragma: no cover - non-UUID source ids
            continue
    return scores


async def candidate_skills(
    db: AsyncSession, label: str, *, k: int = 5, active_only: bool = False
) -> list[Candidate]:
    """Top-k existing skills a raw label might resolve to (plan 153).

    Deterministic on every dialect: the candidate pool is ranked by the
    indexed skill document's cosine (plan 50's space) with the trigram score
    as the tiebreak, so absent/degraded vectors leave the lexical order
    intact. An exact index hit is terminal and returns exactly one candidate.
    A label unrelated to the whole taxonomy still yields k lexical candidates
    scored 0.0 — pass 2 adjudicates ``new``; a 0.0 score is "no signal", never
    a weak match.

    ``active_only`` is the auto-promote dedup gate's lane (plan 153 slice 3):
    exact claims and candidates both restrict to active rows, so a proposed
    twin never shadows an active near-duplicate and a contested token can
    only ever block (never silently pick a winner this gate relies on —
    plan-153 §7).
    """
    label = (label or "").strip()
    if not label or k <= 0:
        return []
    rows = list((await db.execute(select(Skill))).scalars().all())
    if active_only:
        rows = [skill for skill in rows if skill.status == "active"]
    by_id = {skill.id: skill for skill in rows}
    exact_id = _taxonomy_index_rows(rows).get(_norm(label))
    if exact_id is not None and exact_id in by_id:
        skill = by_id[exact_id]
        return [
            Candidate(
                skill_id=skill.id,
                key=skill.key,
                label=skill.label,
                status=skill.status,
                score=1.0,
                signal="exact",
            )
        ]

    pool = [skill for skill in rows if skill.status != "deprecated"]
    trigram_scores = {
        skill.id: max(
            (trigram_similarity(label, text) for text in _match_texts(skill)),
            default=0.0,
        )
        for skill in pool
    }
    semantic = await _semantic_scores(db, label, k=max(k, 1))
    cosines = {
        skill_id: score for skill_id, score in semantic.items() if skill_id in trigram_scores
    }

    def rank_key(skill: Skill) -> tuple[float, float, str]:
        return (-cosines.get(skill.id, 0.0), -trigram_scores[skill.id], skill.key)

    candidates: list[Candidate] = []
    for skill in sorted(pool, key=rank_key)[:k]:
        semantic_score = cosines.get(skill.id, 0.0)
        if semantic_score > 0.0:
            candidates.append(
                Candidate(
                    skill_id=skill.id,
                    key=skill.key,
                    label=skill.label,
                    status=skill.status,
                    score=round(semantic_score, 4),
                    signal="embedding",
                )
            )
        else:
            candidates.append(
                Candidate(
                    skill_id=skill.id,
                    key=skill.key,
                    label=skill.label,
                    status=skill.status,
                    score=round(trigram_scores[skill.id], 4),
                    signal="trigram",
                )
            )
    return candidates
