"""Experience start is optional: projects may be undated.

`experience_items.start` drops NOT NULL — the API layer only requires
it for jobs/internships/volunteer/freelance (kind != project).
"""

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("experience_items", "start", existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    op.execute(
        """UPDATE experience_items
           SET "start" = COALESCE("end", CURRENT_DATE)::date
           WHERE "start" IS NULL"""
    )
    op.alter_column("experience_items", "start", existing_type=sa.Date(), nullable=False)
