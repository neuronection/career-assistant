"""schedules table + digest/background kinds (Phase 29)

Revision ID: f3b5d7f9a1c3
Revises: e1a3c5e7b9d2
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f3b5d7f9a1c3"
down_revision: Union[str, None] = "e1a3c5e7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KIND_ROWS = [
    {
        "id": UUID("a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8004"),
        "key": "digest_ready",
        "label": "Weekly digest",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": True,
    },
    {
        "id": UUID("a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8005"),
        "key": "background_failed",
        "label": "Scheduled task failed",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": True,
    },
]


def upgrade() -> None:
    op.bulk_insert(
        sa.table(
            "notification_kinds",
            sa.column("id", sa.Uuid),
            sa.column("key", sa.String),
            sa.column("label", sa.String),
            sa.column("group", sa.String),
            sa.column("severity", sa.String),
            sa.column("default_enabled", sa.Boolean),
            sa.column("default_channels", sa.JSON),
            sa.column("mutable", sa.Boolean),
        ),
        KIND_ROWS,
    )
    op.create_table(
        "schedules",
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=True),
        sa.Column("trigger", sa.JSON(), nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("payload", sa.JSON(), nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=30), nullable=True),
        sa.Column("last_job_id", sa.Uuid(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("misfire_policy", sa.String(length=20), nullable=False,
                  server_default="asap"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"],
            name=op.f("fk_schedules_owner_user_id_users"), ondelete="CASCADE",
        ),
        sa.UniqueConstraint("kind", "owner_user_id", "payload_hash",
                            name="uq_schedules_kind_owner_payload"),
        sa.CheckConstraint(
            "kind IN ('system_source_sync', 'system_digest', "
            "'system_demand_import', 'system_refit_sweep', "
            "'user_saved_search', 'user_checkin')",
            name=op.f("ck_schedules_kind_allowed"),
        ),
        sa.CheckConstraint(
            "misfire_policy IN ('asap', 'skip', 'next_slot')",
            name=op.f("ck_schedules_misfire_allowed"),
        ),
        sa.CheckConstraint(
            "task IS NULL OR task IN ('posting_sync', 'digest', "
            "'saved_search_run', 'fit_refit')",
            name=op.f("ck_schedules_task_allowed"),
        ),
    )
    op.create_index(op.f("ix_schedules_owner_user_id"), "schedules",
                    ["owner_user_id"], unique=False)
    op.create_index("ix_schedules_next_run", "schedules", ["next_run_at"],
                    unique=False)


def downgrade() -> None:
    op.drop_index("ix_schedules_next_run", table_name="schedules")
    op.drop_index(op.f("ix_schedules_owner_user_id"), table_name="schedules")
    op.drop_table("schedules")
    op.execute(
        "DELETE FROM notifications WHERE kind_id IN "
        "(SELECT id FROM notification_kinds WHERE key IN "
        "('digest_ready', 'background_failed'))"
    )
    op.execute(
        "DELETE FROM notification_kinds WHERE key IN "
        "('digest_ready', 'background_failed')"
    )
