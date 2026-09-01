"""Experience profile (plan 40): structured experience as typed entities.

An `experience_items` row is one role/project; `experience_skills` binds
its skills with role-in-item and optional self-claimed level (the derived
months live in `app.services.experience_derivation`, never hand-entered);
`experience_achievements` carries metric-bearing outcomes.
`skill_evidence` (plan 42.A) is the per-user evidence ledger every source
(assessments, experience, CV parse) writes — exactly one source per row.
`organizations` is the minimal shared entity (key/name/domain/aliases +
skills-parity lifecycle); plan 39 adds matcher/merge machinery.
"""

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    TZDateTime,
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import (
    ExperienceItemSource,
    ExperienceItemStatus,
    ExperienceKind,
    OrgStatus,
    RoleInItem,
)
from app.models.taxonomy_model import Skill


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Normalized employer/org entity (minimal shape; plan 39 extends)."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'active', 'deprecated')",
            name="status_allowed",
        ),
    )

    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    aliases: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrgStatus.PROPOSED.value
    )
    provenance: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )


class ExperienceItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One structured experience entry (role, project, internship…)."""

    __tablename__ = "experience_items"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('job', 'project', 'internship', 'volunteer', 'freelance')",
            name="kind_allowed",
        ),
        CheckConstraint("status IN ('draft', 'active')", name="status_allowed"),
        Index("ix_experience_items_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExperienceKind.PROJECT.value
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    # Normalized link (plan 39); the raw string stays for audit.
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    org_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    start: Mapped[date] = mapped_column(Date(), nullable=False)
    end: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    open_ended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hours_per_week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    onsite_policy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Prose allowed as *detail* — the structure above is the queryable truth.
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    links: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExperienceItemSource.SELF_REPORT.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExperienceItemStatus.ACTIVE.value
    )

    skills: Mapped[list["ExperienceSkill"]] = relationship(
        back_populates="experience", cascade="all, delete-orphan"
    )
    achievements: Mapped[list["ExperienceAchievement"]] = relationship(
        back_populates="experience", cascade="all, delete-orphan"
    )


class ExperienceSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Skill participation inside one item; months are derived, never stored."""

    __tablename__ = "experience_skills"
    __table_args__ = (
        UniqueConstraint("experience_id", "skill_id", name="uq_experience_skills_pair"),
        CheckConstraint(
            "role_in_item IN ('primary', 'secondary', 'exposure')",
            name="role_allowed",
        ),
        CheckConstraint(
            "level_claim IS NULL OR (level_claim >= 1 AND level_claim <= 10)",
            name="level_claim_range",
        ),
    )

    experience_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experience_items.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role_in_item: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RoleInItem.PRIMARY.value
    )
    level_claim: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_used: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)

    experience: Mapped["ExperienceItem"] = relationship(back_populates="skills")
    skill: Mapped["Skill"] = relationship()


class ExperienceAchievement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A metric-bearing outcome ("cut deploy time 40%") as data."""

    __tablename__ = "experience_achievements"

    experience_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experience_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    # {kind: time_saved|scale|revenue|quality, value, unit} — optional.
    metric: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)

    experience: Mapped["ExperienceItem"] = relationship(back_populates="achievements")


class SkillEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The per-user skill evidence ledger (plan 42.A).

    Exactly one source set per row (CHECK): an assessment run, an
    experience item, or a CV document — plus an optional note. The
    derived level lands on `user_skills`; rows here are the trace.
    """

    __tablename__ = "skill_evidence"
    __table_args__ = (
        CheckConstraint(
            "((CASE WHEN assessment_run_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN experience_item_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN cv_document_id IS NOT NULL THEN 1 ELSE 0 END)) = 1",
            name="one_source_set",
        ),
        Index("ix_skill_evidence_user_skill", "user_id", "skill_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    assessment_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=True
    )
    experience_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("experience_items.id", ondelete="CASCADE"), nullable=True
    )
    cv_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Derived level + confidence at evidence time (display summary).
    level_value: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    experience_item: Mapped[Optional["ExperienceItem"]] = relationship()
