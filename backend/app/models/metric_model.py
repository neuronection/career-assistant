"""Metric dimension registry + per-user metric profile.

Every measurable career attribute beyond skills is a first-class,
normalized dimension with a declared group, measurement sources and
consumers — matching, assessments, filters and UI speak one metric
language. `user_metric_profile` mirrors the `user_skills` provenance
pattern (source, confidence, evidence) with a unique
(user_id, dimension_key) per.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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

if TYPE_CHECKING:
    from app.models.user_model import User


class MetricDimension(TimestampMixin, UUIDPrimaryKeyMixin, Base):
    """Curated registry row: one dimension of the metric language."""

    __tablename__ = "metric_dimensions"

    key: Mapped[str] = mapped_column(
        String(60), unique=True, index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    group: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    # Kept for vector dimensions later; every current dimension is scalar.
    scale: Mapped[str] = mapped_column(String(10), nullable=False, default="scalar")
    reverse_score: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Which assessment kinds / profile sections / behaviors feed it and
    # which consumers read it — declared, not implied.
    sources: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    consumers: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )

    __table_args__ = (
        CheckConstraint(
            "\"group\" IN ('interest', 'value', 'workstyle', 'constraint', 'aptitude')",
            name="group_allowed",
        ),
        CheckConstraint("scale IN ('scalar', 'vector')", name="scale_allowed"),
    )


class SkillTransferability(TimestampMixin, UUIDPrimaryKeyMixin, Base):
    """Derived catalog metric: how widely one skill transfers.

    `share` = families containing the skill / families containing any
    published job. Recomputed deterministically from the job_skills join
    graph on catalog change; never hand-edited, never user-specific.
    """

    __tablename__ = "skill_transferability"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    family_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_families: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    share: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)

    __table_args__ = (CheckConstraint("share >= 0 AND share <= 1", name="share_range"),)


class UserMetricProfile(TimestampMixin, UUIDPrimaryKeyMixin, Base):
    """One measured dimension value for a user."""

    __tablename__ = "user_metric_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dimension_key: Mapped[str] = mapped_column(
        ForeignKey("metric_dimensions.key", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    value: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.6, server_default="0.6"
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="self_report"
    )
    evidence: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)

    user: Mapped["User"] = relationship(viewonly=True)
    dimension: Mapped[MetricDimension] = relationship(viewonly=True)

    __table_args__ = (
        UniqueConstraint("user_id", "dimension_key", name="user_dimension"),
        CheckConstraint("value >= 1 AND value <= 10", name="value_range"),
        CheckConstraint(
            "source IN ('self_report', 'assessment', 'behavior', 'derived')",
            name="source_allowed",
        ),
        Index("ix_user_metric_user", "user_id", "dimension_key"),
    )
