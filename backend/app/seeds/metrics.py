"""Metric dimension seeds: the curated registry rows.

Idempotent like every seed (select-then-insert by stable key). The
RIASEC map anchors each seeded taxonomy interest category to exactly one
Holland letter; the mapping is deliberately explicit and total over the
seeded categories so affinity vectors stay stable across re-seeds.
"""

from app.models.metric_model import MetricDimension
from app.models.taxonomy_model import InterestTag
from app.models.enums import MetricGroup
from sqlalchemy import select

RIASEC_LETTERS = (
    "realistic",
    "investigative",
    "artistic",
    "social",
    "enterprising",
    "conventional",
)

DIMENSIONS: list[dict] = [
    *[
        {
            "key": f"interest.{letter}",
            "label": letter.capitalize(),
            "group": MetricGroup.INTEREST.value,
            "description": (
                "Vocational interest affinity (RIASEC) derived from your "
                "interest tags; sharpened by interest batteries."
            ),
            "sources": [
                "profile.interests",
                "assessment.forced_choice",
                "behavior.engagement",
            ],
            "consumers": ["fit.interests", "filter.explore"],
        }
        for letter in RIASEC_LETTERS
    ],
    *[
        {
            "key": f"values.{key}",
            "label": label,
            "group": MetricGroup.VALUE.value,
            "description": (
                "Work value measured against the others via trade-off "
                "items; feeds the values fit dimension once a job-side "
                "signal exists."
            ),
            "sources": ["assessment.tradeoff"],
            "consumers": ["fit.values"],
        }
        for key, label in (
            ("autonomy", "Autonomy"),
            ("security", "Security"),
            ("compensation", "Compensation"),
            ("altruism", "Altruism"),
            ("variety", "Variety"),
            ("work_life_balance", "Work-life balance"),
            ("prestige", "Prestige"),
            ("impact", "Impact"),
        )
    ],
    *[
        {
            "key": f"workstyle.{key}",
            "label": label,
            "group": MetricGroup.WORKSTYLE.value,
            "description": (
                "Work-style preference (1–5 sliders write through as "
                "self_report evidence)."
            ),
            "sources": ["profile.work_preferences"],
            "consumers": ["fit.interests"],
        }
        for key, label in (
            ("teamwork", "Teamwork"),
            ("environment", "Environment"),
            ("structure", "Structure"),
            ("pace", "Pace"),
            ("leadership", "Leadership"),
        )
    ],
]

CATEGORY_RIASEC: dict[str, str] = {
    # Investigative: science, technology, analysis and mathematics.
    "science": "investigative",
    "technology": "investigative",
    "cognitive": "investigative",
    "technical": "investigative",
    # Artistic: visual, performing and creative-making categories.
    "arts": "artistic",
    "creative": "artistic",
    # Social: helping, teaching, care and interpersonal work.
    "people": "social",
    "interpersonal": "social",
    # Enterprising: persuasion, leadership, business and civic life.
    "business": "enterprising",
    "communication": "enterprising",
    "society": "enterprising",
    # Realistic: physical, outdoors and hands-on making.
    "sports": "realistic",
    "physical": "realistic",
    "hands-on": "realistic",
}


def riasec_of_category(category: str | None) -> str | None:
    """The Holland letter for a taxonomy interest category (None if unmapped)."""
    if not category:
        return None
    return CATEGORY_RIASEC.get(str(category).strip())


async def seed_metric_dimensions(db) -> int:
    """Insert missing registry rows (idempotent by key)."""
    added = 0
    for spec in DIMENSIONS:
        exists = (
            (
                await db.execute(
                    select(MetricDimension).where(MetricDimension.key == spec["key"])
                )
            )
            .scalars()
            .first()
        )
        if exists is None:
            db.add(MetricDimension(**spec))
            added += 1
    await db.commit()
    return added


