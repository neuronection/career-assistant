import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered student."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    full_name: Mapped[str] = mapped_column(nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Brute-force protection: consecutive failures lock the account until
    # locked_until passes (or an admin unlocks).
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Bumped to invalidate every outstanding JWT ("sign out everywhere").
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    profile: Mapped["Profile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Profile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Structured student profile; every section is pydantic-validated StructuredJSON."""

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    basics: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    academics: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    hobbies: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    likes: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    dislikes: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    aspirations: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    work_preferences: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    # Experience items (22; promoted to tables by plan 40) + scoring weight
    # preferences live as structured sections until their phases promote them.
    experience: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    preferences: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    constraints: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    ai_summary: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)

    user: Mapped["User"] = relationship(back_populates="profile")


class UserInterest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """User ↔ interest-tag link with 1–5 weight (replaces profile JSONB)."""

    __tablename__ = "user_interests"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "interest_tag_id", name="uq_user_interests_user_tag"
        ),
        CheckConstraint("weight >= 1 AND weight <= 5", name="weight_range"),
        Index("ix_user_interests_interest_tag_id", "interest_tag_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    interest_tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interest_tags.id", ondelete="RESTRICT"), nullable=False
    )
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="self")
    # Display-only summary; real evidence lives in typed tables (Phase 42).
    evidence: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)

    tag = relationship("InterestTag")


class UserSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """User's claimed skill level on the 1–10 anchored scale (Phase 21)."""

    __tablename__ = "user_skills"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", name="uq_user_skills_user_skill"),
        CheckConstraint("level >= 1 AND level <= 10", name="level_range"),
        Index("ix_user_skills_skill_id", "skill_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="self_report"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    skill = relationship("Skill")
