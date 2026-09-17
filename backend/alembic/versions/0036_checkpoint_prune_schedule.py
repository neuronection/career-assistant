"""Checkpoint retention (plan 98 phase 4, ADR-0016): the
system_checkpoint_prune schedule slot whose checkpoint_prune job prunes
stale LangGraph checkpoint threads (server Postgres; desktop prunes the
SQLite sibling file at boot)."""

from alembic import op

revision = "0036"
down_revision = "0035"
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
    "user_saved_search",
    "user_checkin",
    "user_autopilot",
)
NEW_KINDS = OLD_KINDS + ("system_checkpoint_prune",)

OLD_TASKS = (
    "posting_sync",
    "digest",
    "saved_search_run",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
    "followup_sweep",
    "market_history_capture",
    "proposal_sweep",
)
NEW_TASKS = OLD_TASKS + ("checkpoint_prune",)


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
    op.execute("DELETE FROM schedules WHERE kind = 'system_checkpoint_prune'")
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(OLD_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(OLD_TASKS))
