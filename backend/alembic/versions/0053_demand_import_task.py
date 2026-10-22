"""Plan 122 Phase 3 — the dormant `SYSTEM_DEMAND_IMPORT` slot gets its task.

Plan 113 added the schedule kind but never widened
`schedules.task_allowed`, so provisioning a demand-import schedule failed
the CHECK. This revision widens ONLY that constraint — no table, column or
index changes (the plan's "schema: none" claim held everywhere else).

``downgrade()`` deletes demand-import schedules (the old CHECK cannot
represent them) and restores the previous constraint text.
"""

import sqlalchemy as sa

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

_TASK_ALLOWED_OLD = (
    "task IS NULL OR task IN ('posting_sync', 'digest', "
    "'saved_search_run', 'fit_refit', 'catalog_enrich', "
    "'autopilot_run', 'followup_sweep', 'market_history_capture', "
    "'proposal_sweep', 'checkpoint_prune', 'extension_reconcile')"
)
_TASK_ALLOWED = (
    "task IS NULL OR task IN ('posting_sync', 'digest', "
    "'saved_search_run', 'fit_refit', 'catalog_enrich', "
    "'autopilot_run', 'followup_sweep', 'market_history_capture', "
    "'proposal_sweep', 'checkpoint_prune', 'extension_reconcile', "
    "'demand_import')"
)


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _TASK_ALLOWED)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schedules WHERE task = 'demand_import'"))
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _TASK_ALLOWED_OLD)
