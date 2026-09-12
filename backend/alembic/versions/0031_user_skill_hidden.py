"""Skill deletion tombstone: `user_skills.hidden` (boolean, default
false). A hidden row is not rendered anywhere and apply_derivation
never resurrects it; re-adding the skill creates a fresh row."""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_skills",
        sa.Column(
            "hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_skills", "hidden")
