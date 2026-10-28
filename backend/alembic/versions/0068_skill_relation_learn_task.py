"""Plan 138 step 5: the `schedules.task_allowed` widen for the
`skill_relation_learn` job (mirrored CHECK — the enum member and the
`Schedule.task` vocabulary grow together).

The kind slot was reserved early in `0067`; the mirrored `task_allowed`
CHECK is what actually accepts the enqueued task value and is widened
here in the same commit as the `BackgroundJobType` member.
"""

import sqlalchemy as sa

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

OLD_TASKS = (
    "posting_sync",
    "digest",
    "saved_search_run",
    "radar_digest",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
    "followup_sweep",
    "market_history_capture",
    "proposal_sweep",
    "checkpoint_prune",
    "extension_reconcile",
    "demand_import",
)
NEW_TASKS = (*OLD_TASKS, "skill_relation_learn")


def _task_sql(tasks: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{task}'" for task in tasks)
    return f"task IS NULL OR task IN ({joined})"


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(NEW_TASKS))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schedules WHERE task = 'skill_relation_learn'"))
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(OLD_TASKS))
