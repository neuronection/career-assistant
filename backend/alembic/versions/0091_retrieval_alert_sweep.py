"""Plan 51 Q1c — the retrieval alert sweep schedule.

The alert evaluator runs as a bounded system job (``retrieval_alert_sweep``)
on its own five-minute schedule, so every pass is a visible
``background_jobs``/``schedules`` row instead of an invisible loop. This
migration widens the mirrored ``schedules`` CHECKs for that one kind/task;
the kind and task enums and the model constraints change in the same commit
(family law: the boot-provisioned row would otherwise die on insert).

No table is added: alerts use the existing notification funnel and the Q1
read model.
"""

import sqlalchemy as sa

from alembic import op

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "system_source_sync",
    "system_digest",
    "system_demand_import",
    "system_refit_sweep",
    "system_catalog_enrich",
    "system_followups",
    "system_market_history",
    "system_proposal_sweep",
    "system_checkpoint_prune",
    "system_extension_reconcile",
    "system_skill_relation_learn",
    "system_vector_reconcile",
    "user_saved_search",
    "user_radar_digest",
    "user_smart_digest",
    "user_checkin",
    "user_autopilot",
)
NEW_KINDS = (*OLD_KINDS, "system_retrieval_alerts")

OLD_TASKS = (
    "posting_sync",
    "digest",
    "saved_search_run",
    "radar_digest",
    "smart_digest",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
    "followup_sweep",
    "market_history_capture",
    "proposal_sweep",
    "checkpoint_prune",
    "extension_reconcile",
    "demand_import",
    "skill_relation_learn",
    "vector_reconcile",
)
NEW_TASKS = (*OLD_TASKS, "retrieval_alert_sweep")


def _in_sql(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _in_sql("kind", NEW_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint(
            "task_allowed", f"task IS NULL OR {_in_sql('task', NEW_TASKS)}"
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schedules WHERE kind = 'system_retrieval_alerts'"))
    op.execute(sa.text("DELETE FROM background_jobs WHERE job_type = 'retrieval_alert_sweep'"))
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _in_sql("kind", OLD_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint(
            "task_allowed", f"task IS NULL OR {_in_sql('task', OLD_TASKS)}"
        )
