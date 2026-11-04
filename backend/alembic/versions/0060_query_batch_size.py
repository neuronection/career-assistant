"""Plan 130b — batch policy: job_sources gains query_batch_size.

How many rotating role groups one radar-mode sync searches (1 = the
single focused query, 3 = the cap). Executed strictly sequentially with
a jittered interval the connector enforces — the column only sizes the
batch. Mirrored by the `query_batch_size_allowed` CHECK (the family migration rules
§5b recipe). `downgrade()` drops the constraint and the column.
"""

import sqlalchemy as sa

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_sources") as batch:
        batch.add_column(
            sa.Column(
                "query_batch_size",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.create_check_constraint(
            "query_batch_size_allowed", "query_batch_size BETWEEN 1 AND 3"
        )


def downgrade() -> None:
    with op.batch_alter_table("job_sources") as batch:
        batch.drop_constraint("query_batch_size_allowed", type_="check")
        batch.drop_column("query_batch_size")
