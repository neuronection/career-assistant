"""Growth toolkit (Phase 28): roadmaps, learning resources.

Roadmap steps adopt curated path steps (21) and/or skill-gap targets;
completing a skill step upserts `user_skills` which re-fits (22) — the
loop closes visibly. Unique (plan_id, position) is DEFERRABLE on
PostgreSQL so a reorder is one transaction (plan 42.B)."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
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


class GrowthPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tracked plan towards one target job."""

    __tablename__ = "growth_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "target_job_id", name="uq_growth_plans_user_job"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )

    steps: Mapped[list["GrowthPlanStep"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class GrowthPlanStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One actionable step; position is plan-scoped and reorderable."""

    __tablename__ = "growth_plan_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "position", name="uq_growth_plan_steps_plan_pos"),
        CheckConstraint(
            "kind IN ('skill', 'experience', 'certification', 'education')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "status IN ('todo', 'doing', 'done', 'skipped')",
            name="status_allowed",
        ),
        CheckConstraint(
            "target_level IS NULL OR (target_level >= 1 AND target_level <= 10)",
            name="target_level_range",
        ),
        Index("ix_growth_plan_steps_plan_id", "plan_id"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("growth_plans.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    skill_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    path_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("career_path_steps.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    target_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    # Completion evidence: the self-reported level for skill steps.
    completed_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    plan: Mapped[GrowthPlan] = relationship(back_populates="steps")


class LearningResource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A learning resource for one skill; AI-suggested rows enter the
    plan-15 moderation queue (status=draft) — never auto-published."""

    __tablename__ = "learning_resources"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('course', 'book', 'cert', 'doc', 'video')",
            name="kind_allowed",
        ),
        CheckConstraint("cost IN ('free', 'freemium', 'paid')", name="cost_allowed"),
        CheckConstraint("status IN ('draft', 'published')", name="status_allowed"),
        Index("ix_learning_resources_skill_id", "skill_id"),
    )

    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    cost: Mapped[str] = mapped_column(String(20), nullable=False, default="free")
    level_target: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="admin")
    notes: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
