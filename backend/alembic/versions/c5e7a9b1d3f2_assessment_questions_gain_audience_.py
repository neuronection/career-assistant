"""assessment questions gain audience_stages (Phase 25)

Revision ID: c5e7a9b1d3f2
Revises: b2d4f6a8c0e1
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "c5e7a9b1d3f2"
down_revision: Union[str, None] = "b2d4f6a8c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assessment_questions",
        sa.Column("audience_stages", StructuredJSON, nullable=False,
                  server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("assessment_questions", "audience_stages")
