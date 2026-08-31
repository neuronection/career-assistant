"""background_jobs durable queue

Revision ID: c7d21a9f4e05
Revises: 6866a6e415f3
Create Date: 2026-08-28 23:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "c7d21a9f4e05"
down_revision: Union[str, None] = "6866a6e415f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", name=op.f("fk_background_jobs_user_id_users"), ondelete="CASCADE"
            ),
            nullable=True,
        ),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=200), nullable=True),
        sa.Column("payload", StructuredJSON, nullable=False),
        sa.Column("result", StructuredJSON, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_jobs")),
    )
    op.create_index(
        "ix_background_jobs_user_id", "background_jobs", ["user_id"], unique=False
    )
    op.create_index(
        "ix_background_jobs_status_created",
        "background_jobs",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_background_jobs_status_created", table_name="background_jobs")
    op.drop_index("ix_background_jobs_user_id", table_name="background_jobs")
    op.drop_table("background_jobs")
