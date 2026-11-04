"""Plan 130 — radar-driven ingestion: job_sources gains query_mode + query_cache.

`query_mode` ('static' | 'radar', default 'static' = today's behavior) is
mirrored by the `query_mode_allowed` CHECK (the family migration rules §5b recipe);
`query_cache` is the merged-query artifact (role groups + provenance +
rotation cursor) rebuilt on radar change and read at sync time.
`downgrade()` drops the constraint and both columns.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    with op.batch_alter_table("job_sources") as batch:
        batch.add_column(
            sa.Column(
                "query_mode",
                sa.String(12),
                nullable=False,
                server_default="static",
            )
        )
        batch.add_column(sa.Column("query_cache", _JSON, nullable=True))
        batch.create_check_constraint("query_mode_allowed", "query_mode IN ('static', 'radar')")


def downgrade() -> None:
    with op.batch_alter_table("job_sources") as batch:
        batch.drop_constraint("query_mode_allowed", type_="check")
        batch.drop_column("query_cache")
        batch.drop_column("query_mode")
