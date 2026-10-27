"""Run status vocabulary: ``running`` — the ledger row is written at run
START (live status + stage progress on the management page) and updated
to its final status when the run ends.

Self-healing: a new run closes the source's stale running rows (>30 min)
as interrupted, so a crash never leaves a ghost behind."""

import sqlalchemy as sa

from alembic import op

_OLD = "status IN ('ok', 'degraded', 'failed', 'skipped')"
_NEW = "status IN ('running', 'ok', 'degraded', 'failed', 'skipped')"

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_runs") as batch:
        batch.drop_constraint("status_allowed", type_="check")
        batch.create_check_constraint("status_allowed", _NEW)


def downgrade() -> None:
    op.execute("DELETE FROM source_runs WHERE status = 'running'")
    with op.batch_alter_table("source_runs") as batch:
        batch.drop_constraint("status_allowed", type_="check")
        batch.create_check_constraint("status_allowed", _OLD)
