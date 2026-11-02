"""Plan 173 — source display names.

`job_sources.title` holds the extension manifest's human display name
("LinkedIn") for imported sources; posting surfaces show it instead of the
connector class title ("MCP script (external process)"). Nullable — builtin
sources keep NULL and fall back to the connector title; imported rows get
the title seeded at managed import and refreshed on re-apply. The column is
additive and the downgrade drops it.
"""

import sqlalchemy as sa

from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_sources", sa.Column("title", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("job_sources", "title")
