"""Experience profile: structured experience as typed entities.

An `experience_items` row is one role/project; `experience_skills` binds
its skills with role-in-item and optional self-claimed level (the derived
months live in `app.services.profile.experience_derivation`, never hand-entered);
`experience_achievements` carries metric-bearing outcomes.
`skill_evidence` is the per-user evidence ledger every source
(assessments, experience, CV parse) writes — exactly one source per row.
`organizations` is the minimal shared entity (key/name/domain +
skills-parity lifecycle); the matcher machinery (alias rows, exclusions,
the gray-band pair queue and merge suggestions) lives beside it.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import (
    ExperienceItemSource,
    ExperienceItemStatus,
    ExperienceKind,
    OrgAliasSource,
    OrgAliasState,
    OrgExclusionSource,
    OrgPairStatus,
    OrgStatus,
    OrgSuggestionStatus,
    RoleInItem,
)
from app.models.taxonomy_model import Skill


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Normalized employer/org entity (minimal shape; extends)."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'active', 'deprecated')",
            name="status_allowed",
        ),
    )

    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrgStatus.PROPOSED.value
    )
    provenance: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    name_key: Mapped[str] = mapped_column(String(200), nullable=False, default="", index=True)
    initials_key: Mapped[str] = mapped_column(String(200), nullable=False, default="", index=True)


class OrganizationAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One known name variant of an organization (the matcher's memory).

    `alias_key` is the normalized comparison form; a claimed key may live on
    two orgs (collisions like "PG") — exact lookups tie-break in the service.
    """

    __tablename__ = "organization_aliases"
    __table_args__ = (
        UniqueConstraint("org_id", "alias_key"),
        CheckConstraint(
            "source IN ('manual', 'learned', 'llm', 'url', 'merge', 'legacy')",
            name="source_allowed",
        ),
        CheckConstraint("state IN ('active', 'excluded')", name="state_allowed"),
        Index("ix_organization_aliases_alias_key", "alias_key"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    alias_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(
        String(12), nullable=False, default=OrgAliasSource.LEARNED.value
    )
    state: Mapped[str] = mapped_column(
        String(12), nullable=False, default=OrgAliasState.ACTIVE.value
    )
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")


class OrganizationMatchExclusion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A matcher veto: `org_id` NULL marks a label as not-a-company, set marks
    a never-link pair. Consulted before every fuzzy/LLM step."""

    __tablename__ = "organization_match_exclusions"
    __table_args__ = (
        UniqueConstraint("label_key", "org_id"),
        Index(
            "ux_organization_match_exclusions_global",
            "label_key",
            unique=True,
            postgresql_where=text("org_id IS NULL"),
            sqlite_where=text("org_id IS NULL"),
        ),
        CheckConstraint("source IN ('manual', 'llm', 'dismiss', 'seed')", name="source_allowed"),
    )

    label: Mapped[str] = mapped_column(String(200), nullable=False)
    label_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    source: Mapped[str] = mapped_column(
        String(12), nullable=False, default=OrgExclusionSource.MANUAL.value
    )
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")


class OrganizationMatchPair(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Gray-band queue: one ambiguous label vs one candidate, awaiting triage.

    The stored verdict is the audit of the (paid-for) arbiter result; rows
    resolve into a link, a creation or a merge suggestion and are never
    re-asked.
    """

    __tablename__ = "organization_match_pairs"
    __table_args__ = (
        UniqueConstraint("label_key", "org_id"),
        CheckConstraint("status IN ('pending', 'resolved', 'dropped')", name="status_allowed"),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('same', 'different', 'uncertain')",
            name="verdict_allowed",
        ),
        Index("ix_organization_match_pairs_status", "status"),
    )

    label: Mapped[str] = mapped_column(String(200), nullable=False)
    label_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=OrgPairStatus.PENDING.value
    )
    verdict: Mapped[str | None] = mapped_column(String(12), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_by: Mapped[str] = mapped_column(String(120), nullable=False, default="")


class OrganizationMergeSuggestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A human decision on one near-miss pair: accept merges, dismiss excludes."""

    __tablename__ = "organization_merge_suggestions"
    __table_args__ = (
        UniqueConstraint("org_a", "org_b", "label_key"),
        CheckConstraint("status IN ('open', 'accepted', 'dismissed')", name="status_allowed"),
        CheckConstraint("org_a <> org_b", name="distinct_orgs"),
    )

    org_a: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_b: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    label_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    evidence: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=OrgSuggestionStatus.OPEN.value
    )
    decided_by: Mapped[str] = mapped_column(String(120), nullable=False, default="")


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
    # Normalized link; the raw string stays for audit.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    org_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Optional: projects may be undated (note #15: not all kinds mandate a
    # start date) — jobs/internships still require one at the API layer.
    start: Mapped[date | None] = mapped_column(Date(), nullable=True)
    end: Mapped[date | None] = mapped_column(Date(), nullable=True)
    open_ended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hours_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    onsite_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
        back_populates="experience",
        cascade="all, delete-orphan",
        # Deterministic collection order on every dialect: CI SQLite
        # returns arbitrary row order without it (plan-102 anchored
        # collection_edits append in op order — the workspace + CV
        # renderers trust this ordering).
        order_by="ExperienceSkill.created_at",
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
    level_claim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_used: Mapped[date | None] = mapped_column(Date(), nullable=True)

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
    metric: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)

    experience: Mapped["ExperienceItem"] = relationship(back_populates="achievements")


class SkillEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The per-user skill evidence ledger.

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
    assessment_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=True
    )
    experience_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("experience_items.id", ondelete="CASCADE"), nullable=True
    )
    cv_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Derived level + confidence at evidence time (display summary).
    level_value: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=lambda: datetime.now(UTC)
    )

    experience_item: Mapped[Optional["ExperienceItem"]] = relationship()
