"""Revert (plan 99 AD10): widen the profile_proposals status CHECK with
the terminal `reverted` state — an approved card undone in one click."""

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

OLD_STATUS = (
    "status IN ('pending', 'approved', 'rejected', 'conflict', 'expired')"
)
NEW_STATUS = (
    "status IN ('pending', 'approved', 'rejected', 'conflict', 'expired', "
    "'reverted')"
)


def upgrade() -> None:
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("status_allowed", type_="check")
        batch.create_check_constraint("status_allowed", NEW_STATUS)


def downgrade() -> None:
    op.execute("DELETE FROM profile_proposals WHERE status = 'reverted'")
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("status_allowed", type_="check")
        batch.create_check_constraint("status_allowed", OLD_STATUS)
