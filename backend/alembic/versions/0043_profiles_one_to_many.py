"""Profiles 1:N (plan 16 P3b / C3): family-normative profile columns.

Identity-auth §5/§6/§12/§15 — `profiles` becomes one user's many
profiles:

- drop the `ix_profiles_user_id` UNIQUE index (1:1 → 1:N; the index is
  recreated non-unique);
- add `name` (NOT NULL, backfilled "Default"), `is_default` (exactly one
  per user — service-enforced), `last_used_at` (§6 last-used memory) and
  `color` (product ADD for the shared ProfileSwitcher swatch).

Existing rows stay (cheap): pre-change rows are 1:1, so every remaining
row *is* its user's only profile — backfill `name='Default'`,
`is_default=true`. Career's product JSON sections are untouched.

**Destructive by doctrine**: the downgrade deletes every non-oldest
profile per user before restoring the UNIQUE index.

Revision ID: 0043
Revises: 0042
"""

from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

_TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(
            sa.Column("name", sa.String(length=120), nullable=False, server_default="Default")
        )
        batch.add_column(
            sa.Column(
                "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(sa.Column("color", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("last_used_at", _TZ, nullable=True))

    # Pre-change rows are 1:1 (the unique index) — each is its user's
    # only profile, hence exactly one Default per user.
    op.execute("UPDATE profiles SET is_default = true, name = 'Default'")

    op.drop_index("ix_profiles_user_id", table_name="profiles")
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_profiles_user_id", table_name="profiles")

    # 1:1 restored: keep the oldest profile per user (destructive-ok).
    op.execute(
        "DELETE FROM profiles WHERE id NOT IN ("
        "SELECT keep_id FROM ("
        "SELECT id AS keep_id, ROW_NUMBER() OVER ("
        "PARTITION BY user_id ORDER BY created_at, id) AS rn FROM profiles"
        ") WHERE rn = 1)"
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=True)

    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("last_used_at")
        batch.drop_column("color")
        batch.drop_column("is_default")
        batch.drop_column("name")
