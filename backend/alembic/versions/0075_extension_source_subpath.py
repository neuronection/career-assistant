"""Origin+subpath uniqueness for extension sources (the multi-bundle
repo): `extension_sources.subpath` becomes a real column backfilled from
the descriptor JSONB, and the origin-only unique constraint widens to
(origin, subpath) — one source per bundle subpath of the same repo.
Downgrade folds the column back into the descriptor read path and
restores the origin-only unique."""

import sqlalchemy as sa
from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extension_sources",
        sa.Column("subpath", sa.String(length=255), nullable=False, server_default=""),
    )
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    extractor = (
        "json_extract(descriptor, '$.subpath')" if is_sqlite else "descriptor->>'subpath'"
    )
    bind.execute(
        sa.text(
            "UPDATE extension_sources SET subpath = COALESCE("
            f"NULLIF({extractor}, ''), '')"
        )
    )
    with op.batch_alter_table("extension_sources") as batch:
        batch.drop_constraint("uq_extension_sources_origin", type_="unique")
        batch.create_unique_constraint(
            "uq_extension_sources_origin_subpath", ["origin", "subpath"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    extractor = (
        "json_extract(descriptor, '$.subpath')" if is_sqlite else "descriptor->>'subpath'"
    )
    bind.execute(
        sa.text(
            "UPDATE extension_sources SET descriptor = (CASE WHEN "
            f"{extractor} IS NULL OR {extractor} = '' THEN descriptor ELSE "
            "json_set(descriptor, '$.subpath', subpath) END)"
        )
        if is_sqlite
        else sa.text(
            "UPDATE extension_sources SET descriptor = jsonb_set("
            "descriptor, '{subpath}', to_jsonb(subpath)) "
            "WHERE subpath <> ''"
        )
    )
    with op.batch_alter_table("extension_sources") as batch:
        batch.drop_constraint("uq_extension_sources_origin_subpath", type_="unique")
        batch.create_unique_constraint("uq_extension_sources_origin", ["origin"])
    op.drop_column("extension_sources", "subpath")
