"""engagement: search history, feed state, tag kind, job links, notifications (Phase 24)

Revision ID: b2d4f6a8c0e1
Revises: e8b2c4f6a9d1
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "b2d4f6a8c0e1"
down_revision: Union[str, None] = "e8b2c4f6a9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KIND_ROWS = [
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8001",
        "key": "fit_threshold",
        "label": "Fit threshold reached",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": '["in_app"]',
        "mutable": True,
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8002",
        "key": "new_in_family",
        "label": "New job in a followed family",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": '["in_app"]',
        "mutable": True,
    },
]


def upgrade() -> None:
    op.add_column(
        "match_insights",
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "match_insights",
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "match_insights",
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "interest_tags",
        sa.Column("kind", sa.String(length=20), nullable=False,
                  server_default="topic"),
    )
    op.create_index(
        op.f("ix_interest_tags_kind"), "interest_tags", ["kind"], unique=False
    )
    op.add_column(
        "jobs",
        sa.Column("links", StructuredJSON, nullable=False,
                  server_default=sa.text("'[]'")),
    )

    op.create_table(
        "search_history",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("filters", StructuredJSON, nullable=False),
        sa.Column("filters_hash", sa.String(length=64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("saved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_history")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_search_history_user_id_users"), ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "scope IN ('catalog', 'rankings', 'universities')",
            name=op.f("ck_search_history_scope_allowed"),
        ),
    )
    op.create_index(
        op.f("ix_search_history_user_id"), "search_history", ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_search_history_scope"), "search_history", ["scope"], unique=False
    )
    op.create_index(
        "ix_search_history_user_saved", "search_history", ["user_id", "saved"],
        unique=False,
    )

    op.create_table(
        "notification_kinds",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("group", sa.String(length=40), nullable=False,
                  server_default="career"),
        sa.Column("severity", sa.String(length=20), nullable=False,
                  server_default="info"),
        sa.Column("default_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("default_channels", StructuredJSON, nullable=False,
                  server_default=sa.text("'[\"in_app\"]'")),
        sa.Column("mutable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_kinds")),
        sa.UniqueConstraint("key", name=op.f("uq_notification_kinds_key")),
    )
    op.create_index(
        op.f("ix_notification_kinds_key"), "notification_kinds", ["key"],
        unique=False,
    )
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
        [
            {
                "id": UUID(row["id"]),
                "key": row["key"],
                "label": row["label"],
                "group": row["group"],
                "severity": row["severity"],
                "default_enabled": row["default_enabled"],
                "default_channels": ["in_app"],
                "mutable": row["mutable"],
            }
            for row in KIND_ROWS
        ],
    )

    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind_id", sa.Uuid(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False,
                  server_default="info"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("dedup_key", sa.String(length=150), nullable=True),
        sa.Column("dedup_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["kind_id"], ["notification_kinds.id"],
            name=op.f("fk_notifications_kind_id_notification_kinds"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        op.f("ix_notifications_user_id"), "notifications", ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_read", "notifications", ["user_id", "read_at"],
        unique=False,
    )
    op.create_index(
        "uq_notifications_user_dedup_key", "notifications",
        ["user_id", "dedup_key"], unique=True,
        sqlite_where=sa.text("dedup_key IS NOT NULL"),
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )

    op.create_table(
        "notification_rules",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("params", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_rules")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_notification_rules_user_id_users"), ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "kind",
                            name="uq_notification_rules_user_kind"),
        sa.CheckConstraint(
            "kind IN ('fit_threshold', 'new_in_family')",
            name=op.f("ck_notification_rules_kind_supported"),
        ),
    )
    op.create_index(
        op.f("ix_notification_rules_user_id"), "notification_rules", ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_rules_user_id"),
                  table_name="notification_rules")
    op.drop_table("notification_rules")
    op.drop_index("uq_notifications_user_dedup_key", table_name="notifications")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_notification_kinds_key"), table_name="notification_kinds")
    op.drop_table("notification_kinds")
    op.drop_index("ix_search_history_user_saved", table_name="search_history")
    op.drop_index(op.f("ix_search_history_scope"), table_name="search_history")
    op.drop_index(op.f("ix_search_history_user_id"), table_name="search_history")
    op.drop_table("search_history")
    op.drop_column("jobs", "links")
    op.drop_index(op.f("ix_interest_tags_kind"), table_name="interest_tags")
    op.drop_column("interest_tags", "kind")
    op.drop_column("match_insights", "hidden_at")
    op.drop_column("match_insights", "saved_at")
    op.drop_column("match_insights", "seen_at")
