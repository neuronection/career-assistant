"""CV-data profile entities: education, certifications, awards.

These fill the CV-relevant gaps in the structured profile — everything the
CV builder (47) and intake (45) target as first-class context sources. All
three carry `source` (same values as experience items) so CV-parse drafts
land with provenance, and a draft/active status for review flows.
"""

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

_STATUS_ALLOWED = "status IN ('draft', 'active')"
_SOURCE_ALLOWED = "source IN ('self_report', 'cv_parse', 'assessment', 'import')"


class EducationItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One structured education entry (multi-entry, month precision)."""

    __tablename__ = "education_items"
    __table_args__ = (
        CheckConstraint(_STATUS_ALLOWED, name="status_allowed"),
        CheckConstraint(_SOURCE_ALLOWED, name="source_allowed"),
        Index("ix_education_items_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    # Raw string kept for audit.
    org_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    program: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    level: Mapped[str] = mapped_column(
        String(30), nullable=False, default="high_school"
    )
    start: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    end: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    in_progress: Mapped[bool] = mapped_column(nullable=False, default=False)
    grade_band: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    focus_subjects: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="self_report"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Optional enrichment into the universities catalog; the
    # free-text institution/program stay the CV-render source of truth.
    university_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("universities.id", ondelete="SET NULL"), nullable=True
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )


class Certification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A certification or license with optional expiry."""

    __tablename__ = "certifications"
    __table_args__ = (
        CheckConstraint(_STATUS_ALLOWED, name="status_allowed"),
        CheckConstraint(_SOURCE_ALLOWED, name="source_allowed"),
        Index("ix_certifications_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    issued: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    expires: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    credential_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    link: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="self_report"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class ProfileAchievement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Awards, honors, publications and extracurricular highlights."""

    __tablename__ = "profile_achievements"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('award', 'honor', 'publication', 'extracurricular')",
            name="kind_allowed",
        ),
        CheckConstraint(_STATUS_ALLOWED, name="status_allowed"),
        CheckConstraint(_SOURCE_ALLOWED, name="source_allowed"),
        Index("ix_profile_achievements_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="award")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="self_report"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
