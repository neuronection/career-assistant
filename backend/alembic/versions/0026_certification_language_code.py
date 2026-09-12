"""Explicit language proof on certifications: `certifications.language_code`
optionally names the language a certificate evidences. Pure additive
column, no data migration — existing rows keep their derived matching."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "certifications",
        sa.Column("language_code", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("certifications", "language_code")
