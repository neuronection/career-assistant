"""Typed mapping outcome + review overlay (plan 205 AD3).

The matcher's decision is mirrored into closed-vocabulary typed columns on
``job_postings`` (``mapping_outcome_state``/``mapping_outcome_reason``,
``mapping_review_state``/``mapping_review_reason``) so the console can
group/filter without JSONB paths, while ``posting_facts`` keeps the
display/trace projection (confidence, timestamps, policy hash, review
note/actor). The typed columns and the JSONB projection are written in one
transaction by the helpers here; ``catalog_job_id``/``mapping_*`` and the
``mapping_signals``/``mapping_features`` trace stay authoritative — this is
a projection, never a second source of truth.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.posting_model import JobPosting
from app.services.postings.change_journal import (
    RETAG_FIELDS,
    PostingChangeJournal,
    snapshot,
)


class MappingOutcomeState(StrEnum):
    MAPPED = "mapped"
    UNMAPPED = "unmapped"


class MappingOutcomeReason(StrEnum):
    SKILL_OVERLAP = "skill_overlap"
    SEMANTIC = "semantic"
    SEMANTIC_RERANK = "semantic_rerank"
    MANUAL = "manual"
    PROPOSAL = "proposal"
    NO_SKILLS = "no_skills"
    BELOW_THRESHOLD = "below_threshold"
    NO_CANDIDATE = "no_candidate"
    SEMANTIC_UNAVAILABLE = "semantic_unavailable"
    SEMANTIC_PENDING = "semantic_pending"
    UNMAPPED_BY_ADMIN = "unmapped_by_admin"
    UNKNOWN = "unknown"


class MappingReviewReason(StrEnum):
    NO_GOOD_TYPE = "no_good_type"
    MULTI_ROLE = "multi_role"
    NOT_A_JOB = "not_a_job"
    DUPLICATE = "duplicate"
    OTHER = "other"


#: The ``mapping_method`` values that translate 1:1 into an outcome reason.
_METHOD_REASONS = {
    "skill_overlap": MappingOutcomeReason.SKILL_OVERLAP,
    "semantic": MappingOutcomeReason.SEMANTIC,
    "semantic_rerank": MappingOutcomeReason.SEMANTIC_RERANK,
    "manual": MappingOutcomeReason.MANUAL,
    "proposal": MappingOutcomeReason.PROPOSAL,
}

#: The outcome reasons a post-extract matcher decision can end in and still
#: count as accounted for (machine-terminal, AD1).
MACHINE_TERMINAL_REASONS = frozenset(
    {
        MappingOutcomeReason.NO_SKILLS,
        MappingOutcomeReason.BELOW_THRESHOLD,
        MappingOutcomeReason.NO_CANDIDATE,
    }
)


def write_mapping_outcome(
    posting: JobPosting,
    *,
    state: MappingOutcomeState,
    reason: MappingOutcomeReason,
    confidence: float | None = None,
    policy_hash: str | None = None,
) -> None:
    """Mirror one decision into the typed columns + the JSONB projection.

    Same transaction as the caller's decision write; ``flag_modified`` is
    only for the JSONB (the typed columns are tracked attributes).
    """
    posting.mapping_outcome_state = state.value
    posting.mapping_outcome_reason = reason.value
    facts = {**(posting.posting_facts or {})}
    facts["mapping_outcome"] = {
        "confidence": confidence,
        "mapped_at": datetime.now(UTC).isoformat(),
        "policy_hash": policy_hash,
    }
    posting.posting_facts = facts
    flag_modified(posting, "posting_facts")


def write_mapping_review(
    posting: JobPosting,
    *,
    reason: MappingReviewReason,
    note: str,
    actor_id: uuid.UUID | None,
) -> None:
    """Write the human ignore overlay: typed state/reason + the JSONB note."""
    posting.mapping_review_state = "ignored"
    posting.mapping_review_reason = reason.value
    facts = {**(posting.posting_facts or {})}
    facts["mapping_review"] = {
        "note": note,
        "actor": str(actor_id) if actor_id is not None else None,
        "at": datetime.now(UTC).isoformat(),
    }
    posting.posting_facts = facts
    flag_modified(posting, "posting_facts")


def clear_mapping_review(posting: JobPosting) -> None:
    """Clear the overlay (unignore, or an unmap that must not resurrect it)."""
    posting.mapping_review_state = None
    posting.mapping_review_reason = None
    facts = {**(posting.posting_facts or {})}
    facts.pop("mapping_review", None)
    posting.posting_facts = facts
    flag_modified(posting, "posting_facts")


def derive_outcome(posting: JobPosting) -> tuple[MappingOutcomeState, MappingOutcomeReason] | None:
    """Derive the outcome for a legacy row from typed/stored data only.

    Deterministic, no AI, prose-free: the mapping method (or the catalog
    link) decides mapped rows; the ``mapping_signals`` trace decides
    semantic pending/unavailable; everything else lands on ``unknown``
    (the funnel precedence buckets pre-extract/needs-review rows at read
    time regardless of the stored outcome, AD2). Returns ``None`` when the
    row already carries an outcome (idempotence) or has nothing to derive
    from.
    """
    if posting.mapping_outcome_state is not None:
        return None
    if posting.catalog_job_id is not None:
        reason = _METHOD_REASONS.get(posting.mapping_method or "", MappingOutcomeReason.UNKNOWN)
        return (MappingOutcomeState.MAPPED, reason)
    signals = (posting.posting_facts or {}).get("mapping_signals")
    signals = signals if isinstance(signals, dict) else {}
    if signals.get("semantic_pending"):
        return (MappingOutcomeState.UNMAPPED, MappingOutcomeReason.SEMANTIC_PENDING)
    semantic = signals.get("semantic")
    if isinstance(semantic, dict) and semantic.get("degraded"):
        return (MappingOutcomeState.UNMAPPED, MappingOutcomeReason.SEMANTIC_UNAVAILABLE)
    return (MappingOutcomeState.UNMAPPED, MappingOutcomeReason.UNKNOWN)


async def backfill_postings_outcome(
    db: AsyncSession,
    postings: list[JobPosting],
    *,
    actor_ref: dict | None = None,
) -> dict:
    """Write the derived outcome for the given legacy rows in one pass."""
    derived = 0
    for posting in postings:
        outcome = derive_outcome(posting)
        if outcome is None:
            continue
        state, reason = outcome
        before = snapshot(posting, RETAG_FIELDS)
        write_mapping_outcome(posting, state=state, reason=reason)
        PostingChangeJournal.record(
            db,
            posting.id,
            "retag",
            actor_ref=actor_ref or {"trigger": "mapping_outcome_backfill"},
            operation={
                "mapping_outcome_backfill": {
                    "state": state.value,
                    "reason": reason.value,
                }
            },
            before=before,
            after=snapshot(posting, RETAG_FIELDS),
        )
        derived += 1
    return {"derived": derived, "scanned": len(postings)}


__all__ = [
    "MACHINE_TERMINAL_REASONS",
    "MappingOutcomeReason",
    "MappingOutcomeState",
    "MappingReviewReason",
    "backfill_postings_outcome",
    "clear_mapping_review",
    "derive_outcome",
    "write_mapping_outcome",
    "write_mapping_review",
]
