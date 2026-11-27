"""Bank pack identity and metric anchors (plan 225 S0).

Adds the stored `seed_key` identity to the five remaining seeded banks
(assessment questions, assessment templates, CV templates, metric
dimensions, skill packs), a `status` on metric dimensions and the new
`metric_category_anchors` table that turns the RIASEC category map into
data. Backfills are self-contained literals: migrations never import
`app.seeds.*` because plan 225 S5 deletes those modules, and a revision
must stay runnable against the code of any later checkout. Existing rows
are matched by key, category or exact prompt; unmatched/edited rows stay
NULL and are never adopted.

Downgrade drops the new table, the partial indexes and columns, and resets
the metric-dimension status.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-27
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_KEY_TABLES = (
    "assessment_questions",
    "assessment_templates",
    "cv_templates",
    "metric_dimensions",
    "ai_skill_packs",
)

DIMENSION_KEYS = (
    "interest.realistic",
    "interest.investigative",
    "interest.artistic",
    "interest.social",
    "interest.enterprising",
    "interest.conventional",
    "values.autonomy",
    "values.security",
    "values.compensation",
    "values.altruism",
    "values.variety",
    "values.work_life_balance",
    "values.prestige",
    "values.impact",
    "workstyle.teamwork",
    "workstyle.environment",
    "workstyle.structure",
    "workstyle.pace",
    "workstyle.leadership",
)

CATEGORY_ANCHORS = (
    ("science", "investigative"),
    ("technology", "investigative"),
    ("cognitive", "investigative"),
    ("technical", "investigative"),
    ("arts", "artistic"),
    ("creative", "artistic"),
    ("people", "social"),
    ("interpersonal", "social"),
    ("business", "enterprising"),
    ("communication", "enterprising"),
    ("society", "enterprising"),
    ("sports", "realistic"),
    ("physical", "realistic"),
    ("hands-on", "realistic"),
)

QUESTION_KEYS = (
    (
        "A friend asks you to help organize a big local charity event. "
        "Which role do you quietly hope for?",
        "charity-event-role",
    ),
    (
        "Your class gets a free-form project month. Which project pulls you in first?",
        "free-form-project",
    ),
    (
        "Something breaks on a group trip and everyone looks at each other. "
        "What happens next, realistically?",
        "group-trip-breakdown",
    ),
    (
        "A company offers you a Saturday shadowing one of its teams. Which team do you pick?",
        "saturday-shadowing",
    ),
    (
        "A week in your dream job — how would the tasks split?",
        "dream-job-week",
    ),
    (
        "You get a free learning year, split across these tracks:",
        "learning-year-tracks",
    ),
    (
        "Rank these workday realities from 'sounds great' to 'no thanks'.",
        "workday-realities-ranking",
    ),
    (
        "Which compliments would you actually want to earn?",
        "wanted-compliments",
    ),
)

ASSESSMENT_TEMPLATE_KEYS = (
    ("riasec-interest-battery", 1),
    ("work-values-battery", 1),
)

CV_TEMPLATE_KEYS = (
    ("ats-classic", 2),
    ("ats-classic-work-projects", 2),
    ("modern-two-column", 4),
    ("compact-onepage", 3),
    ("academic", 3),
    ("student-first", 3),
    ("navy-sidebar", 4),
    ("teal-sidebar", 4),
    ("coral-banner", 2),
    ("charcoal-amber", 2),
)

SKILL_PACK_KEYS = (
    ("interview-prep-style", 1),
    ("cover-letter-voice", 1),
    ("autopilot-curation-rubric", 1),
)


def _index_name(table: str) -> str:
    return f"uq_{table}_seed_key"


def _backfill_dimensions(bind: sa.Connection) -> None:
    for key in DIMENSION_KEYS:
        bind.execute(
            sa.text(
                "UPDATE metric_dimensions SET seed_key = :seed_key "
                "WHERE key = :key AND seed_key IS NULL"
            ),
            {"seed_key": f"metric-dimension:{key}", "key": key},
        )


def _backfill_anchors(bind: sa.Connection) -> None:
    anchors = sa.table(
        "metric_category_anchors",
        sa.column("id", sa.Uuid()),
        sa.column("category", sa.String()),
        sa.column("letter", sa.String()),
        sa.column("status", sa.String()),
        sa.column("seed_key", sa.String()),
    )
    op.bulk_insert(
        anchors,
        [
            {
                "id": uuid.uuid4(),
                "category": category,
                "letter": letter,
                "status": "published",
                "seed_key": f"interest-category:{category}",
            }
            for category, letter in CATEGORY_ANCHORS
        ],
    )


def _backfill_questions(bind: sa.Connection) -> None:
    for prompt, key in QUESTION_KEYS:
        bind.execute(
            sa.text(
                "UPDATE assessment_questions SET seed_key = :seed_key "
                "WHERE prompt = :prompt AND run_id IS NULL AND seed_key IS NULL"
            ),
            {"seed_key": f"assessment-question:{key}", "prompt": prompt},
        )


def _backfill_versions(bind: sa.Connection, table: str, prefix: str, entries: Sequence) -> None:
    for key, version in entries:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET seed_key = :seed_key "
                "WHERE author_key = 'bank' AND key = :key AND version = :version "
                "AND seed_key IS NULL"
            ),
            {"seed_key": f"{prefix}:{key}/v{version}", "key": key, "version": version},
        )


def upgrade() -> None:
    bind = op.get_bind()

    for table in SEED_KEY_TABLES:
        op.add_column(table, sa.Column("seed_key", sa.String(200), nullable=True))
        op.create_index(
            _index_name(table),
            table,
            ["seed_key"],
            unique=True,
            postgresql_where=sa.text("seed_key IS NOT NULL"),
            sqlite_where=sa.text("seed_key IS NOT NULL"),
        )

    with op.batch_alter_table("metric_dimensions") as batch:
        batch.add_column(
            sa.Column("status", sa.String(20), nullable=False, server_default="published")
        )
        batch.create_check_constraint("status_allowed", "status IN ('published', 'retired')")

    op.create_table(
        "metric_category_anchors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("letter", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="published"),
        sa.Column("seed_key", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "letter IN ('realistic', 'investigative', 'artistic', 'social', "
            "'enterprising', 'conventional')",
            name="letter_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('published', 'retired')",
            name="status_allowed",
        ),
    )
    op.create_index(
        "ix_metric_category_anchors_category",
        "metric_category_anchors",
        ["category"],
        unique=True,
    )
    op.create_index(
        "uq_metric_category_anchors_seed_key",
        "metric_category_anchors",
        ["seed_key"],
        unique=True,
        postgresql_where=sa.text("seed_key IS NOT NULL"),
        sqlite_where=sa.text("seed_key IS NOT NULL"),
    )

    _backfill_dimensions(bind)
    _backfill_anchors(bind)
    _backfill_questions(bind)
    _backfill_versions(
        bind, "assessment_templates", "assessment-template", ASSESSMENT_TEMPLATE_KEYS
    )
    _backfill_versions(bind, "cv_templates", "cv-template", CV_TEMPLATE_KEYS)
    _backfill_versions(bind, "ai_skill_packs", "skill-pack", SKILL_PACK_KEYS)


def downgrade() -> None:
    op.drop_index("ix_metric_category_anchors_category", table_name="metric_category_anchors")
    op.drop_index("uq_metric_category_anchors_seed_key", table_name="metric_category_anchors")
    op.drop_table("metric_category_anchors")

    with op.batch_alter_table("metric_dimensions") as batch:
        batch.drop_constraint("status_allowed", type_="check")
        batch.drop_column("status")

    for table in SEED_KEY_TABLES:
        op.drop_index(_index_name(table), table_name=table)
        op.drop_column(table, "seed_key")
