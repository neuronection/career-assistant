"""Plan 168 — durable autopilot run trace.

`autopilot_runs.run_steps` JSONB holds the per-node trace ledger (one
append-return entry per executed node: step, kind, iteration, timing and
whitelisted args/output summaries). The trace is a ledger, not checkpoint
history — checkpoints stay resume-only and TTL-pruned (ADR-0044 §8). The
server default covers the NOT NULL add on SQLite; the column is additive
and the trace is rebuildable forward only, so the downgrade drops it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "autopilot_runs",
        sa.Column("run_steps", _JSON, nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("autopilot_runs", "run_steps")
