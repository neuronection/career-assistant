import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    TZDateTime,
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered user — family-normative `users` (identity-auth §5)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "oidc_issuer", "oidc_subject", name="uq_users_oidc_issuer_subject"
        ),
    )

    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    # NULLABLE (§5): NULL ⇒ password login refused for that row (DIM owner
    # until a password is set); otherwise bcrypt ≥12 rounds (nx_auth).
    password_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    full_name: Mapped[str] = mapped_column(nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Brute-force protection: consecutive failures lock the account until
    # locked_until passes (or an admin unlocks).
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )
    # Bumped to invalidate every outstanding token ("sign out everywhere").
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # OIDC link (§14, present from day one); unique as a pair above.
    oidc_issuer: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    oidc_subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    profiles: Mapped[list["Profile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Profile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A coached person's structured profile (identity-auth §5/§6).

    Family-normative 1:N columns (`user_id` FK, `name`, `is_default`,
    `preferences`, timestamps) plus career's product shape: every section
    is pydantic-validated StructuredJSON on the profile row (§6
    "product meaning"). Exactly one `is_default` per user is
    service-enforced (`app.services.profiles_service`).
    """

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(120), nullable=False, default="Default", server_default="Default"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # Optional profile accent (study's shared ProfileSwitcher swatch).
    color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Last-used tracking (§6: the last-used profile is remembered per
    # user) — the desktop binding fallback sorts on it.
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
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
    # Scoring-weight preferences (22) live as a structured section.
    preferences: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    constraints: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    ai_summary: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    # Profile photo: a documents row (kind=photo); NULL = no photo.
    photo_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="profiles")


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
    # When False the user opted out: apply_derivation never touches or
    # re-creates this row (self_report rows ignore it — always owned).
    derive_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    # Tombstone: the user deleted this row. apply_derivation never
    # re-creates it and no surface renders it (re-adding the skill via
    # the profiles pages makes a fresh row).
    hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    skill = relationship("Skill")
