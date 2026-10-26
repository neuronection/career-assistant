"""Job radar: the profile's saved job-search configuration (plan 129 P4).

One row per profile — the "configure once" promise. The radar is a saved
filter set consumed by Explore/feed defaults (4a) and, from 4b, by the
scheduler's post-sync matching for cadence digests. `source_keys` is
schema-ready and deliberately unconsumed until source-follows land:
NULL/empty = follow every instance source.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import RadarCadence

_SOURCE_KEYS_MAX = 24
_KEYWORDS_MAX = 24
_LOCATIONS_MAX = 12
_SENIORITY_MAX = 8


def _in_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + value + "'" for value in values)
    return f"{column} IN ({quoted})"


class JobRadar(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The profile's saved job-search configuration (1:1, opt-in)."""

    __tablename__ = "job_radars"
    __table_args__ = (
        CheckConstraint(
            _in_check("cadence", tuple(cadence.value for cadence in RadarCadence)),
            name="cadence_allowed",
        ),
        CheckConstraint(
            "onsite_policy IS NULL OR onsite_policy IN ('onsite', 'hybrid', 'remote')",
            name="onsite_policy_allowed",
        ),
        UniqueConstraint("profile_id", name="uq_job_radars_profile_id"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    keywords: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    locations: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    seniority: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    onsite_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    salary_min_annual: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    source_keys: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    cadence: Mapped[str] = mapped_column(String(20), nullable=False, default=RadarCadence.OFF.value)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
