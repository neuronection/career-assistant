"""The editable mapping policy (plan 205 AD8/S8).

``app_settings["catalog.mapping_policy"]`` holds the four decision
thresholds (``tau_job``, ``delta``, ``semantic_threshold``,
``semantic_min_shared_skills``); the blend weights and the candidate cap
stay fixed. A missing or partial row means the shipped defaults — the
defaults are BIT-IDENTICAL to the previous constants. Every decision
records the effective policy hash in its trace; the dry-run reports what
a change WOULD do inside a savepoint and rolls it back.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.posting_model import JobPosting, PostingSkill
from app.models.settings_model import AppSetting

POLICY_KEY = "catalog.mapping_policy"

#: The shipped defaults — BIT-IDENTICAL to the previous module constants
#: (``postings_service.AUTO_MAP_THRESHOLD``, ``semantic_rerank.RERANK_MARGIN``,
#: ``semantic_rescue.SEMANTIC_MAP_THRESHOLD``/``SEMANTIC_MIN_SHARED_SKILLS``).
#: The parity test in tests/test_mapping_console.py pins the equality so the
#: two homes can never drift.
DEFAULT_TAU_JOB = 0.34
DEFAULT_DELTA = 0.08
DEFAULT_SEMANTIC_THRESHOLD = 0.6
DEFAULT_SEMANTIC_MIN_SHARED_SKILLS = 1

#: Fixed by design (AD8): the blend weights and candidate cap are read-only.
BLEND_DETERMINISTIC = 0.75
BLEND_SEMANTIC = 0.25
CANDIDATE_K = 25


@dataclass(frozen=True)
class MappingPolicy:
    """The four editable decision thresholds (AD8)."""

    tau_job: float = DEFAULT_TAU_JOB
    delta: float = DEFAULT_DELTA
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    semantic_min_shared_skills: int = DEFAULT_SEMANTIC_MIN_SHARED_SKILLS

    @property
    def hash(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def with_overrides(self, values: dict[str, Any]) -> MappingPolicy:
        fields = {}
        for key in ("tau_job", "delta", "semantic_threshold", "semantic_min_shared_skills"):
            if key in values and values[key] is not None:
                fields[key] = values[key]
        return replace(self, **fields)


def _validate(values: dict[str, Any]) -> list[str]:
    problems = []
    for key in ("tau_job", "delta", "semantic_threshold"):
        value = values.get(key)
        if value is not None and not (0.0 <= float(value) <= 1.0):
            problems.append(f"{key} must be between 0 and 1")
    shared = values.get("semantic_min_shared_skills")
    if shared is not None and int(shared) < 1:
        problems.append("semantic_min_shared_skills must be at least 1")
    return problems


async def load_mapping_policy(db: AsyncSession) -> MappingPolicy:
    """The effective policy: shipped defaults, overridden per-field by the
    stored row (a missing/partial row changes nothing — bit-identical)."""
    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == POLICY_KEY))).scalars().first()
    )
    if row is None:
        return MappingPolicy()
    value = row.value if isinstance(row.value, dict) else {}
    return MappingPolicy().with_overrides(value)


async def save_mapping_policy(db: AsyncSession, values: dict[str, Any]) -> MappingPolicy:
    """Upsert the stored policy (validated); returns the effective result."""
    problems = _validate(values)
    if problems:
        raise ValidationError("; ".join(problems))
    policy = (await load_mapping_policy(db)).with_overrides(values)
    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == POLICY_KEY))).scalars().first()
    )
    if row is None:
        db.add(AppSetting(key=POLICY_KEY, value=asdict(policy)))
    else:
        row.value = asdict(policy)
    await db.flush()
    return policy


async def dry_run_policy(
    db: AsyncSession,
    posting_ids: list[Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    """Run the candidate policy over ≤50 postings WITHOUT persisting (AD8).

    No embed/index (both semantic stages skip ``_ensure_posting_indexed``),
    no deferred enqueue, no commit. The affected rows' prior state is
    captured and RESTORED in place after the decisions (explicit restore —
    uniform on both dialects; SQLite's savepoint semantics proved
    unreliable under the decision path), then the identity map is expired
    so the mutated ORM objects are never reused.
    """
    from app.services.postings.mapping_outcome import MappingOutcomeState
    from app.services.postings.postings_service import decide_catalog

    problems = _validate(values)
    if problems:
        raise ValidationError("; ".join(problems))
    if len(posting_ids) > 50:
        raise ValidationError("a dry-run covers at most 50 postings")
    base_policy = await load_mapping_policy(db)
    candidate = base_policy.with_overrides(values)

    rows = (
        (
            await db.execute(
                select(JobPosting).where(
                    JobPosting.id.in_(posting_ids),
                    JobPosting.status.in_(("new", "mapped")),
                )
            )
        )
        .scalars()
        .all()
    )
    results: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    degraded = False
    for posting in rows:
        skill_rows = (
            (
                await db.execute(
                    select(PostingSkill.skill_id).where(PostingSkill.posting_id == posting.id)
                )
            )
            .scalars()
            .all()
        )
        skill_ids = set(skill_rows)
        before = {
            "status": posting.status,
            "catalog_job_id": posting.catalog_job_id,
            "mapping_method": posting.mapping_method,
            "mapping_confidence": posting.mapping_confidence,
            "mapping_reason": posting.mapping_reason,
            "mapping_version": posting.mapping_version,
            "mapping_outcome_state": posting.mapping_outcome_state,
            "mapping_outcome_reason": posting.mapping_outcome_reason,
            "needs_review": posting.needs_review,
            "features": posting.mapping_features,
            "facts": posting.posting_facts,
        }
        snapshots.append({"posting": posting, "before": before})
        mapped = await decide_catalog(
            db,
            posting,
            skill_ids,
            policy=candidate,
            defer_semantic=False,
            skip_semantic_indexing=True,
        )
        after_state = (
            MappingOutcomeState.MAPPED.value
            if mapped is not None
            else MappingOutcomeState.UNMAPPED.value
        )
        signals = (posting.posting_facts or {}).get("mapping_signals") or {}
        semantic = signals.get("semantic") or {}
        rerank = signals.get("rerank") or {}
        degraded = degraded or bool(semantic.get("degraded")) or bool(rerank.get("degraded"))
        results.append(
            {
                "posting_id": str(posting.id),
                "before": {
                    "state": before["mapping_outcome_state"],
                    "reason": before["mapping_outcome_reason"],
                },
                "after": {
                    "state": after_state,
                    "reason": posting.mapping_outcome_reason,
                    "confidence": posting.mapping_confidence,
                    "catalog_job_id": str(posting.catalog_job_id)
                    if posting.catalog_job_id
                    else None,
                },
                "changed": before["catalog_job_id"] != posting.catalog_job_id
                or before["mapping_outcome_reason"] != posting.mapping_outcome_reason,
            }
        )

    # Restore the pre-run state in place: the request session never
    # commits, but an explicit restore keeps both dialects honest even if
    # a callee flushes or commits.
    from sqlalchemy.orm.attributes import flag_modified

    for entry in snapshots:
        restored: JobPosting = entry["posting"]
        before = entry["before"]
        restored.status = before["status"]
        restored.catalog_job_id = before["catalog_job_id"]
        restored.mapping_method = before["mapping_method"]
        restored.mapping_confidence = before["mapping_confidence"]
        restored.mapping_reason = before["mapping_reason"]
        restored.mapping_version = before["mapping_version"]
        restored.mapping_outcome_state = before["mapping_outcome_state"]
        restored.mapping_outcome_reason = before["mapping_outcome_reason"]
        restored.needs_review = before["needs_review"]
        restored.mapping_features = before["features"]
        flag_modified(restored, "mapping_features")
        restored.posting_facts = before["facts"]
        flag_modified(restored, "posting_facts")
    await db.flush()
    db.expire_all()
    return {
        "policy": asdict(candidate),
        "policy_hash": candidate.hash,
        "degraded_semantic": degraded,
        "results": results,
        "scanned": len(results),
    }


__all__ = [
    "BLEND_DETERMINISTIC",
    "BLEND_SEMANTIC",
    "CANDIDATE_K",
    "POLICY_KEY",
    "MappingPolicy",
    "dry_run_policy",
    "load_mapping_policy",
    "save_mapping_policy",
]
