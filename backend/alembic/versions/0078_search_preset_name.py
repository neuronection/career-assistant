"""Plan 165 — saved searches become named presets.

The Explore preset bar shows saved postings searches by name; the column
is nullable so existing remembered/saved rows keep working unchanged.
"""

import sqlalchemy as sa

from alembic import op

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("search_history") as batch:
        batch.add_column(sa.Column("name", sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("search_history") as batch:
        batch.drop_column("name")
