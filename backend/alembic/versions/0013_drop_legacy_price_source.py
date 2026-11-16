"""Drop the retired `legacy` price-source marker.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE ai_generations SET price_source = 'unknown' WHERE price_source = 'legacy'")
    )
    with op.batch_alter_table("ai_generations") as batch:
        batch.drop_constraint("price_source_allowed", type_="check")
        batch.create_check_constraint(
            "price_source_allowed",
            "price_source IN ('user', 'builtin', 'local', 'unknown')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_generations") as batch:
        batch.drop_constraint("price_source_allowed", type_="check")
        batch.create_check_constraint(
            "price_source_allowed",
            "price_source IN ('user', 'builtin', 'local', 'legacy', 'unknown')",
        )
