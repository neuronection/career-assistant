"""assessment runs/questions/answers tables (Phase 23)

Revision ID: e8b2c4f6a9d1
Revises: c9f3a7e1d5b8
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "e8b2c4f6a9d1"
down_revision: Union[str, None] = "c9f3a7e1d5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assessment_runs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False,
                  server_default="full"),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("phase_order", StructuredJSON, nullable=False),
        sa.Column("context", StructuredJSON, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="in_progress"),
        sa.Column("current_phase", sa.Integer(), nullable=False),
        sa.Column("progress", StructuredJSON, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_runs")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_assessment_runs_user_id_users"), ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_assessment_runs_user_id"), "assessment_runs", ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_assessment_runs_status"), "assessment_runs", ["status"],
        unique=False,
    )
    op.create_table(
        "assessment_questions",
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("phase", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("help", sa.Text(), nullable=False, server_default=""),
        sa.Column("options", StructuredJSON, nullable=False),
        sa.Column("time_split", StructuredJSON, nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False,
                  server_default="bank"),
        sa.Column("status", sa.String(length=10), nullable=False,
                  server_default="active"),
        sa.Column("sort_index", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_questions")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["assessment_runs.id"],
            name=op.f("fk_assessment_questions_run_id_assessment_runs"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_assessment_questions_run_id", "assessment_questions", ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_questions_status", "assessment_questions", ["status"],
        unique=False,
    )
    op.create_table(
        "assessment_answers",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("answer", StructuredJSON, nullable=False),
        sa.Column("derived", StructuredJSON, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_answers")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["assessment_runs.id"],
            name=op.f("fk_assessment_answers_run_id_assessment_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["assessment_questions.id"],
            name=op.f("fk_assessment_answers_question_id_assessment_questions"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "question_id",
                            name="uq_assessment_answers_run_question"),
    )
    op.create_index(
        "ix_assessment_answers_run_id", "assessment_answers", ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("assessment_answers")
    op.drop_table("assessment_questions")
    op.drop_table("assessment_runs")
