"""Plan 129 phase 4a — `job_radars`: the profile's saved job-search
configuration ("configure once").

One row per profile (unique FK, CASCADE): keywords, locations,
seniority, onsite preference, a salary floor on the NORMALIZED annual
basis (phase 2), the notification cadence and the enabled switch.
`source_keys` is schema-ready for source-follows and deliberately
unconsumed until then. Model-first (family-migration §1): mirrors
``app.models.radar_model.JobRadar`` exactly. ``downgrade()`` drops the
table.

Revision id: ``0057`` — chains onto the plan-129 phase-2 ``0056`` head.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_CADENCE = "cadence IN ('instant', 'daily', 'weekly', 'off')"
_ONSITE = "onsite_policy IS NULL OR onsite_policy IN ('onsite', 'hybrid', 'remote')"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_radars",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("keywords", _JSON, nullable=False),
        sa.Column("locations", _JSON, nullable=False),
        sa.Column("seniority", _JSON, nullable=False),
        sa.Column("onsite_policy", sa.String(length=20), nullable=True),
        sa.Column("salary_min_annual", sa.Numeric(12, 2), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("source_keys", _JSON, nullable=False),
        sa.Column("cadence", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("profile_id", name="uq_job_radars_profile_id"),
        sa.CheckConstraint(_CADENCE, name="cadence_allowed"),
        sa.CheckConstraint(_ONSITE, name="onsite_policy_allowed"),
    )


def downgrade() -> None:
    op.drop_table("job_radars")
