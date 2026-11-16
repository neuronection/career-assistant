"""saved screening answers

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-11

Plan 212 S1.5: one reusable answer per user + prompt key. The kit shows
the saved text; the user edits and saves explicitly (no generation, no
auto-apply). `question_key` is the stable prompt key from the kit, never
the localized label.
"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.models.base
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("question_key", sa.String(length=80), nullable=False),
        sa.Column("question_text", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("answer_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "evidence_refs",
            app.models.base.StructuredJSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("created_at", app.models.base.TZDateTime(), nullable=False),
        sa.Column("updated_at", app.models.base.TZDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "question_key", name="uq_saved_answers_user_key"),
    )
    op.create_index("ix_saved_answers_user", "saved_answers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_answers_user", table_name="saved_answers")
    op.drop_table("saved_answers")
