"""Plan 153 slice 1: the `schedules` CHECK widen for the
`embeddings_reconcile` job (mirrored CHECKs — the enum members and the
`Schedule.kind`/`Schedule.task` vocabularies grow together, family
law §5b: the same commit widens both or the boot-provisioned row dies
on insert).

The skill-embedding reconcile batch (plan 153 assumption 2) runs as a
periodic scheduler job; this is the only schema change it needs — the
embeddings themselves live in the existing `ai_embeddings` store under
`entity_kind='skill'`.
"""

import sqlalchemy as sa

from alembic import op

revision = "0086"
down_revision = "0085"
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
    "user_saved_search",
    "user_radar_digest",
    "user_smart_digest",
    "user_checkin",
    "user_autopilot",
)
NEW_KINDS = (*OLD_KINDS, "system_embeddings_reconcile")

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
)
NEW_TASKS = (*OLD_TASKS, "embeddings_reconcile")


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
    op.execute(sa.text("DELETE FROM schedules WHERE kind = 'system_embeddings_reconcile'"))
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _in_sql("kind", OLD_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint(
            "task_allowed", f"task IS NULL OR {_in_sql('task', OLD_TASKS)}"
        )
