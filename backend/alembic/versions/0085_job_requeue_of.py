"""Plan 184 — the bulk-reprocess marker.

`background_jobs.requeue_of` (nullable UUID, indexed, no FK) links a
requeued job back to the failed row it replaces. Plain column, no foreign
key: the requeue chain outlives deletions exactly like
`ai_generations.run_id` (the audit outlives deleted CVs/jobs/users). The
marker is auxiliary audit data — the downgrade drops it by design.
"""

import sqlalchemy as sa

from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("requeue_of", sa.Uuid(), nullable=True))
    op.create_index("ix_background_jobs_requeue_of", "background_jobs", ["requeue_of"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_requeue_of", table_name="background_jobs")
    op.drop_column("background_jobs", "requeue_of")
