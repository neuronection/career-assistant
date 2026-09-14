"""HITL profile proposals (plan 77): `profile_proposals`.

Every chatbot-proposed profile mutation lands here as a pending card the
user resolves. Cards are first-class: chat lineage FKs are SET NULL so a
session delete never cascades into pending proposals. No data migration —
the table starts empty.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

_STRUCTURED = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "profile_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("entity_label", sa.String(length=200), nullable=False),
        sa.Column("payload_json", _STRUCTURED, nullable=False),
        sa.Column("base_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("diff_json", _STRUCTURED, nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column(
            "chat_session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "chat_message_id",
            sa.Uuid(),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "ai_generation_id",
            sa.Uuid(),
            sa.ForeignKey("ai_generations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolve_error",
            sa.String(length=400),
            nullable=False,
            server_default="",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'conflict', 'expired')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "action IN ('create', 'update', 'delete')", name="action_allowed"
        ),
        sa.CheckConstraint(
            "kind IN ('experience_item', 'education_item', 'certification', "
            "'profile_achievement', 'user_skill', 'profile_section')",
            name="kind_allowed",
        ),
        sa.CheckConstraint("source IN ('chat')", name="source_allowed"),
    )
    op.create_index(
        "ix_profile_proposals_user_status",
        "profile_proposals",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_profile_proposals_entity",
        "profile_proposals",
        ["user_id", "entity_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_proposals_entity", table_name="profile_proposals")
    op.drop_index(
        "ix_profile_proposals_user_status", table_name="profile_proposals"
    )
    op.drop_table("profile_proposals")
