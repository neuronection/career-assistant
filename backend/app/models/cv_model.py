"""CV Studio core records.

A `cv_documents` row is one living CV (resume or cover letter): its editor
state autosaves into `working_content`, while `cv_versions` rows are
immutable compiled snapshots (unique per version, canonical content hash,
never edited — restore/duplicate create new rows). Source files stay on the
generic `documents` table (kind="cv") so the reserved
`skill_evidence.cv_document_id` FK keeps one canonical file
entity.
"""

import uuid
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class CvDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One living CV document."""

    __tablename__ = "cv_documents"
    __table_args__ = (
        CheckConstraint("kind IN ('resume', 'cover_letter')", name="kind_allowed"),
        CheckConstraint(
            "status IN ('draft', 'final', 'archived')", name="status_allowed"
        ),
        CheckConstraint("page_size IN ('a4', 'letter')", name="page_size_allowed"),
        CheckConstraint("max_pages >= 1 AND max_pages <= 10", name="max_pages_range"),
        Index("ix_cv_documents_user_updated", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="resume")
    target_posting_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )
    # Template choice; NULL = renderer default layout.
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("cv_templates.id", ondelete="SET NULL"), nullable=True
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    page_size: Mapped[str] = mapped_column(String(10), nullable=False, default="a4")
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # The only mutable content column — autosaved editor state.
    working_content: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    # Per-CV context selection: {mode, include[], exclude[]}.
    context: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    # Per-CV profile photo; NULL = profile default.
    photo_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )


class CvVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable compiled snapshot of a CV."""

    __tablename__ = "cv_versions"
    __table_args__ = (
        UniqueConstraint(
            "cv_document_id", "version", name="uq_cv_versions_doc_version"
        ),
        CheckConstraint(
            "created_by IN ('user_save', 'ai_apply', 'export', 'restore', 'duplicate')",
            name="created_by_allowed",
        ),
        Index("ix_cv_versions_doc_version", "cv_document_id", "version"),
    )

    cv_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cv_documents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
    context_resolution: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(20), nullable=False)
