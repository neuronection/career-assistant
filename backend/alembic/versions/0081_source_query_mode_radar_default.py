"""Job sources default to Follow my job radar (plan 154 follow-up).

`job_sources.query_mode` now ships a radar server default: a freshly
created source rotates the user's job radar role groups instead of
requiring manual keyword entry. Existing rows are untouched — the change
is the DEFAULT for new rows on both dialects.
"""

import sqlalchemy as sa

from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("job_sources") as batch:
            batch.alter_column(
                "query_mode",
                existing_type=sa.String(length=12),
                existing_nullable=False,
                server_default="radar",
            )
    else:
        op.alter_column(
            "job_sources",
            "query_mode",
            existing_type=sa.String(length=12),
            existing_nullable=False,
            server_default="radar",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("job_sources") as batch:
            batch.alter_column(
                "query_mode",
                existing_type=sa.String(length=12),
                existing_nullable=False,
                server_default="static",
            )
    else:
        op.alter_column(
            "job_sources",
            "query_mode",
            existing_type=sa.String(length=12),
            existing_nullable=False,
            server_default="static",
        )
