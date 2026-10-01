""": ai_models.reasoning_effort

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-04 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_models",
        sa.Column("reasoning_effort", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_models", "reasoning_effort")
