"""Origin+subpath uniqueness for extension sources (the multi-bundle
repo): `extension_sources.subpath` becomes a real column backfilled from
the descriptor JSONB, and the origin-only unique constraint widens to
(origin, subpath) — one source per bundle subpath of the same repo.
Downgrade folds the column back into each descriptor, keeps one row per
origin, and restores the origin-only unique."""

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
    extractor = "json_extract(descriptor, '$.subpath')" if is_sqlite else "descriptor->>'subpath'"
    bind.execute(
        sa.text(f"UPDATE extension_sources SET subpath = COALESCE(NULLIF({extractor}, ''), '')")
    )
    with op.batch_alter_table("extension_sources") as batch:
        batch.drop_constraint("uq_extension_sources_origin", type_="unique")
        batch.create_unique_constraint("uq_extension_sources_origin_subpath", ["origin", "subpath"])


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    extractor = "json_extract(descriptor, '$.subpath')" if is_sqlite else "descriptor->>'subpath'"
    # Fold each row's subpath back into its descriptor (data survives the
    # fold), then keep exactly ONE row per origin — the origin-only unique
    # cannot apply while the multi-bundle rows exist. The keeper is the
    # earliest (created_at, id/rowid) — deterministic on both dialects; the
    # folded descriptors preserve the dropped subpaths.
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
    if is_sqlite:
        dedupe = sa.text(
            "DELETE FROM extension_sources WHERE rowid IN ("
            "SELECT a.rowid FROM extension_sources AS a "
            "JOIN extension_sources AS b ON a.origin = b.origin "
            "WHERE (b.created_at, b.rowid) < (a.created_at, a.rowid))"
        )
    else:
        dedupe = sa.text(
            "DELETE FROM extension_sources AS a USING extension_sources AS b "
            "WHERE a.origin = b.origin "
            "AND (b.created_at, b.id) < (a.created_at, a.id)"
        )
    result = bind.execute(dedupe)
    print(f"DEDUPE[0075.downgrade] deleted={result.rowcount} (sqlite={is_sqlite})")
    with op.batch_alter_table("extension_sources") as batch:
        batch.drop_constraint("uq_extension_sources_origin_subpath", type_="unique")
        batch.create_unique_constraint("uq_extension_sources_origin", ["origin"])
    op.drop_column("extension_sources", "subpath")
