"""Metric model: metric_dimensions + user_metric_profile.

The dimension registry is the one metric language for matching,
assessments, filters and UI; user_metric_profile stores measured values
with the user_skills provenance pattern (source, confidence, evidence)
under a unique (user_id, dimension_key) per.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_dimensions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("group", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("scale", sa.String(length=10), nullable=False),
        sa.Column(
            "reverse_score", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column('sources', JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=False),
        sa.Column('consumers', JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.CheckConstraint(
            '"group" IN (\'interest\', \'value\', \'workstyle\', \'constraint\', \'aptitude\')',
            name="group_allowed",
        ),
        sa.CheckConstraint(
            "scale IN ('scalar', 'vector')", name="scale_allowed"
        ),
    )
    op.create_index(
        "ix_metric_dimensions_key", "metric_dimensions", ["key"], unique=True
    )
    op.create_index("ix_metric_dimensions_group", "metric_dimensions", ["group"])

    op.create_table(
        "user_metric_profile",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dimension_key",
            sa.String(length=60),
            sa.ForeignKey("metric_dimensions.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(4, 2), nullable=False),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default="0.6"
        ),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column('evidence', JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.CheckConstraint(
            "value >= 1 AND value <= 10", name="value_range"
        ),
        sa.CheckConstraint(
            "source IN ('self_report', 'assessment', 'behavior', 'derived')",
            name="source_allowed",
        ),
        sa.UniqueConstraint(
            "user_id", "dimension_key", name="user_dimension"
        ),
    )
    op.create_index(
        "ix_user_metric_profile_user_id", "user_metric_profile", ["user_id"]
    )
    op.create_index(
        "ix_user_metric_profile_dimension_key",
        "user_metric_profile",
        ["dimension_key"],
    )
    op.create_index(
        "ix_user_metric_user", "user_metric_profile", ["user_id", "dimension_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_metric_user", table_name="user_metric_profile")
    op.drop_index(
        "ix_user_metric_profile_dimension_key", table_name="user_metric_profile"
    )
    op.drop_index("ix_user_metric_profile_user_id", table_name="user_metric_profile")
    op.drop_table("user_metric_profile")
    op.drop_index("ix_metric_dimensions_group", table_name="metric_dimensions")
    op.drop_index("ix_metric_dimensions_key", table_name="metric_dimensions")
    op.drop_table("metric_dimensions")
