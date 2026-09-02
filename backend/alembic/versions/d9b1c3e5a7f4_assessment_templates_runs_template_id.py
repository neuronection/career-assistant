"""assessment_templates + runs.template_id FK (Phase 37)

Revision ID: d9b1c3e5a7f4
Revises: c3a9e7d1f5b2
Create Date: 2026-09-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "d9b1c3e5a7f4"
down_revision: Union[str, None] = "c3a9e7d1f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assessment_templates",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("author_key", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="user"),
        sa.Column("visibility", sa.String(length=20), nullable=False,
                  server_default="private"),
        sa.Column("audience_stages", StructuredJSON, nullable=False,
                  server_default=sa.text("'[]'")),
        sa.Column("language", sa.String(length=10), nullable=False,
                  server_default="en"),
        sa.Column("schema_version", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("ref", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="draft"),
        sa.Column("retired", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("content", StructuredJSON, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_templates")),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["users.id"],
            name=op.f("fk_assessment_templates_author_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("author_key", "key", "version",
                            name=op.f("uq_assessment_templates_version")),
        sa.UniqueConstraint("ref", name=op.f("uq_assessment_templates_ref")),
        sa.CheckConstraint(
            "source IN ('bank', 'ai', 'user', 'imported')",
            name=op.f("ck_assessment_templates_source_allowed"),
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name=op.f("ck_assessment_templates_visibility_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name=op.f("ck_assessment_templates_status_allowed"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_assessment_templates_version_positive")
        ),
    )
    op.create_index(
        op.f("ix_assessment_templates_key"), "assessment_templates", ["key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_assessment_templates_author_user_id"), "assessment_templates",
        ["author_user_id"], unique=False,
    )

    with op.batch_alter_table("assessment_runs") as batch:
        batch.create_foreign_key(
            op.f("fk_assessment_runs_template_id_assessment_templates"),
            "assessment_templates",
            ["template_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("assessment_runs") as batch:
        batch.drop_constraint(
            op.f("fk_assessment_runs_template_id_assessment_templates"),
            type_="foreignkey",
        )
    op.drop_index(op.f("ix_assessment_templates_author_user_id"),
                  table_name="assessment_templates")
    op.drop_index(op.f("ix_assessment_templates_key"),
                  table_name="assessment_templates")
    op.drop_table("assessment_templates")
