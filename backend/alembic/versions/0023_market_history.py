"""Demand history: the market_snapshots table plus the
system_market_history schedule slot whose market_history_capture job
persists one snapshot per family/job scope per day."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

JSON = JSONB().with_variant(sa.JSON(), "sqlite")

OLD_KINDS = (
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
NEW_KINDS = OLD_KINDS + ("system_market_history",)

OLD_TASKS = (
    "posting_sync",
    "digest",
    "saved_search_run",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
    "followup_sweep",
)
NEW_TASKS = OLD_TASKS + ("market_history_capture",)


def _constraint_sql(kinds: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{kind}'" for kind in kinds)
    return f"kind IN ({joined})"


def _task_sql(tasks: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{task}'" for task in tasks)
    return f"task IS NULL OR task IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope_kind", sa.String(length=10), nullable=False),
        sa.Column("scope_key", sa.String(length=120), nullable=False),
        sa.Column("family_key", sa.String(length=80), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("capture_date", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("thin_sample", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(scope_kind = 'family' AND family_key IS NOT NULL AND job_id IS NULL)"
            " OR (scope_kind = 'job' AND job_id IS NOT NULL AND family_key IS NULL)",
            name="scope_shape",
        ),
        sa.UniqueConstraint(
            "scope_kind",
            "scope_key",
            "capture_date",
            name="uq_market_snapshots_scope_day",
        ),
    )
    op.create_index(
        "ix_market_snapshots_job", "market_snapshots", ["job_id"]
    )
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(NEW_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(NEW_TASKS))


def downgrade() -> None:
    op.execute("DELETE FROM schedules WHERE kind = 'system_market_history'")
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(OLD_TASKS))
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(OLD_KINDS))
    op.drop_index("ix_market_snapshots_job", table_name="market_snapshots")
    op.drop_table("market_snapshots")
