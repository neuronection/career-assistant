"""Plan 129 phase 1 — company_profiles: reviewed firmographics for the
normalized org entity.

One row per organization (unique FK, CASCADE): the reviewed 1:1 layer
over ``organizations`` — company type, size, HQ, founded year, industry
tags, links and typed financial claims (kind + amount + currency +
as-of + source per claim). What postings prove is derived at read time
and never stored here. Model-first (family-migration §1): mirrors
``app.models.company_model.CompanyProfile`` exactly. ``downgrade()``
removes the table.

Revision id: ``0055`` — chains onto the plan-127 ``0054`` head.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_COMPANY_TYPE = (
    "company_type IN ('public', 'private', 'subsidiary', 'nonprofit', 'government', 'startup')"
)
_SOURCE = "source IN ('manual', 'derived')"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("company_type", sa.String(length=20), nullable=True),
        sa.Column("industry_tags", _JSON, nullable=False),
        sa.Column("employees_min", sa.Integer(), nullable=True),
        sa.Column("employees_max", sa.Integer(), nullable=True),
        sa.Column("hq_city", sa.String(length=120), nullable=True),
        sa.Column("hq_country", sa.String(length=60), nullable=True),
        sa.Column("founded_year", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("financials", _JSON, nullable=False),
        sa.Column("links", _JSON, nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", name="uq_company_profiles_organization_id"),
        sa.CheckConstraint(_COMPANY_TYPE, name="company_type_allowed"),
        sa.CheckConstraint(_SOURCE, name="source_allowed"),
    )


def downgrade() -> None:
    op.drop_table("company_profiles")