async def unmapped_categories(db) -> list[str]:
    """Seeded interest categories with no RIASEC anchor (registry drift alarm)."""
    rows = await db.execute(
        select(InterestTag.category).where(InterestTag.deprecated.is_(False)).distinct()
    )
    return sorted(
        category
        for (category,) in rows.all()
        if category and riasec_of_category(category) is None
    )


RIASEC_QUESTION_PROMPTS = {
    "realistic": "Rate your interest in hands-on, equipment and outdoors work.",
    "investigative": "Rate your interest in analysing, researching and figuring things out.",
    "artistic": "Rate your interest in creative, expressive and design work.",
    "social": "Rate your interest in teaching, helping and caring for people.",
    "enterprising": "Rate your interest in leading, selling and persuading.",
    "conventional": "Rate your interest in organising data, processes and details.",
}

VALUE_QUESTION_PROMPTS = {
    "autonomy": "How much do you value deciding how you do your work?",
    "security": "How much do you value a stable, predictable position?",
    "compensation": "How much do you value maximising your pay?",
    "altruism": "How much do you value work that helps others?",
    "variety": "How much do you value varied, changing tasks?",
    "work_life_balance": "How much do you value protected time outside work?",
    "prestige": "How much do you value a prestigious title or employer?",
    "impact": "How much do you value visible impact on a mission?",
}


async def seed_metric_templates(db) -> int:
    """Bank assessment batteries for the metric dimensions.

    Two published bank templates — the RIASEC interest battery and the
    work-values battery — so the template library ships with working
    instruments for the registry's interest/value families. Idempotent
    by (author_key='bank', key, version).
    """

    from app.models.assessment_template_model import AssessmentTemplate
    from app.models.enums import (
        TemplateSource,
        TemplateStatus,
        TemplateVisibility,
    )
    from app.schemas.assessment_template import (
        TemplateContent,
        TemplatePhase,
        TemplateQuestion,
    )
    from app.services.assessment_templates import (
        _canonical_hash,
        generate_template_ref,
    )

    batteries = [
        (
            "riasec-interest-battery",
            "RIASEC interest battery",
            "Six self-ratings that map your interests onto the registry's "
            "RIASEC dimensions.",
            [
                (
                    f"interest.{letter}",
                    RIASEC_QUESTION_PROMPTS[letter],
                )
                for letter in RIASEC_LETTERS
            ],
        ),
        (
            "work-values-battery",
            "Work values battery",
            "Eight self-ratings over the registry's work-value dimensions.",
            [
                (f"values.{key}", prompt)
                for key, prompt in VALUE_QUESTION_PROMPTS.items()
            ],
        ),
    ]
    added = 0
    for key, title, description, questions in batteries:
        exists = (
            (
                await db.execute(
                    select(AssessmentTemplate).where(
                        AssessmentTemplate.author_key == "bank",
                        AssessmentTemplate.key == key,
                        AssessmentTemplate.version == 1,
                    )
                )
            )
            .scalars()
            .first()
        )
        if exists is not None:
            continue
        content = TemplateContent(
            phases=[
                TemplatePhase(
                    title=title,
                    questions=[
                        TemplateQuestion(
                            kind="slider",
                            prompt=prompt,
                            dimension_key=dimension_key,
                            numeric_min=1,
                            numeric_max=10,
                            cap=10,
                        )
                        for dimension_key, prompt in questions
                    ],
                )
            ],
        )
        db.add(
            AssessmentTemplate(
                key=key,
                version=1,
                title=title,
                description=description,
                author_user_id=None,
                author_key="bank",
                source=TemplateSource.BANK.value,
                visibility=TemplateVisibility.PRIVATE.value,
                audience_stages=[],
                language="en",
                schema_version=content.schema_version,
                content_hash=_canonical_hash(content.model_dump(mode="json")),
                ref=generate_template_ref(),
                status=TemplateStatus.PUBLISHED.value,
                content=content.model_dump(mode="json"),
            )
        )
        added += 1
    await db.commit()
    return added
