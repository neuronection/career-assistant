"""CV intake drafts: one AI-extracted `CvExtract` per source
document, stored for review-first apply.

Nothing here touches the profile: the draft is the review payload; apply
writes only user-confirmed selections. Drafts expire with the document
(CASCADE); a document has at most one live draft (UNIQUE). Applying one
records where each created entity landed (`cv_intake_applied`).
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin


class CvParseDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The review-first extraction draft of one CV source document."""

    __tablename__ = "cv_parse_drafts"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_cv_parse_drafts_document"),
        CheckConstraint(
            "status IN ('pending', 'applied', 'discarded')", name="status_allowed"
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # The validated CvExtract payload.
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
    # Skill-resolution + apply reports (proposed keys, conflicts, unmapped).
    report: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class CvIntakeApplied(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Where a CV import landed: one row per profile entity
    created by applying a document's draft.

    `entity_type` is one of the stable report slugs (`basics`,
    `skills`, `experience_items`, `education_items`, `certifications`,
    `profile_achievements`, `user_interest`, `academics_languages`).
    JSONB-backed sections (basics, academics languages) point at the
    profile row; concrete entities point at their own UUID — so
    `entity_id` is a plain column, not a polymorphic FK. Deleting the
    source document (or the user) removes the trail.
    """

    __tablename__ = "cv_intake_applied"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "entity_type", "entity_id", name="uq_cv_applied_entity"
        ),
        CheckConstraint(
            "entity_type IN ('basics', 'skills', 'experience_items', "
            "'education_items', 'certifications', 'profile_achievements', "
            "'user_interest', 'academics_languages')",
            name="entity_type_allowed",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
