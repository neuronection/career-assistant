"""Plan 151 — AI ledger time index.

``ix_ai_generations_created_at``: the audit & monitoring surface windows
every query by ``created_at`` (24h/7d/30d overviews, time buckets, recent
failures). task_type/user_id/run_id are indexed since baseline/0029 but
``created_at`` is not, so every windowed aggregate would scan the whole
ledger. Downgrade drops the index (no data change).
"""

from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_generations_created_at", "ai_generations", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_generations_created_at", table_name="ai_generations")
