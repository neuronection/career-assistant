"""Metric vocabulary kept in code.

The dimension rows and the interest-category anchors are reference data and
arrive through the seed-pack lane (the ``neuronection-reference-banks`` pack);
the six Holland letters stay structural code because the fit engine and the
pack validator both key on them. ``unmapped_categories`` reports taxonomy
categories that have no published anchor row.
"""

from sqlalchemy import select

from app.models.taxonomy_model import InterestTag

RIASEC_LETTERS = (
    "realistic",
    "investigative",
    "artistic",
    "social",
    "enterprising",
    "conventional",
)


async def unmapped_categories(db) -> list[str]:
    """Non-deprecated interest categories with no published anchor row."""
    from app.models.metric_model import MetricCategoryAnchor

    anchored = set(
        (
            await db.execute(
                select(MetricCategoryAnchor.category).where(
                    MetricCategoryAnchor.status == "published"
                )
            )
        )
        .scalars()
        .all()
    )
    rows = await db.execute(
        select(InterestTag.category).where(InterestTag.deprecated.is_(False)).distinct()
    )
    return sorted(category for (category,) in rows.all() if category and category not in anchored)
