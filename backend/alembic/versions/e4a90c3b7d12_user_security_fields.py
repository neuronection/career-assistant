"""user security fields: lockout + token_version

Revision ID: e4a90c3b7d12
Revises: c7d21a9f4e05
Create Date: 2026-08-29 00:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e4a90c3b7d12"
down_revision: Union[str, None] = "c7d21a9f4e05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
