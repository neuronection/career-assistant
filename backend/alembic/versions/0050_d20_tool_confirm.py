"""Plan 32 follow-up (D20 / ADR-0011 / ADR-0015): the destructive-confirm
runtime funnel's store.

Two shapes in one migration:

* ``profile_proposals.kind`` widens to carry ``tool_execution`` — a
  destructive tool call becomes a Class-B card in the existing proposal
  machinery (idempotent resolve, notification fanout, cross-session
  inbox); the constraint widening is the mirrored-CHECK rule
  (family-migration §5b): provisioning the new kind otherwise 500s on
  insert;
* ``user_tool_grants`` — per-user state-changing enablement (the tools
  catalog toggle): a ``state-changing`` registry tool executes only
  while a grant row exists; ``destructive`` tools are never grantable
  and confirm every call.

Model-first (family-migration §1): mirrors ``app.models.enums`` +
``app.models.tool_grant_model`` exactly.
"""

import sqlalchemy as sa

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint(
            "kind_allowed",
            "kind IN ('experience_item', 'education_item', 'certification', "
            "'profile_achievement', 'user_skill', 'profile_section', 'cv_synth', "
            "'cv_set_bullets', 'cv_choice', 'tool_execution')",
        )
    op.create_table(
        "user_tool_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tool_key", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "tool_key", name="uq_user_tool_grants"),
        sa.CheckConstraint("tool_key <> ''", name="tool_key_nonempty"),
    )
    op.create_index("ix_user_tool_grants_user", "user_tool_grants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_tool_grants_user", table_name="user_tool_grants")
    op.drop_table("user_tool_grants")
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint(
            "kind_allowed",
            "kind IN ('experience_item', 'education_item', 'certification', "
            "'profile_achievement', 'user_skill', 'profile_section', 'cv_synth', "
            "'cv_set_bullets', 'cv_choice')",
        )
