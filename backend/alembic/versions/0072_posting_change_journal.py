"""Plan 142 — posting change journal.

Append-only ``posting_changes``: one row per real posting mutation with
its actor, operation parameters, duration and capped field diff, written
through the single ``PostingChangeJournal.record`` seam by every writer
(sync upsert, LLM extract, detail fetch, company matcher/merge/triage,
skill re-tag, expiry, manual moderation). The digest gate keeps no-op
writes out; ``actor_ref``/``operation`` carry ids and knobs only —
prompt/response content stays in ``ai_generations``/``job_postings.raw``.
Downgrade drops the table (rows are operational history, like
``source_runs``).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_ACTOR_KIND = (
    "actor_kind IN ("
    "'sync_run', 'extract_llm', 'detail_fetch', 'company_match', "
    "'retag', 'manual', 'expiry')"
)
_OUTCOME = "outcome IN ('ok', 'partial', 'error')"

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "posting_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_kind", sa.String(length=40), nullable=False),
        sa.Column("actor_ref", _JSON, nullable=True),
        sa.Column("operation", _JSON, nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("diff", _JSON, nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False, server_default="ok"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["posting_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_ACTOR_KIND, name="actor_kind_allowed"),
        sa.CheckConstraint(_OUTCOME, name="outcome_allowed"),
    )
    op.create_index(
        "ix_posting_changes_posting_occurred", "posting_changes", ["posting_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_posting_changes_posting_occurred", table_name="posting_changes")
    op.drop_table("posting_changes")
