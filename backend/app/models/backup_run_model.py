"""Backup run ledger (ADR-0063 §2 / plan 64 §1.5).

One row per backup execution. The **writer is the backup script**
(``scripts/backup.sh`` and the compose ``backup`` sidecar) — the web app
never writes it; the table exists so a failed or stale backup is a query
away (``SELECT * FROM backup_runs ORDER BY started_at DESC LIMIT 5``)
instead of a log line. Staleness (> 2x the configured interval) is the
operator's external alert (plan 62 templates configure it).

Schema managed by Alembic (``0016_backup_runs``) like every app table, so
the one-shot migrate job creates it as the owner role; the app itself has
no use for it (the script talks to the database through the ``db``
container's owner connection).
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime, UUIDPrimaryKeyMixin

BACKUP_RUN_STATUSES = ("running", "ok", "failed")


class BackupRun(UUIDPrimaryKeyMixin, Base):
    """One off-host/local backup execution (ADR-0063 §2)."""

    __tablename__ = "backup_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'ok', 'failed')",
            name="backup_runs_status_allowed",
        ),
        Index("ix_backup_runs_started", "started_at"),
    )

    started_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="running")
    bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    destination: Mapped[str | None] = mapped_column(Text(), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
