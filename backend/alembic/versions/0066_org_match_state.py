"""Plan 135 — queryable org-match state.

`job_postings.org_match` JSONB holds the provenance (layer/score/matched_on
+ state), but JSONB is not filterable dialect-safely — the /postings
"no company" audit filter needs to split gate-rejects from pairs still
pending triage on both Postgres and SQLite. `org_match_state` is the
indexed projection of that one field; the matcher and the triage service
keep the two in sync. Backfill reads the JSONB per row. Downgrade drops
the column (the JSONB keeps the state).
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def _json_dict(value: object) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(
        "job_postings",
        sa.Column("org_match_state", sa.String(length=12), nullable=True),
    )
    with op.batch_alter_table("job_postings") as batch:
        batch.create_check_constraint(
            "org_match_state_allowed",
            "org_match_state IS NULL OR org_match_state IN ('linked', 'pending', 'rejected')",
        )
    postings = bind.execute(sa.text("SELECT id, org_match FROM job_postings")).fetchall()
    for posting_id, org_match in postings:
        state = _json_dict(org_match).get("state")
        if not state:
            continue
        bind.execute(
            sa.text("UPDATE job_postings SET org_match_state = :state WHERE id = :pid"),
            {"state": str(state)[:12], "pid": str(posting_id)},
        )
    op.create_index("ix_postings_org_match_state", "job_postings", ["org_match_state"])


def downgrade() -> None:
    op.drop_index("ix_postings_org_match_state", table_name="job_postings")
    op.drop_column("job_postings", "org_match_state")
