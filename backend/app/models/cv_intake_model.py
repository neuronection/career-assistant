"""CV intake drafts: one AI-extracted `CvExtract` per source
document, stored for review-first apply.

Nothing here touches the profile: the draft is the review payload; apply
writes only user-confirmed selections. Drafts expire with the document
(CASCADE); a document has at most one live draft (UNIQUE).
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
