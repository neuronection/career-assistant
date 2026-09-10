"""Agent skill packs: the ai_skill_packs table plus
pack_key/pack_version provenance columns on ai_generations."""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_skill_packs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("task", sa.String(length=60), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "author_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("author_key", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "author_key", "key", "version", name="uq_ai_skill_packs_version"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name="status_allowed"
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index(
        "ix_ai_skill_packs_task_status", "ai_skill_packs", ["task", "status"]
    )
    op.create_index(
        "ix_ai_skill_packs_author_user_id", "ai_skill_packs", ["author_user_id"]
    )
    op.add_column(
        "ai_generations",
        sa.Column("pack_key", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "ai_generations",
        sa.Column("pack_version", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_generations", "pack_version")
    op.drop_column("ai_generations", "pack_key")
    op.drop_index(
        "ix_ai_skill_packs_author_user_id", table_name="ai_skill_packs"
    )
    op.drop_index("ix_ai_skill_packs_task_status", table_name="ai_skill_packs")
    op.drop_table("ai_skill_packs")
