"""posting refs + posting_fits + postings saved-search scope (Phase 32)

Revision ID: e0f5a7c9e1a4
Revises: c9e4f6a8d0f3
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "e0f5a7c9e1a4"
down_revision: Union[str, None] = "c9e4f6a8d0f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_refs(connection) -> None:
    """Generate unique Crockford refs for postings inserted pre-32."""
    from app.models.posting_model import generate_posting_ref

    rows = connection.execute(
        sa.text("SELECT id FROM job_postings WHERE ref IS NULL")
    ).fetchall()
    for (posting_id,) in rows:
        connection.execute(
            sa.text("UPDATE job_postings SET ref = :ref WHERE id = :id"),
            {"ref": generate_posting_ref(), "id": str(posting_id)},
        )


def upgrade() -> None:
    op.add_column("job_postings", sa.Column("ref", sa.String(length=8), nullable=True))
    connection = op.get_bind()
    _backfill_refs(connection)
    with op.batch_alter_table("job_postings") as batch:
        batch.alter_column("ref", existing_type=sa.String(length=8), nullable=False)
    op.create_index(
        op.f("ix_job_postings_ref"), "job_postings", ["ref"], unique=True
    )

    op.create_table(
        "posting_fits",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Numeric(4, 2), nullable=False),
        sa.Column("breakdown", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("inputs_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posting_fits")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_posting_fits_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"], ["job_postings.id"],
            name=op.f("fk_posting_fits_posting_id_job_postings"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "posting_id",
                            name=op.f("uq_posting_fits_user_posting")),
    )
    op.create_index(
        op.f("ix_posting_fits_posting_id"), "posting_fits", ["posting_id"],
        unique=False,
    )

    # Postings saved searches (plans 24+29) need the scope in the CHECK.
    with op.batch_alter_table("search_history") as batch:
        batch.drop_constraint("scope_allowed", type_="check")
        batch.create_check_constraint(
            "scope_allowed",
            "scope IN ('catalog', 'rankings', 'universities', 'postings')",
        )


def downgrade() -> None:
    with op.batch_alter_table("search_history") as batch:
        batch.drop_constraint("scope_allowed", type_="check")
        batch.create_check_constraint(
            "scope_allowed",
            "scope IN ('catalog', 'rankings', 'universities')",
        )
    op.drop_index(op.f("ix_posting_fits_posting_id"), table_name="posting_fits")
    op.drop_table("posting_fits")
    op.drop_index(op.f("ix_job_postings_ref"), table_name="job_postings")
    with op.batch_alter_table("job_postings") as batch:
        batch.drop_column("ref")
