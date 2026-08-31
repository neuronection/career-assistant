"""deep posting extraction columns (Phase 31)

Revision ID: c9e4f6a8d0f3
Revises: b8d2f4a6c0e2
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "c9e4f6a8d0f3"
down_revision: Union[str, None] = "b8d2f4a6c0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_postings", sa.Column("extract", StructuredJSON, nullable=True)
    )
    op.add_column(
        "job_postings",
        sa.Column("extract_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column("needs_review", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("job_postings", "needs_review")
    op.drop_column("job_postings", "extract_version")
    op.drop_column("job_postings", "extract")
