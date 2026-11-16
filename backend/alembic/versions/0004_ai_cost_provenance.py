"""AI cost provenance + system price overrides (plan 58 P2)."""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_generations") as batch:
        batch.add_column(sa.Column("provider_key", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("cost_micros", sa.BigInteger(), nullable=True))
        batch.add_column(
            sa.Column(
                "usage_source", sa.String(length=20), nullable=False, server_default="unknown"
            )
        )
        batch.add_column(sa.Column("estimate_method", sa.String(length=40), nullable=True))
        batch.add_column(
            sa.Column(
                "price_source", sa.String(length=20), nullable=False, server_default="unknown"
            )
        )
        batch.add_column(sa.Column("price_version", sa.String(length=120), nullable=True))
        batch.create_check_constraint(
            "usage_source_allowed",
            "usage_source IN ('provider', 'estimated', 'partial', 'unknown')",
        )
        batch.create_check_constraint(
            "price_source_allowed",
            "price_source IN ('user', 'builtin', 'local', 'legacy', 'unknown')",
        )

    op.create_table(
        "ai_price_overrides",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("provider_key", sa.String(length=40), nullable=True),
        sa.Column(
            "provider_ref",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("ai_providers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("match", sa.String(length=10), nullable=False, server_default="exact"),
        sa.Column("input_micros_per_million", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_micros_per_million", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("metering", sa.String(length=20), nullable=False, server_default="tokens"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider_key",
            "provider_ref",
            "model",
            "match",
            name="uq_ai_price_overrides_scope",
        ),
        sa.CheckConstraint("match IN ('exact', 'prefix')", name="match_allowed"),
        sa.CheckConstraint(
            "metering IN ('tokens', 'input_only', 'output_only')",
            name="metering_allowed",
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_price_overrides")
    with op.batch_alter_table("ai_generations") as batch:
        batch.drop_constraint("usage_source_allowed", type_="check")
        batch.drop_constraint("price_source_allowed", type_="check")
        batch.drop_column("price_version")
        batch.drop_column("estimate_method")
        batch.drop_column("price_source")
        batch.drop_column("usage_source")
        batch.drop_column("cost_micros")
        batch.drop_column("provider_key")
