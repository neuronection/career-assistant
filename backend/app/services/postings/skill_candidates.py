"""Deterministic skill-candidate matcher (plan 153 slice 1).

Pass-1 extraction emits taxonomy-blind raw labels; this module proposes
the existing skills each label might belong to before one batched
pass-2 resolver call adjudicates ``match_key | new`` per label. The
pipeline is layered and deterministic: exact ``_taxonomy_index`` hit
(score 1.0, terminal, plan-138 precedence law honored) → trigram
similarity over key/label/aliases → embedding cosine ranking over the
same candidate set. Semantic order is a ranking signal only — missing
or failed vectors degrade to the lexical (trigram) order, never gate
which candidates are offered. Deprecated rows participate as fallback
exact matches only (never shadows); proposed + active rows are full
candidates.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding_model import AIEmbedding
from app.models.taxonomy_model import Skill
from app.services.catalog.organization_service import trigram_similarity
from app.services.embedding_service import KIND_SKILL, cosine
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


async def _query_vector(db: AsyncSession, label: str) -> list[float] | None:
    """Embed the label once; any failure degrades to lexical order."""
    try:
        from app.ai.gateway import embed_texts

        return (await embed_texts(db, [label]))[0]
    except Exception:
        return None


async def candidate_skills(
    db: AsyncSession, label: str, *, k: int = 5, active_only: bool = False
) -> list[Candidate]:
    """Top-k existing skills a raw label might resolve to (plan 153).

    Deterministic on every dialect: the candidate pool is ranked by
    cosine (same-dim stored vectors only) with the trigram score as the
    tiebreak, so absent/degraded vectors leave the lexical order intact.
    An exact index hit is terminal and returns exactly one candidate. A
    label unrelated to the whole taxonomy still yields k lexical
    candidates scored 0.0 — pass 2 adjudicates ``new``; a 0.0 score is
    "no signal", never a weak match.

    ``active_only`` is the auto-promote dedup gate's lane (plan 153
    slice 3): exact claims and candidates both restrict to active rows,
    so a proposed twin never shadows an active near-duplicate and a
    contested token can only ever block (never silently pick a winner
    this gate relies on — plan-153 §7).
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
    embedding_rows = (
        (await db.execute(select(AIEmbedding).where(AIEmbedding.entity_kind == KIND_SKILL)))
        .scalars()
        .all()
    )
    query_vector = await _query_vector(db, label) if embedding_rows else None
    cosines: dict[UUID, float] = {}
    if query_vector:
        stored = {
            row.entity_id: row.vector
            for row in embedding_rows
            if row.dim == len(query_vector) and row.vector
        }
        for skill in pool:
            vector = stored.get(skill.id)
            if vector is not None:
                cosines[skill.id] = cosine(query_vector, vector)

    def rank_key(skill: Skill) -> tuple[float, float, str]:
        return (-cosines.get(skill.id, 0.0), -trigram_scores[skill.id], skill.key)

    candidates: list[Candidate] = []
    for skill in sorted(pool, key=rank_key)[:k]:
        semantic = cosines.get(skill.id, 0.0)
        if semantic > 0.0:
            candidates.append(
                Candidate(
                    skill_id=skill.id,
                    key=skill.key,
                    label=skill.label,
                    status=skill.status,
                    score=round(semantic, 4),
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
