"""Stamp bank pack identity on reference rows after seeding (plan 225 S0).

`0022` backfills rows that existed when it ran, but a fresh install seeds
*after* the migration. Until the banks move to packs (S1-S5) this pass gives
the seeded rows their stored `seed_key` (and creates the category anchors),
so the pack lane can adopt instead of duplicating them.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.assessment_model import AssessmentQuestion
from app.models.assessment_template_model import AssessmentTemplate
from app.models.cv_template_model import CvTemplate
from app.models.metric_model import MetricCategoryAnchor, MetricDimension
from app.models.skill_pack_model import AISkillPack
from app.seeds.bank_keys import QUESTION_KEYS


async def stamp_bank_identities(db) -> int:
    """Idempotently set `seed_key` on seeded bank rows; return the count."""
    from app.seeds.metrics import CATEGORY_RIASEC, DIMENSIONS

    stamped = 0

    for spec in DIMENSIONS:
        row = await db.scalar(
            select(MetricDimension).where(
                MetricDimension.key == spec["key"],
                MetricDimension.seed_key.is_(None),
            )
        )
        if row is not None:
            row.seed_key = f"metric-dimension:{row.key}"
            stamped += 1

    for category, letter in CATEGORY_RIASEC.items():
        anchor = await db.scalar(
            select(MetricCategoryAnchor).where(MetricCategoryAnchor.category == category)
        )
        if anchor is None:
            db.add(
                MetricCategoryAnchor(
                    category=category,
                    letter=letter,
                    status="published",
                    seed_key=f"interest-category:{category}",
                )
            )
            stamped += 1
        elif anchor.seed_key is None:
            anchor.seed_key = f"interest-category:{category}"
            stamped += 1

    for prompt, key in QUESTION_KEYS.items():
        row = await db.scalar(
            select(AssessmentQuestion).where(
                AssessmentQuestion.prompt == prompt,
                AssessmentQuestion.run_id.is_(None),
                AssessmentQuestion.seed_key.is_(None),
            )
        )
        if row is not None:
            row.seed_key = f"assessment-question:{key}"
            stamped += 1

    stamped += await _stamp_versions(db, AssessmentTemplate, "assessment-template")
    stamped += await _stamp_versions(db, CvTemplate, "cv-template")
    stamped += await _stamp_versions(db, AISkillPack, "skill-pack")
    await db.flush()
    return stamped


async def _stamp_versions(db, model, prefix: str) -> int:
    rows = (
        (
            await db.execute(
                select(model).where(model.author_key == "bank", model.seed_key.is_(None))
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.seed_key = f"{prefix}:{row.key}/v{row.version}"
    return len(rows)
