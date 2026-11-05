"""Plan 52 T4 — bounded live indexing progress on ``background_jobs``.

Adds the nullable ``progress_detail`` document (``JSONB`` on PostgreSQL,
``JSON`` on SQLite) next to ``progress``/``stage``. Vector handlers write a
bounded counters object with the existing per-document progress UPDATE, so a
run shows processed/total documents and chunks, embedded/skipped/failed and
tokens instead of only a percentage. The column is nullable: every other job
family keeps its current progress semantics, and the detail is pruned when
the final ``result`` commits (the result stays authoritative).

No table, index or backfill: existing rows read as ``NULL`` (no live detail).
Downgrade drops the column; the detail is live telemetry, never audit data.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("progress_detail", _JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("background_jobs", "progress_detail")
