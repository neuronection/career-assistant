"""taxonomy deprecation flag

Revision ID: f5b21e8c9a30
Revises: e4a90c3b7d12
Create Date: 2026-08-29 01:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f5b21e8c9a30"
down_revision: Union[str, None] = "e4a90c3b7d12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("interest_tags", "skill_tags"):
        op.add_column(
            table,
            sa.Column(
                "deprecated", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )


def downgrade() -> None:
    for table in ("interest_tags", "skill_tags"):
        op.drop_column(table, "deprecated")
