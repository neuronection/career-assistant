"""Plan 52 T3c — persist the tokenizer selection source.

Adds ``vector_spaces.tokenizer_source`` so a built token-aware space can
report where its pinned tokenizer came from (provider, curated, admin or
fallback) without guessing from the current profile. The value is metadata,
not part of the frozen space key: migration 0096 already persisted the
identity fields, and the key stays exactly what was stamped at build time.

Existing rows (all v1 or an early v2 row) keep the column NULL. A non-NULL
value is valid only on a token-aware row and only from the closed vocabulary.
Downgrade drops the column and its check; the space key is untouched.
"""

import sqlalchemy as sa

from alembic import op

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None

_SOURCE_CHECK = (
    "tokenizer_source IS NULL OR "
    "(tokenizer_kind IS NOT NULL AND "
    "tokenizer_source IN ('provider', 'curated', 'admin', 'fallback'))"
)


def upgrade() -> None:
    with op.batch_alter_table("vector_spaces") as batch:
        batch.add_column(sa.Column("tokenizer_source", sa.String(length=20), nullable=True))
        batch.create_check_constraint("tokenizer_source_allowed", _SOURCE_CHECK)


def downgrade() -> None:
    with op.batch_alter_table("vector_spaces") as batch:
        batch.drop_constraint("tokenizer_source_allowed", type_="check")
        batch.drop_column("tokenizer_source")
