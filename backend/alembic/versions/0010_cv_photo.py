"""Per-CV profile photo: cv_documents.photo_document_id.

A CV may point at ANY of the user's photo documents (the gallery);
NULL means "follow the profile default" (profiles.photo_document_id).
Deleting a photo SET NULLs both references — nothing breaks.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cv_documents") as batch:
        batch.add_column(
            sa.Column("photo_document_id", sa.Uuid(), nullable=True),
        )
        batch.create_foreign_key(
            "fk_cv_documents_photo_document",
            "documents",
            ["photo_document_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("cv_documents") as batch:
        batch.drop_constraint("fk_cv_documents_photo_document", type_="foreignkey")
        batch.drop_column("photo_document_id")
