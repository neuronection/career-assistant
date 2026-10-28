"""Tree-placement provenance (plan 139): `skills.parent_source`.

Tri-state CHECK column: 'curated' (a human set or deliberately cleared
the parent), 'learned' (the tree catch-up filled it from an approved
`is_a` edge), NULL (untouched by human and machine — the only slot the
catch-up may fill). No data migration: existing placements keep NULL —
fabricating either value would claim a decision nobody recorded, and the
catch-up's fills-only-empty rule already skips non-empty slots, so NULL
degrades gracefully (plan 139, decision 7).
"""

import sqlalchemy as sa

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("skills") as batch:
        batch.add_column(sa.Column("parent_source", sa.String(20), nullable=True))
        batch.create_check_constraint(
            "parent_source_allowed", "parent_source IN ('curated', 'learned')"
        )


def downgrade() -> None:
    with op.batch_alter_table("skills") as batch:
        batch.drop_constraint("parent_source_allowed", type_="check")
        batch.drop_column("parent_source")
