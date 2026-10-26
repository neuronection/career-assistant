"""Plan 129 phase 4b — the radar digest rides the per-user scheduler.

`schedules` widens `kind_allowed` (+ `user_radar_digest`) and
`task_allowed` (+ `radar_digest`) — exactly the 0053 recipe. The radar
digest reuses the seeded `new_posting_match` notification kind, so no
notification-kind change. ``downgrade()`` deletes radar-digest schedules
(the old CHECKs cannot represent them) and restores the previous text.
"""

import sqlalchemy as sa

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

_KIND_ALLOWED_OLD = (
    "kind IN ('system_source_sync', 'system_digest', "
    "'system_demand_import', 'system_refit_sweep', "
    "'system_catalog_enrich', 'system_followups', "
    "'system_market_history', 'system_proposal_sweep', "
    "'system_checkpoint_prune', 'system_extension_reconcile', "
    "'user_saved_search', 'user_checkin', 'user_autopilot')"
)
_KIND_ALLOWED = (
    "kind IN ('system_source_sync', 'system_digest', "
    "'system_demand_import', 'system_refit_sweep', "
    "'system_catalog_enrich', 'system_followups', "
    "'system_market_history', 'system_proposal_sweep', "
    "'system_checkpoint_prune', 'system_extension_reconcile', "
    "'user_saved_search', 'user_radar_digest', 'user_checkin', "
    "'user_autopilot')"
)
_TASK_ALLOWED_OLD = (
    "task IS NULL OR task IN ('posting_sync', 'digest', "
    "'saved_search_run', 'fit_refit', 'catalog_enrich', "
    "'autopilot_run', 'followup_sweep', 'market_history_capture', "
    "'proposal_sweep', 'checkpoint_prune', 'extension_reconcile', "
    "'demand_import')"
)
_TASK_ALLOWED = (
    "task IS NULL OR task IN ('posting_sync', 'digest', "
    "'saved_search_run', 'radar_digest', 'fit_refit', "
    "'catalog_enrich', 'autopilot_run', 'followup_sweep', "
    "'market_history_capture', 'proposal_sweep', "
    "'checkpoint_prune', 'extension_reconcile', 'demand_import')"
)


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _KIND_ALLOWED)
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _TASK_ALLOWED)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schedules WHERE kind = 'user_radar_digest'"))
    op.execute(sa.text("DELETE FROM background_jobs WHERE job_type = 'radar_digest'"))
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _KIND_ALLOWED_OLD)
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _TASK_ALLOWED_OLD)
