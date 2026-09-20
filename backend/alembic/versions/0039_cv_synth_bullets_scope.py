"""cv_synth scope gains 'bullets' (achievements-only variants)

Revision ID: 0039
Revises: 0038
"""

from alembic import op

revision = "0039"
down_revision = "0038"

_NEW = "scope IN ('item', 'summary', 'bullets')"
_OLD = "scope IN ('item', 'summary')"


def _apply(check: str) -> None:
    with op.batch_alter_table("cv_synth_items") as batch:
        batch.drop_constraint("scope_allowed", type_="check")
        batch.create_check_constraint("scope_allowed", check)


def upgrade() -> None:
    _apply(_NEW)


def downgrade() -> None:
    op.execute("UPDATE cv_synth_items SET scope = 'item' WHERE scope = 'bullets'")
    _apply(_OLD)
