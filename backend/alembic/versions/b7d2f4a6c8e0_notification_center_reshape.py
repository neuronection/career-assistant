"""notification center reshape (Phase 36)

Event/recipient/delivery split + browser-push subscriptions + per-kind
preferences + app_settings KV. Existing single-table rows are backfilled:
one event keeps its id, one recipient row per old user row.

Revision ID: b7d2f4a6c8e0
Revises: e0f5a7c9e1a4
Create Date: 2026-09-01 00:00:00.000000
"""

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "b7d2f4a6c8e0"
down_revision: Union[str, None] = "e0f5a7c9e1a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_new_tables() -> None:
    op.create_table(
        "notification_recipients",
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="unread"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_recipients")),
        sa.ForeignKeyConstraint(
            ["notification_id"], ["notifications.id"],
            name=op.f("fk_notification_recipients_notification_id_notifications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_notification_recipients_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("notification_id", "user_id",
                            name=op.f("uq_notification_recipients_pair")),
        sa.CheckConstraint(
            "status IN ('unread', 'read', 'dismissed')",
            name=op.f("ck_notification_recipients_status_allowed"),
        ),
    )
    op.create_index(
        op.f("ix_notification_recipients_user_id"),
        "notification_recipients", ["user_id"], unique=False,
    )
    op.create_index(
        "ix_notification_recipients_user_status",
        "notification_recipients", ["user_id", "status"], unique=False,
    )

    op.create_table(
        "notification_subscriptions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=False),
        sa.Column("endpoint", sa.String(length=1000), nullable=False),
        sa.Column("endpoint_hash", sa.String(length=64), nullable=False),
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=200), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_subscriptions")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_notification_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "device_id",
                            name=op.f("uq_notification_subs_device")),
    )
    op.create_index(
        op.f("ix_notification_subscriptions_user_id"),
        "notification_subscriptions", ["user_id"], unique=False,
    )
    op.create_index(
        "uq_notification_subs_endpoint",
        "notification_subscriptions", ["endpoint_hash"], unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="pending"),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.ForeignKeyConstraint(
            ["notification_id"], ["notifications.id"],
            name=op.f("fk_notification_deliveries_notification_id_notifications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_notification_deliveries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["notification_subscriptions.id"],
            name=op.f("fk_notification_deliveries_subscription_id_notification_"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("notification_id", "user_id", "channel",
                            name=op.f("uq_notification_deliveries_triple")),
        sa.CheckConstraint(
            "channel IN ('in_app', 'desktop', 'browser')",
            name=op.f("ck_notification_deliveries_channel_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'delivered', 'failed')",
            name=op.f("ck_notification_deliveries_status_allowed"),
        ),
    )
    op.create_index(
        op.f("ix_notification_deliveries_user_id"),
        "notification_deliveries", ["user_id"], unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_user_channel",
        "notification_deliveries", ["user_id", "channel", "created_at"],
        unique=False,
    )

    op.create_table(
        "notification_kind_prefs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("channels", StructuredJSON, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_kind_prefs")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_notification_kind_prefs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["kind_id"], ["notification_kinds.id"],
            name=op.f("fk_notification_kind_prefs_kind_id_notification_kinds"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "kind_id",
                            name=op.f("uq_notification_kind_prefs")),
    )
    op.create_index(
        op.f("ix_notification_kind_prefs_user_id"),
        "notification_kind_prefs", ["user_id"], unique=False,
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_settings")),
    )
    op.create_index(op.f("ix_app_settings_key"), "app_settings", ["key"],
                    unique=True)


def _backfill_recipients(connection) -> None:
    """One inbox row per pre-36 notification row (status carried over)."""
    # Pre-36 kinds carried ["in_app"] only; plan 36 registers the desktop
    # and browser channels, so the default matrix widens for toasty kinds.
    connection.execute(
        sa.text(
            "UPDATE notification_kinds SET default_channels = "
            '\'["in_app", "desktop", "browser"]\' '
            "WHERE key IN ('fit_threshold', 'new_in_family', "
            "'new_posting_match', 'digest_ready', 'deadline_approaching', "
            "'checkin_due')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE notification_kinds SET default_channels = "
            '\'["in_app", "desktop"]\' WHERE key = \'background_failed\''
        )
    )
    rows = connection.execute(
        sa.text("SELECT id, user_id, read_at FROM notifications")
    ).fetchall()
    for notification_id, user_id, read_at in rows:
        if user_id is None:
            continue
        connection.execute(
            sa.text(
                "INSERT INTO notification_recipients "
                "(notification_id, user_id, status, read_at, dismissed_at, id) "
                "VALUES (:nid, :uid, :status, :read_at, NULL, :rid)"
            ),
            {
                "nid": str(notification_id),
                "uid": str(user_id),
                "status": "read" if read_at is not None else "unread",
                "read_at": read_at,
                "rid": str(uuid.uuid4()),
            },
        )


def upgrade() -> None:
    _create_new_tables()
    op.add_column(
        "notification_kinds",
        sa.Column("manage_url", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("source_ref", StructuredJSON, nullable=True),
    )

    connection = op.get_bind()
    _backfill_recipients(connection)

    op.drop_index("uq_notifications_user_dedup_key", table_name="notifications")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_column("user_id")
        batch.drop_column("read_at")
    op.create_index(
        "uq_notifications_dedup_key",
        "notifications", ["dedup_key"], unique=True,
        sqlite_where=sa.text("dedup_key IS NOT NULL"),
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
    op.create_index(
        "ix_notifications_kind_created",
        "notifications", ["kind_id", "created_at"], unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    op.drop_index("ix_notifications_kind_created", table_name="notifications")
    op.drop_index("uq_notifications_dedup_key", table_name="notifications")
    with op.batch_alter_table("notifications") as batch:
        batch.add_column(
            sa.Column("user_id", sa.Uuid(), nullable=True)
        )
        batch.add_column(sa.Column("read_at", sa.DateTime(timezone=True),
                                   nullable=True))
        batch.drop_column("source_ref")
    # Best-effort state restore (multi-recipient events keep one arbitrary
    # recipient — the pre-36 single-table shape cannot represent more).
    connection.execute(
        sa.text(
            "UPDATE notifications SET user_id = ("
            " SELECT r.user_id FROM notification_recipients r"
            " WHERE r.notification_id = notifications.id LIMIT 1),"
            " read_at = ("
            " SELECT r.read_at FROM notification_recipients r"
            " WHERE r.notification_id = notifications.id LIMIT 1)"
        )
    )
    op.create_index(
        "uq_notifications_user_dedup_key",
        "notifications", ["user_id", "dedup_key"], unique=True,
        sqlite_where=sa.text("dedup_key IS NOT NULL"),
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
    op.create_index(
        "ix_notifications_user_read", "notifications", ["user_id", "read_at"],
        unique=False,
    )
    op.drop_column("notification_kinds", "manage_url")
    op.drop_table("app_settings")
    op.drop_table("notification_kind_prefs")
    op.drop_table("notification_deliveries")
    op.drop_table("notification_subscriptions")
    op.drop_table("notification_recipients")
