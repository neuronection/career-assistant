"""Career Autopilot: autopilot_goals + autopilot_runs +
autopilot_findings, plus the schedule slot that runs goals on a
cadence (schedules.kind gains `user_autopilot`, .task `autopilot_run`)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015"
down_revision = "0014"
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
)
NEW_KINDS = (
    "system_source_sync",
    "system_digest",
    "system_demand_import",
    "system_refit_sweep",
    "system_catalog_enrich",
    "user_saved_search",
    "user_checkin",
    "user_autopilot",
)

JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _constraint_sql(kinds: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{kind}'" for kind in kinds)
    return f"kind IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "autopilot_goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("goal_text", sa.Text(), nullable=False),
        sa.Column("constraints", JSON, nullable=False),
        sa.Column("cadence", JSON, nullable=True),
        sa.Column("budget", JSON, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'paused')", name="status_allowed"),
    )
    op.create_index(
        "ix_autopilot_goals_user_status",
        "autopilot_goals",
        ["user_id", "status"],
    )
    op.create_index("ix_autopilot_goals_user_id", "autopilot_goals", ["user_id"])

    op.create_table(
        "autopilot_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "goal_id",
            sa.Uuid(),
            sa.ForeignKey("autopilot_goals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("searches_executed", JSON, nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'budget_aborted', "
            "'cancelled', 'failed')",
            name="status_allowed",
        ),
    )
    op.create_index(
        "ix_autopilot_runs_goal_started",
        "autopilot_runs",
        ["goal_id", "started_at"],
    )
    op.create_index("ix_autopilot_runs_goal_id", "autopilot_runs", ["goal_id"])

    op.create_table(
        "autopilot_findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("autopilot_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "posting_id",
            sa.Uuid(),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(4, 2), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("evidence", JSON, nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "posting_id", name="uq_autopilot_run_posting"),
        sa.CheckConstraint(
            "feedback IS NULL OR feedback IN ('more_like_this', 'hide_like_this')",
            name="feedback_allowed",
        ),
        sa.CheckConstraint("score >= 0 AND score <= 10", name="score_range"),
    )
    op.create_index("ix_autopilot_findings_run", "autopilot_findings", ["run_id"])

    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(NEW_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint(
            "task_allowed",
            "task IS NULL OR task IN ('posting_sync', 'digest', "
            "'saved_search_run', 'fit_refit', 'catalog_enrich', 'autopilot_run')",
        )


def downgrade() -> None:
    op.execute("DELETE FROM schedules WHERE kind = 'user_autopilot'")
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint(
            "task_allowed",
            "task IS NULL OR task IN ('posting_sync', 'digest', "
            "'saved_search_run', 'fit_refit', 'catalog_enrich')",
        )
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(OLD_KINDS))
    op.drop_index("ix_autopilot_findings_run", table_name="autopilot_findings")
    op.drop_table("autopilot_findings")
    op.drop_index("ix_autopilot_runs_goal_id", table_name="autopilot_runs")
    op.drop_index("ix_autopilot_runs_goal_started", table_name="autopilot_runs")
    op.drop_table("autopilot_runs")
    op.drop_index("ix_autopilot_goals_user_id", table_name="autopilot_goals")
    op.drop_index("ix_autopilot_goals_user_status", table_name="autopilot_goals")
    op.drop_table("autopilot_goals")
