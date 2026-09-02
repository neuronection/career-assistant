"""Assessment template library (plan 37): tests are content, not code.

A template is a pydantic-validated package that compiles onto the
plan-23 engine — phases materialize as ordinary run questions, scoring
rides the existing kind handlers, and results normalize through the
template's own block. Versions are immutable rows (plan 42.B): an edit
publishes version n+1, never mutates content.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TemplateStatus, TemplateVisibility


class AssessmentTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable template version.

    `author_key` carries the uniqueness scope: the author's user id or
    `bank` for system rows — unique (author_key, key, version) is the
    plan-42.B contract (NULL-based uniques are unreliable across
    dialects). `ref` is the short in-instance share code (plan-32
    pattern); `content_hash` is the canonical-JSON sha256 of `content`
    (plan-42.D) verified on export/import.
    """

    __tablename__ = "assessment_templates"
    __table_args__ = (
        UniqueConstraint(
            "author_key", "key", "version", name="uq_assessment_templates_version"
        ),
        CheckConstraint(
            "source IN ('bank', 'ai', 'user', 'imported')", name="source_allowed"
        ),
        CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="visibility_allowed",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name="status_allowed"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_assessment_templates_key", "key"),
    )

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    author_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # `public` exists in the enum but is rejected at write time (plan 15
    # flips it on with the community-sharing phase).
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TemplateVisibility.PRIVATE.value
    )
    audience_stages: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    schema_version: Mapped[int] = mapped_column(default=1, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ref: Mapped[str | None] = mapped_column(String(8), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TemplateStatus.DRAFT.value
    )
    retired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
