"""Posting trust signals and cross-source dedupe

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11

Plan 212 S2.2: a canonical posting can absorb cross-source duplicates;
`repost_count`, `last_verified_at` and typed `trust_flags` carry the
evidence. Low-confidence pairs stay proposals in
`trust_flags.duplicate_candidate` until an admin merges or clears them.
"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.models.base
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite cannot ALTER-add a named self-FK; it rebuilds the table through
    # batch mode. Postgres takes the plain ALTER path (no table rewrite).
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("job_postings", recreate="always") as batch:
            batch.add_column(sa.Column("duplicate_of_id", sa.Uuid(), nullable=True))
            batch.add_column(
                sa.Column("repost_count", sa.Integer(), nullable=False, server_default="0")
            )
            batch.add_column(
                sa.Column("last_verified_at", app.models.base.TZDateTime(), nullable=True)
            )
            batch.add_column(
                sa.Column(
                    "trust_flags",
                    app.models.base.StructuredJSON,
                    nullable=False,
                    server_default=sa.text("'{}'"),
                )
            )
            batch.create_foreign_key(
                "fk_job_postings_duplicate_of",
                "job_postings",
                ["duplicate_of_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index("ix_postings_duplicate_of", ["duplicate_of_id"])
        return

    op.add_column("job_postings", sa.Column("duplicate_of_id", sa.Uuid(), nullable=True))
    op.add_column(
        "job_postings",
        sa.Column("repost_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "job_postings",
        sa.Column("last_verified_at", app.models.base.TZDateTime(), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column(
            "trust_flags",
            app.models.base.StructuredJSON,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.create_foreign_key(
        "fk_job_postings_duplicate_of",
        "job_postings",
        "job_postings",
        ["duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_postings_duplicate_of", "job_postings", ["duplicate_of_id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("job_postings", recreate="always") as batch:
            batch.drop_index("ix_postings_duplicate_of")
            batch.drop_constraint("fk_job_postings_duplicate_of", type_="foreignkey")
            batch.drop_column("trust_flags")
            batch.drop_column("last_verified_at")
            batch.drop_column("repost_count")
            batch.drop_column("duplicate_of_id")
        return

    op.drop_index("ix_postings_duplicate_of", table_name="job_postings")
    op.drop_constraint("fk_job_postings_duplicate_of", "job_postings", type_="foreignkey")
    op.drop_column("job_postings", "trust_flags")
    op.drop_column("job_postings", "last_verified_at")
    op.drop_column("job_postings", "repost_count")
    op.drop_column("job_postings", "duplicate_of_id")
