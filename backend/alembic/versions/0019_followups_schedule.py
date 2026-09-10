"""Follow-up automation: schedules gains the daily
system_followups slot whose followup_sweep job nudges applied postings
(+7d / +14d, user-adjustable) through the funnel."""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "system_source_sync",
    "system_digest",
    "system_demand_import",
    "system_refit_sweep",
    "system_catalog_enrich",
    "user_saved_search",
    "user_checkin",
    "user_autopilot",
)
NEW_KINDS = (
    "system_source_sync",
    "system_digest",
    "system_demand_import",
    "system_refit_sweep",
    "system_catalog_enrich",
    "system_followups",
    "user_saved_search",
    "user_checkin",
    "user_autopilot",
)

OLD_TASKS = (
    "posting_sync",
    "digest",
    "saved_search_run",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
)
NEW_TASKS = (
    "posting_sync",
    "digest",
    "saved_search_run",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
    "followup_sweep",
)


def _constraint_sql(kinds: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{kind}'" for kind in kinds)
    return f"kind IN ({joined})"


def _task_sql(tasks: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{task}'" for task in tasks)
    return f"task IS NULL OR task IN ({joined})"


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(NEW_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(NEW_TASKS))


def downgrade() -> None:
    op.execute("DELETE FROM schedules WHERE kind = 'system_followups'")
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(OLD_TASKS))
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(OLD_KINDS))
