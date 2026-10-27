"""Tool-timeout fold: the managed-spawn mint put ``timeout_seconds: 30``
on fetch_postings sources, which died mid-run ("tool call timed out")
— the fetch's own budget alone is 20–90s before pacing overhead.

Only the exact minted default (30) moves to 120 (the mcp model's
ceiling); anything else is a deliberate value and stays. The downgrade
restores 30 on the rows this revision moved.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def _rows(bind):
    sources = sa.table(
        "job_sources",
        sa.column("id", sa.Uuid()),
        sa.column("connector_key", sa.String()),
        sa.column("config", _JSON),
    )
    return sources, bind.execute(sa.select(sources)).fetchall()


def upgrade() -> None:
    bind = op.get_bind()
    sources, rows = _rows(bind)
    for row in rows:
        config = dict(row.config or {})
        if row.connector_key != "mcp" or config.get("timeout_seconds") != 30:
            continue
        config["timeout_seconds"] = 120
        bind.execute(sources.update().where(sources.c.id == row.id).values(config=config))


def downgrade() -> None:
    bind = op.get_bind()
    sources, rows = _rows(bind)
    for row in rows:
        config = dict(row.config or {})
        if row.connector_key != "mcp" or config.get("timeout_seconds") != 120:
            continue
        config["timeout_seconds"] = 30
        bind.execute(sources.update().where(sources.c.id == row.id).values(config=config))
