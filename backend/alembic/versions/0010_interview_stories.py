"""STAR story library

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-11

Plan 212 S1.7: user-owned STAR stories, optionally linked to an
experience item. The story editor is the only writer; the interview
practice prepends a story question deterministically (never generated).
"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.models.base
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_stories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "competency_keys",
            app.models.base.StructuredJSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("situation", sa.Text(), nullable=False, server_default=""),
        sa.Column("task", sa.Text(), nullable=False, server_default=""),
        sa.Column("action", sa.Text(), nullable=False, server_default=""),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column("experience_item_id", sa.Uuid(), nullable=True),
        sa.Column(
            "evidence_refs",
            app.models.base.StructuredJSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("created_at", app.models.base.TZDateTime(), nullable=False),
        sa.Column("updated_at", app.models.base.TZDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["experience_item_id"], ["experience_items.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interview_stories_user", "interview_stories", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_interview_stories_user", table_name="interview_stories")
    op.drop_table("interview_stories")
