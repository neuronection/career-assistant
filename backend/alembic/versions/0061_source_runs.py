"""Plan 134 — source run ledger: one row per ingestion attempt.

The management page's history: trigger, status, timing, item counts and
the bounded error/report per ``sync_source`` call. Additive; the
downgrade drops the table (its rows are operational history).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_TRIGGER = "trigger IN ('manual', 'scheduled')"
_STATUS = "status IN ('ok', 'degraded', 'failed', 'skipped')"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=12), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("report", _JSON, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_id"], ["job_sources.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_TRIGGER, name="trigger_allowed"),
        sa.CheckConstraint(_STATUS, name="status_allowed"),
    )
    op.create_index("ix_source_runs_source_started", "source_runs", ["source_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_source_runs_source_started", table_name="source_runs")
    op.drop_table("source_runs")
