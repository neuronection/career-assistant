"""Autopilot findings feed indexes (plan 175).

The findings feed orders/filters by `created_at` and joins `posting_id`
(latest-per-posting dedupe, applied-badge join) — both were unindexed
scans over the shortlist table.
"""

from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_autopilot_findings_created",
        "autopilot_findings",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_autopilot_findings_posting",
        "autopilot_findings",
        ["posting_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_findings_posting", table_name="autopilot_findings")
    op.drop_index("ix_autopilot_findings_created", table_name="autopilot_findings")
