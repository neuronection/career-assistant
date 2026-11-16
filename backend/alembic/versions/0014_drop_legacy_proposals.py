"""Clear retired v1 job proposals and backfill job state.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                UPDATE job_postings
                   SET posting_facts = posting_facts - 'job_proposal'
                 WHERE jsonb_typeof(posting_facts -> 'job_proposal') = 'object'
                   AND COALESCE(
                         (posting_facts -> 'job_proposal' ->> 'proposal_version')::int,
                         1
                       ) <> 2
                """
            )
        )
    else:
        bind.execute(
            sa.text(
                """
                UPDATE job_postings
                   SET posting_facts = json_remove(posting_facts, '$.job_proposal')
                 WHERE json_type(posting_facts, '$.job_proposal') = 'object'
                   AND COALESCE(
                         json_extract(posting_facts, '$.job_proposal.proposal_version'),
                         1
                       ) <> 2
                """
            )
        )
    bind.execute(
        sa.text(
            "DELETE FROM background_jobs WHERE job_type IN "
            "('job_proposal_backfill', 'mapping_outcome_backfill')"
        )
    )
    bind.execute(
        sa.text("DELETE FROM app_settings WHERE key = 'catalog.job_proposal_backfill.boot'")
    )


def downgrade() -> None:
    pass
