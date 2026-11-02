"""Plan 179 — the cross-user smart-search cache.

`smart_query_cache` holds one row per NORMALIZED free-text query (the
PK is the sha256 of the casefolded, whitespace-collapsed sentence), the
closed ``SmartSearchSpec`` projection and its creation time. The
text→filter mapping has no personal inputs, so the cache is shared
across users — a repeat query from anyone costs zero AI. Cache data,
not records: the daily smart-digest job prunes rows older than 7 days
(ADR-0044 §8 does not apply — the purge is implemented and documented).
The downgrade drops the table; cache data is rebuildable by definition.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def _JSON():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "smart_query_cache",
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("spec", _JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("query_hash"),
    )


def downgrade() -> None:
    op.drop_table("smart_query_cache")
