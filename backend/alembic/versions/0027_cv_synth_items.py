"""Synthesized CV items: `cv_synth_items` (plan 62) — a user-level
library of AI-written or manual variants over CV context source items,
with typed source refs and source content hashes for staleness
detection. No data migration — the table starts empty."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_STRUCTURED = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "cv_synth_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("variant_key", sa.String(length=60), nullable=False),
        sa.Column(
            "target_posting_id",
            sa.Uuid(),
            sa.ForeignKey("job_postings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_refs", _STRUCTURED, nullable=False),
        sa.Column("source_state", _STRUCTURED, nullable=False),
        sa.Column("source_set_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", _STRUCTURED, nullable=False),
        sa.Column("evidence_refs", _STRUCTURED, nullable=False),
        sa.Column("voice", _STRUCTURED, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('item', 'summary')", name="scope_allowed"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')", name="status_allowed"
        ),
        sa.CheckConstraint("source IN ('ai', 'manual')", name="source_allowed"),
        sa.CheckConstraint("variant_key <> ''", name="variant_key_present"),
    )
    op.create_index(
        "ix_cv_synth_items_user_status",
        "cv_synth_items",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_cv_synth_items_user_set",
        "cv_synth_items",
        ["user_id", "source_set_hash"],
    )
    op.create_index(
        "ix_cv_synth_items_user_posting",
        "cv_synth_items",
        ["user_id", "target_posting_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cv_synth_items_user_posting", table_name="cv_synth_items")
    op.drop_index("ix_cv_synth_items_user_set", table_name="cv_synth_items")
    op.drop_index("ix_cv_synth_items_user_status", table_name="cv_synth_items")
    op.drop_table("cv_synth_items")
