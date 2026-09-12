"""Run linkage on the audit ledger: `ai_generations.run_id` (nullable
UUID, indexed, no FK) + `run_stage`. Nullability keeps every single-call
audit row indistinguishable from today; the ledger outlives deleted
CVs/jobs/users and the budget sums are untouched."""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_generations",
        sa.Column("run_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "ai_generations",
        sa.Column("run_stage", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_ai_generations_run_id", "ai_generations", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_ai_generations_run_id", table_name="ai_generations")
    op.drop_column("ai_generations", "run_stage")
    op.drop_column("ai_generations", "run_id")
