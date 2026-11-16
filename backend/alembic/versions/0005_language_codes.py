"""language codes projection

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11

Plan 212 S1.4a: the posting extract moves spoken languages from a bare
code list to structured requirements (code + level + evidence). The
explore facet needs a dialect-safe scalar, so `language_codes` stores a
comma-delimited, lower-cased projection (`",en,el,"`) written by
`apply_extract`; the structured rows stay in `job_postings.extract`.

Existing rows are left NULL: `EXTRACT_VERSION` moves to 6 and the
bounded backfill re-extracts them, which writes the projection. No old
JSON path is read as a fallback (no-BC).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("language_codes", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_postings", "language_codes")
