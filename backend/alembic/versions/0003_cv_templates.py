"""CV Studio templates: cv_templates + cv_documents.template_id

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-02 23:30:00.000000
"""

from typing import Sequence, Union

import app.models.base
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cv_templates",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("author_key", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("page_size", sa.String(length=10), nullable=False),
        sa.Column("ats_safe", sa.Boolean(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            app.models.base.TZDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            app.models.base.TZDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_cv_templates_author_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cv_templates")),
        sa.UniqueConstraint(
            "author_key", "key", "version", name="uq_cv_templates_version"
        ),
        sa.CheckConstraint(
            "source IN ('bank', 'ai', 'user', 'imported', 'duplicated')",
            name="source_allowed",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')", name="visibility_allowed"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name="status_allowed"
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("page_size IN ('a4', 'letter')", name="page_size_allowed"),
    )
    op.create_index(
        op.f("ix_cv_templates_author_user_id"),
        "cv_templates",
        ["author_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_cv_templates_key"), "cv_templates", ["key"], unique=False)
    with op.batch_alter_table("cv_documents") as batch:
        batch.add_column(sa.Column("template_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_cv_documents_template_id_cv_templates"),
            "cv_templates",
            ["template_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("cv_documents") as batch:
        batch.drop_constraint(
            op.f("fk_cv_documents_template_id_cv_templates"), type_="foreignkey"
        )
        batch.drop_column("template_id")
    op.drop_index(op.f("ix_cv_templates_key"), table_name="cv_templates")
    op.drop_index(op.f("ix_cv_templates_author_user_id"), table_name="cv_templates")
    op.drop_table("cv_templates")
