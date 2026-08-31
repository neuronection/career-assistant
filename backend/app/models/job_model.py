import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.taxonomy_model import InterestTag, Skill
    from app.models.university_model import JobDepartmentLink


class JobFamily(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Job family tree node (adjacency + materialised path)."""

    __tablename__ = "job_families"

    key: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("job_families.id", ondelete="CASCADE"), nullable=True
    )
    path: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", index=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    children: Mapped[list["JobFamily"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped[Optional["JobFamily"]] = relationship(
        back_populates="children", remote_side="JobFamily.id"
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="family")


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A job in the catalog with fully structured attributes."""

    __tablename__ = "jobs"

    code: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_families.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    short_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="published", index=True
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="seed", index=True
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    attributes: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    # Curated outbound links [{label, url, kind}] (Phase 24) — admin-edited
    # catalog metadata; AI suggestions only ever reach the moderation queue.
    links: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    ai_metadata: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)

    family: Mapped[JobFamily] = relationship(back_populates="jobs")
    skill_links: Mapped[list["JobSkill"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    tag_links: Mapped[list["JobTag"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    relations_from: Mapped[list["JobRelation"]] = relationship(
        back_populates="from_job",
        cascade="all, delete-orphan",
        foreign_keys="JobRelation.from_job_id",
    )
    relations_to: Mapped[list["JobRelation"]] = relationship(
        back_populates="to_job",
        cascade="all, delete-orphan",
        foreign_keys="JobRelation.to_job_id",
    )
    department_links: Mapped[list["JobDepartmentLink"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobRelation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Typed, weighted edge between two jobs in the relation graph."""

    __tablename__ = "job_relations"
    __table_args__ = (
        UniqueConstraint(
            "from_job_id", "to_job_id", "relation_type", name="uq_job_relation_edge"
        ),
        Index("ix_job_relations_from", "from_job_id"),
        Index("ix_job_relations_to", "to_job_id"),
    )

    from_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    to_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="seed", index=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    from_job: Mapped[Job] = relationship(
        back_populates="relations_from", foreign_keys=[from_job_id]
    )
    to_job: Mapped[Job] = relationship(
        back_populates="relations_to", foreign_keys=[to_job_id]
    )


class JobSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Job ↔ skill requirement: FK join, never plain text (Phase 21)."""

    __tablename__ = "job_skills"
    __table_args__ = (
        UniqueConstraint("job_id", "skill_id", name="uq_job_skills_job_skill"),
        CheckConstraint(
            "required_level >= 1 AND required_level <= 10",
            name="required_level_range",
        ),
        Index("ix_job_skills_skill_id", "skill_id"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    required_level: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    importance: Mapped[str] = mapped_column(String(20), nullable=False, default="core")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="seed")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")

    job: Mapped[Job] = relationship(back_populates="skill_links")
    skill: Mapped["Skill"] = relationship()


class JobTag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Job ↔ interest-tag link (replaces attributes.interests JSONB)."""

    __tablename__ = "job_tags"
    __table_args__ = (
        UniqueConstraint("job_id", "interest_tag_id", name="uq_job_tags_job_tag"),
        Index("ix_job_tags_interest_tag_id", "interest_tag_id"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    interest_tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interest_tags.id", ondelete="RESTRICT"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="seed")

    job: Mapped[Job] = relationship(back_populates="tag_links")
    tag: Mapped["InterestTag"] = relationship()
