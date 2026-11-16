"""Backup run ledger (ADR-0063 §2).

One row per backup execution, written by `scripts/backup.sh` / the compose
`backup` sidecar (the writer is the backup script, never the web app).
A failed or stale backup is a query, not a log line; staleness alerts are
the deployment template's concern (plan 62).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.models.base import GuidType

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("id", GuidType(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="running"),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'ok', 'failed')",
            name="backup_runs_status_allowed",
        ),
    )
    op.create_index("ix_backup_runs_started", "backup_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_runs_started", table_name="backup_runs")
    op.drop_table("backup_runs")
