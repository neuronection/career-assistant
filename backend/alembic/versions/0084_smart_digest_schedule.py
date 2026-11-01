"""Plan 179 — the smart digest rides the per-user scheduler.

`schedules` widens `kind_allowed` (+ `user_smart_digest`) and
`task_allowed` (+ `smart_digest`) — exactly the 0058 recipe. The
downgrade deletes smart-digest schedules and smart-digest jobs (the old
CHECKs cannot represent them) and restores the previous text.
"""

import sqlalchemy as sa

from alembic import op

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None

_KIND_ALLOWED_OLD = (
    "kind IN ('system_source_sync', 'system_digest', "
    "'system_demand_import', 'system_refit_sweep', "
    "'system_catalog_enrich', 'system_followups', "
    "'system_market_history', 'system_proposal_sweep', "
    "'system_checkpoint_prune', 'system_extension_reconcile', "
    "'system_skill_relation_learn', "
    "'user_saved_search', 'user_radar_digest', 'user_checkin', "
    "'user_autopilot')"
)
_KIND_ALLOWED = (
    "kind IN ('system_source_sync', 'system_digest', "
    "'system_demand_import', 'system_refit_sweep', "
    "'system_catalog_enrich', 'system_followups', "
    "'system_market_history', 'system_proposal_sweep', "
    "'system_checkpoint_prune', 'system_extension_reconcile', "
    "'system_skill_relation_learn', "
    "'user_saved_search', 'user_radar_digest', 'user_smart_digest', "
    "'user_checkin', 'user_autopilot')"
)
_TASK_ALLOWED_OLD = (
    "task IS NULL OR task IN ('posting_sync', 'digest', "
    "'saved_search_run', 'radar_digest', 'fit_refit', "
    "'catalog_enrich', 'autopilot_run', 'followup_sweep', "
    "'market_history_capture', 'proposal_sweep', "
    "'checkpoint_prune', 'extension_reconcile', "
    "'demand_import', 'skill_relation_learn')"
)
_TASK_ALLOWED = (
    "task IS NULL OR task IN ('posting_sync', 'digest', "
    "'saved_search_run', 'radar_digest', 'smart_digest', "
    "'fit_refit', 'catalog_enrich', 'autopilot_run', "
    "'followup_sweep', 'market_history_capture', 'proposal_sweep', "
    "'checkpoint_prune', 'extension_reconcile', "
    "'demand_import', 'skill_relation_learn')"
)


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _KIND_ALLOWED)
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _TASK_ALLOWED)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schedules WHERE kind = 'user_smart_digest'"))
    op.execute(sa.text("DELETE FROM background_jobs WHERE job_type = 'smart_digest'"))
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _KIND_ALLOWED_OLD)
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _TASK_ALLOWED_OLD)
