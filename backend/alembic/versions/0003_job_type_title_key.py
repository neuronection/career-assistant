"""job type title key: normalized column and index

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10 16:00:00.000000

Plan 210 S5: ``jobs.title_key`` is a derived normalized title used by the
write-path duplicate guard and the catalog hygiene report. The backfill is
self-contained Python row iteration (no app imports) so the migration keeps
working after the service code moves on. The index is intentionally not
unique: live duplicate pairs must be merged before a partial unique index
can be added (plan 202/210 deferral).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

_JOBS = sa.table(
    "jobs",
    sa.column("id", sa.Uuid()),
    sa.column("title", sa.String()),
    sa.column("title_key", sa.String()),
)


def _title_key(title: str) -> str:
    text = str(title or "").replace("&", " and ")
    text = _PUNCTUATION.sub(" ", text)
    normalized = _WHITESPACE.sub(" ", text).strip().casefold()
    return re.sub(r"[\s_]+", "-", normalized).strip("-")[:200]


def _backfill() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(_JOBS.c.id, _JOBS.c.title)).mappings()
    for row in rows:
        bind.execute(
            sa.update(_JOBS)
            .where(_JOBS.c.id == row["id"])
            .values(title_key=_title_key(row["title"]))
        )


def upgrade() -> None:
    op.add_column("jobs", sa.Column("title_key", sa.String(length=200), nullable=True))
    op.create_index("ix_jobs_title_key", "jobs", ["title_key"])
    _backfill()


def downgrade() -> None:
    op.drop_index("ix_jobs_title_key", table_name="jobs")
    op.drop_column("jobs", "title_key")
