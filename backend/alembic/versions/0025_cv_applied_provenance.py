"""CV import provenance: `cv_intake_applied` records where each entity
created by applying a CV draft landed (per-CV "view what was imported"
trail). No data migration — the table starts empty; earlier imports
keep their apply reports as before."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cv_intake_applied",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "document_id", "entity_type", "entity_id", name="uq_cv_applied_entity"
        ),
        sa.CheckConstraint(
            "entity_type IN ('basics', 'skills', 'experience_items', "
            "'education_items', 'certifications', 'profile_achievements', "
            "'user_interest', 'academics_languages')",
            name="entity_type_allowed",
        ),
    )
    op.create_index("ix_cv_intake_applied_user_id", "cv_intake_applied", ["user_id"])
    op.create_index(
        "ix_cv_intake_applied_document_id", "cv_intake_applied", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_cv_intake_applied_document_id", table_name="cv_intake_applied")
    op.drop_index("ix_cv_intake_applied_user_id", table_name="cv_intake_applied")
    op.drop_table("cv_intake_applied")
