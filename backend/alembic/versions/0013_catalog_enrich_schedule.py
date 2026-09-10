"""Catalog enrichment sweep: schedules.kind gains
system_catalog_enrich — the slot that runs the moderated
archetype v2-enrichment pass."""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "system_source_sync",
    "system_digest",
    "system_demand_import",
    "system_refit_sweep",
    "user_saved_search",
    "user_checkin",
)
NEW_KINDS = (
    "system_source_sync",
    "system_digest",
    "system_demand_import",
    "system_refit_sweep",
    "system_catalog_enrich",
    "user_saved_search",
    "user_checkin",
)


def _constraint_sql(kinds: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{kind}'" for kind in kinds)
    return f"kind IN ({joined})"


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(NEW_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint(
            "task_allowed",
            "task IS NULL OR task IN ('posting_sync', 'digest', "
            "'saved_search_run', 'fit_refit', 'catalog_enrich')",
        )


def downgrade() -> None:
    op.execute("DELETE FROM schedules WHERE kind = 'system_catalog_enrich'")
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(OLD_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint(
            "task_allowed",
            "task IS NULL OR task IN ('posting_sync', 'digest', "
            "'saved_search_run', 'fit_refit')",
        )
