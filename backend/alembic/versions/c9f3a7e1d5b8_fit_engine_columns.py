"""fit engine columns on match_insights + profile experience/preferences (Phase 22)

Revision ID: c9f3a7e1d5b8
Revises: b7e4d1a9c3f2
Create Date: 2026-08-31 00:00:00.000000

Destructive (pre-launch): `base_score` and the tag-overlap fallback are
deleted — the deterministic fit layer replaces them. No compatibility path.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "c9f3a7e1d5b8"
down_revision: Union[str, None] = "b7e4d1a9c3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    op.add_column(
        "match_insights",
        sa.Column("fit_score", sa.Numeric(4, 2), nullable=True),
    )
    op.add_column(
        "match_insights",
        sa.Column("fit_breakdown", StructuredJSON, nullable=True),
    )
    op.add_column(
        "match_insights",
        sa.Column("fit_version", sa.Integer(), nullable=False,
                  server_default="0"),
    )
    if _is_sqlite():
        with op.batch_alter_table("match_insights") as batch:
            batch.drop_column("base_score")
    else:
        op.drop_column("match_insights", "base_score")
    op.add_column(
        "profiles", sa.Column("experience", StructuredJSON, nullable=False,
                              server_default=sa.text("'[]'"))
    )
    op.add_column(
        "profiles", sa.Column("preferences", StructuredJSON, nullable=False,
                              server_default=sa.text("'{}'"))
    )


def downgrade() -> None:
    op.drop_column("profiles", "preferences")
    op.drop_column("profiles", "experience")
    op.add_column(
        "match_insights",
        sa.Column("base_score", sa.Numeric(4, 2), nullable=True),
    )
    op.drop_column("match_insights", "fit_version")
    op.drop_column("match_insights", "fit_breakdown")
    op.drop_column("match_insights", "fit_score")
