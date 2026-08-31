"""growth plans/steps + learning resources (Phase 28)

Revision ID: e1a3c5e7b9d2
Revises: d8f0b2c4e6a5
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e1a3c5e7b9d2"
down_revision: Union[str, None] = "d8f0b2c4e6a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    op.create_table(
        "growth_plans",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("target_job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="active"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_growth_plans")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_growth_plans_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_job_id"], ["jobs.id"],
            name=op.f("fk_growth_plans_target_job_id_jobs"), ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "target_job_id",
                            name="uq_growth_plans_user_job"),
    )
    op.create_index(op.f("ix_growth_plans_user_id"), "growth_plans",
                    ["user_id"], unique=False)
    op.create_index(op.f("ix_growth_plans_status"), "growth_plans",
                    ["status"], unique=False)

    op.create_table(
        "growth_plan_steps",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=True),
        sa.Column("path_step_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False,
                  server_default=""),
        sa.Column("target_level", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="todo"),
        sa.Column("completed_level", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_growth_plan_steps")),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["growth_plans.id"],
            name=op.f("fk_growth_plan_steps_plan_id_growth_plans"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"],
            name=op.f("fk_growth_plan_steps_skill_id_skills"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["path_step_id"], ["career_path_steps.id"],
            name=op.f("fk_growth_plan_steps_path_step_id_career_path_steps"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("plan_id", "position",
                            name="uq_growth_plan_steps_plan_pos"),
        sa.CheckConstraint(
            "kind IN ('skill', 'experience', 'certification', 'education')",
            name=op.f("ck_growth_plan_steps_kind_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('todo', 'doing', 'done', 'skipped')",
            name=op.f("ck_growth_plan_steps_status_allowed"),
        ),
        sa.CheckConstraint(
            "target_level IS NULL OR (target_level >= 1 AND target_level <= 10)",
            name=op.f("ck_growth_plan_steps_target_level_range"),
        ),
    )
    if not _is_sqlite():
        op.execute(
            "ALTER TABLE growth_plan_steps "
            "ADD CONSTRAINT uq_growth_plan_steps_plan_pos_deferrable "
            "UNIQUE (plan_id, position) DEFERRABLE INITIALLY DEFERRED"
        )
        op.execute(
            "ALTER TABLE growth_plan_steps "
            "DROP CONSTRAINT uq_growth_plan_steps_plan_pos"
        )
    op.create_index("ix_growth_plan_steps_plan_id", "growth_plan_steps",
                    ["plan_id"], unique=False)

    op.create_table(
        "learning_resources",
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False,
                  server_default=""),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("cost", sa.String(length=20), nullable=False,
                  server_default="free"),
        sa.Column("level_target", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="published"),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="admin"),
        sa.Column("notes", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_resources")),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"],
            name=op.f("fk_learning_resources_skill_id_skills"), ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "kind IN ('course', 'book', 'cert', 'doc', 'video')",
            name=op.f("ck_learning_resources_kind_allowed"),
        ),
        sa.CheckConstraint(
            "cost IN ('free', 'freemium', 'paid')",
            name=op.f("ck_learning_resources_cost_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published')",
            name=op.f("ck_learning_resources_status_allowed"),
        ),
    )
    op.create_index("ix_learning_resources_skill_id", "learning_resources",
                    ["skill_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_learning_resources_skill_id", table_name="learning_resources")
    op.drop_table("learning_resources")
    if not _is_sqlite():
        op.execute(
            "ALTER TABLE growth_plan_steps "
            "DROP CONSTRAINT IF EXISTS uq_growth_plan_steps_plan_pos_deferrable"
        )
    op.drop_index("ix_growth_plan_steps_plan_id", table_name="growth_plan_steps")
    op.drop_table("growth_plan_steps")
    op.drop_index(op.f("ix_growth_plans_status"), table_name="growth_plans")
    op.drop_index(op.f("ix_growth_plans_user_id"), table_name="growth_plans")
    op.drop_table("growth_plans")
