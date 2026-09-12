"""Derivation opt-out: `user_skills.derive_enabled` (boolean, default
true). False-derived rows keep their last level and are never touched
or re-created by apply_derivation until the user re-enables them."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_skills",
        sa.Column(
            "derive_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_skills", "derive_enabled")
