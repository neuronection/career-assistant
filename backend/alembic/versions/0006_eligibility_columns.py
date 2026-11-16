"""eligibility columns: work authorization, opportunity type, deadline, overrides

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11

Plan 212 S1.4b: the typed columns the eligibility gates and the student
opportunity surfaces read. `job_postings` gains the extracted
work-authorization status, opportunity type and explicit application
deadline; `posting_interactions` gains the per-user `gate_overrides`
map (``{"visa": true, "grade": false}``) so an "apply anyway" decision
survives a cached fit without invalidating it.

No data backfill: the extraction backfill (`EXTRACT_VERSION` 6) writes
the posting columns; overrides start empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.models.base
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("work_authorization", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column("opportunity_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column("application_deadline", sa.Date(), nullable=True),
    )
    op.add_column(
        "posting_interactions",
        sa.Column(
            "gate_overrides",
            app.models.base.StructuredJSON,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("posting_interactions", "gate_overrides")
    op.drop_column("job_postings", "application_deadline")
    op.drop_column("job_postings", "opportunity_type")
    op.drop_column("job_postings", "work_authorization")
