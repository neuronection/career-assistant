"""numeric grade model

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11

Plan 212 S1.4c: replace the qualitative `education_items.grade_band`
with a scale-scoped numeric model (`grade_scale`, `grade_value`,
derived `grade_ordinal`). The shipped vocabulary
(`low|below_average|average|good|excellent|unknown`) is not convertible
into a formal class or GPA, so every existing value becomes NULL — no
fabricated grade, no read fallback. Users re-enter a formal value once.

SQLite rebuilds the table through `batch_alter_table`; Postgres alters
in place. Downgrade restores the column shape (values are not
recoverable — documented).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("education_items") as batch:
        batch.add_column(sa.Column("grade_scale", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("grade_value", sa.Numeric(5, 2), nullable=True))
        batch.add_column(sa.Column("grade_ordinal", sa.Numeric(5, 2), nullable=True))
        batch.drop_column("grade_band")


def downgrade() -> None:
    with op.batch_alter_table("education_items") as batch:
        batch.add_column(sa.Column("grade_band", sa.String(length=20), nullable=True))
        batch.drop_column("grade_ordinal")
        batch.drop_column("grade_value")
        batch.drop_column("grade_scale")
