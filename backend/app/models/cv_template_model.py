"""CV template library: layouts are content, not code.

Mirrors's discipline: versions are immutable rows (unique per
author scope + key + version), content is a pydantic-validated
package validated against the block-kind registry, and `author_key`
('bank' or the author's user id) makes the uniqueness scope dialect-safe.
The deterministic renderer (cv_renderer) is the only render path for
preview, export, and the visual-review loop.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin


class CvTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable CV template version."""

    __tablename__ = "cv_templates"
    __table_args__ = (
        UniqueConstraint(
            "author_key", "key", "version", name="uq_cv_templates_version"
        ),
        CheckConstraint(
            "source IN ('bank', 'ai', 'user', 'imported', 'duplicated')",
            name="source_allowed",
        ),
        CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="visibility_allowed",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name="status_allowed"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("page_size IN ('a4', 'letter')", name="page_size_allowed"),
        Index("ix_cv_templates_key", "key"),
    )

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    author_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # `public` exists in the enum but is rejected at write time —
    # the community-sharing phase flips it on later.
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private"
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    page_size: Mapped[str] = mapped_column(String(10), nullable=False, default="a4")
    # Lint-verified claim: template renders with standard headings and no
    # layout that breaks plain-text extraction.
    ats_safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    content: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
