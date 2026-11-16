"""Deterministic posting-skill gap report (plan 212 S1.1).

One shared computation feeds both surfaces that compare a posting's
extracted skill requirements against the user's levels: the CV tailor
coverage (`cv_suggestion_service._coverage`) and the posting gap report
(`GET /postings/{ref}/gap` + `PostingDetailOut.gap`). The report is
evidence-first and never a score: every row cites the posting's own
words (when its label resolved to a taxonomy key) and the user's
evidence ledger (or nothing). A headline percentage is deliberately
absent — the match score lives on its own card and is not duplicated.

Bounds: the extract caps skills at 40, so every loop here is bounded;
the evidence ledger is read in ONE query for all resolved keys.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.experience_model import SkillEvidence
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill
from app.schemas.posting import (
    GapStatus,
    PostingExtractSkillOut,
    PostingGapEvidenceOut,
    PostingGapOut,
    PostingGapRowOut,
)

PRIORITY_GROUPS = ("must_have", "nice_to_have", "bonus")
USER_EVIDENCE_CAP = 4
EVIDENCE_LABEL_CAP = 120


def gap_status(required_level: int | None, user_level: int | None) -> GapStatus:
    """`met` / `partial` / `missing` on the 1-10 anchored scale.

    No recorded level is `missing`, never a guess. A requirement
    without a usable bar (level 0/None — not producible by the current
    extractor, tolerated for older stored rows) is met by any recorded
    level: presence of the skill is the only honest claim available.
    """
    if user_level is None or user_level <= 0:
        return "missing"
    if required_level is None or required_level <= 0 or user_level >= required_level:
        return "met"
    return "partial"


def build_gap_rows(
    skills: list[PostingExtractSkillOut],
    levels: dict[str, int],
    labels: dict[str, str] | None = None,
    evidence: dict[str, list[PostingGapEvidenceOut]] | None = None,
) -> list[PostingGapRowOut]:
    """One row per extract skill, in extract order — a label that never
    resolved keeps its row (`skill_key`/`label` null, no quote: the
    quote joins on the resolved key) and is never dropped silently."""
    labels = labels or {}
    evidence = evidence or {}
    rows: list[PostingGapRowOut] = []
    for skill in skills:
        key = skill.skill_key or ""
        resolved = bool(key)
        user_level = levels.get(key) if resolved else None
        priority = skill.priority if skill.priority in PRIORITY_GROUPS else "bonus"
        rows.append(
            PostingGapRowOut(
                raw_label=skill.raw_label or key,
                skill_key=skill.skill_key,
                label=labels.get(key) if resolved else None,
                required_level=skill.required_level,
                user_level=user_level,
                status=gap_status(skill.required_level, user_level),
                priority=priority,
                kind="skill",
                evidence_quote=skill.evidence_quote if resolved else "",
                user_evidence=evidence.get(key, []) if resolved else [],
            )
        )
    return rows


def group_gap_rows(rows: list[PostingGapRowOut]) -> PostingGapOut:
    """Group rows into the extractor's closed priority vocabulary."""
    grouped = PostingGapOut()
    buckets: dict[str, list[PostingGapRowOut]] = {
        "must_have": grouped.must_have,
        "nice_to_have": grouped.nice_to_have,
        "bonus": grouped.bonus,
    }
    for row in rows:
        buckets[row.priority].append(row)
    return grouped


async def skill_levels(db: AsyncSession, user_id, skill_keys: list[str]) -> dict[str, int]:
    """The user's levels for the given taxonomy keys — one query,
    `derive_enabled` only (the same population the tailor coverage has
    always read)."""
    if not skill_keys:
        return {}
    rows = await db.execute(
        select(Skill.key, UserSkill.level)
        .join(UserSkill, UserSkill.skill_id == Skill.id)
        .where(
            UserSkill.user_id == user_id,
            UserSkill.derive_enabled,
            Skill.key.in_(skill_keys),
        )
    )
    return dict(rows.all())


async def skill_labels(db: AsyncSession, skill_keys: list[str]) -> dict[str, str]:
    """The taxonomy's display labels for the resolved keys — one query."""
    if not skill_keys:
        return {}
    rows = await db.execute(select(Skill.key, Skill.label).where(Skill.key.in_(skill_keys)))
    return dict(rows.all())


async def user_evidence(
    db: AsyncSession, user_id, skill_keys: list[str]
) -> dict[str, list[PostingGapEvidenceOut]]:
    """Per-key user evidence from the skill evidence ledger — ONE query
    for all keys, capped per key. `self_report` claims have no ledger
    row and stay empty (honestly: "no evidence")."""
    if not skill_keys:
        return {}
    key_rows = await db.execute(select(Skill.id, Skill.key).where(Skill.key.in_(skill_keys)))
    id_to_key = dict(key_rows.all())
    if not id_to_key:
        return {}
    per_skill: dict[str, list[PostingGapEvidenceOut]] = {}
    for skill_id, key in id_to_key.items():
        rows = await db.execute(
            select(SkillEvidence)
            .options(selectinload(SkillEvidence.experience_item))
            .where(
                SkillEvidence.user_id == user_id,
                SkillEvidence.skill_id == skill_id,
            )
            .order_by(SkillEvidence.claimed_at.desc(), SkillEvidence.id)
            .limit(USER_EVIDENCE_CAP)
        )
        for row in rows.scalars().unique():
            if row.experience_item_id is not None:
                ref = PostingGapEvidenceOut(
                    source="experience",
                    label=(row.experience_item.title or "")[:EVIDENCE_LABEL_CAP]
                    if row.experience_item
                    else "",
                )
            elif row.assessment_run_id is not None:
                ref = PostingGapEvidenceOut(source="assessment")
            else:
                ref = PostingGapEvidenceOut(source="cv_document")
            per_skill.setdefault(key, []).append(ref)
    return per_skill


async def build_posting_gap(
    db: AsyncSession, user_id, extract_skills: list[PostingExtractSkillOut]
) -> PostingGapOut:
    """The posting's gap report for one user: levels, labels and
    evidence in one bounded pass each, then the pure grouping."""
    keys = [skill.skill_key for skill in extract_skills if skill.skill_key]
    levels = await skill_levels(db, user_id, keys)
    labels = await skill_labels(db, keys)
    evidence = await user_evidence(db, user_id, keys)
    return group_gap_rows(build_gap_rows(extract_skills, levels, labels, evidence))
