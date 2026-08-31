"""notification preferences for the desktop channel (Phase 30)

Revision ID: b8d2f4a6c0e2
Revises: f3b5d7f9a1c3
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "b8d2f4a6c0e2"
down_revision: Union[str, None] = "f3b5d7f9a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("desktop_channel_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("quiet_hours", StructuredJSON, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id",
                            name=op.f("uq_notification_preferences_user")),
    )
    op.create_index(
        op.f("ix_notification_preferences_user_id"),
        "notification_preferences",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_preferences_user_id"),
                  table_name="notification_preferences")
    op.drop_table("notification_preferences")
