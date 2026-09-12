"""Delete CV-evidence rows with their document.

`skill_evidence.cv_document_id` was `ondelete SET NULL`, but the
`ck_skill_evidence_one_source_set` CHECK requires exactly one non-null
source — deleting the document wiped the only source and the CHECK
rejected the update. The FK now matches the other two sources and
cascades, so document deletion removes its evidence rows.
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("skill_evidence") as batch:
        batch.drop_constraint(
            "fk_skill_evidence_cv_document_id_documents",
            type_="foreignkey",
        )
        batch.create_foreign_key(
            "fk_skill_evidence_cv_document_id_documents",
            "documents",
            ["cv_document_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("skill_evidence") as batch:
        batch.drop_constraint(
            "fk_skill_evidence_cv_document_id_documents",
            type_="foreignkey",
        )
        batch.create_foreign_key(
            "fk_skill_evidence_cv_document_id_documents",
            "documents",
            ["cv_document_id"],
            ["id"],
            ondelete="SET NULL",
        )
