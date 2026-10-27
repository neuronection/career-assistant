"""The postings filter system (plan 136): saved filter presets with the
filter spec as versioned JSONB. Profile-scoped — the fit score and saved
state differ per profile."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")
_UUID = UUID().with_variant(sa.Text(), "sqlite")

revision = "0066"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "posting_filter_presets",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("profile_id", _UUID, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("tags", _JSON, nullable=False, server_default="[]"),
        sa.Column(
            "filters",
            _JSON,
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("profile_id", "name", name="uq_posting_filter_presets_profile_name"),
    )
    op.create_index(
        "ix_posting_filter_presets_profile",
        "posting_filter_presets",
        ["profile_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_posting_filter_presets_profile", table_name="posting_filter_presets")
    op.drop_table("posting_filter_presets")
