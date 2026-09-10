"""Profile photo reference: profiles.photo_document_id.

Revision ID: 0009_profile_photo
Revises: 0008_ai_model_reasoning_effort
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(
            sa.Column("photo_document_id", sa.Uuid(), nullable=True),
        )
        batch.create_foreign_key(
            "fk_profiles_photo_document",
            "documents",
            ["photo_document_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_constraint("fk_profiles_photo_document", type_="foreignkey")
        batch.drop_column("photo_document_id")
