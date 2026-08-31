"""External job postings (Phase 26): sources, postings, skill edges,
user interactions. Plan-42 column policy applied: every filtered/sorted
hot field is a real indexed column; money is NUMERIC + ISO currency +
period; JSONB keeps content only."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

# Crockford base32 (no I, L, O, U) — unambiguous when read aloud or typed.
REF_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_posting_ref(length: int = 8) -> str:
    """A fresh 8-char Crockford base32 reference id (plan 32)."""
    import secrets

    return "".join(secrets.choice(REF_ALPHABET) for _ in range(length))


class JobSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An enabled posting source: connector key (data, not code) + config.

    `connector_key` references a registered connector (built-in or plugin);
    config is validated against that connector's `config_model()` at write.
    """

    __tablename__ = "job_sources"
    __table_args__ = (
        CheckConstraint(
            "length(connector_key) BETWEEN 1 AND 80", name="connector_key_present"
        ),
    )

    key: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, nullable=False
    )
    connector_key: Mapped[str] = mapped_column(String(80), nullable=False)
    config: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Connector sync state: etag / last_modified / cursor / watermark.
    sync_state: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class JobPosting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One real vacancy, normalized from a connector and mapped to the
    catalog by skill-ID intersection (never label matching)."""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "external_id", name="uq_postings_source_external"
        ),
        CheckConstraint(
            "status IN ('new', 'mapped', 'expired', 'hidden')",
            name="status_allowed",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="salary_range_sane",
        ),
        Index("ix_postings_status_posted", "status", "posted_at"),
        Index("ix_postings_catalog_job", "catalog_job_id"),
        Index("ix_postings_expires_at", "expires_at"),
        Index("ix_postings_salary_min", "salary_min"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    # Short public reference (Crockford base32, plan 32): the chat + display
    # surface; UUIDs stay internal PKs. Generated on insert, unique.
    ref: Mapped[str] = mapped_column(
        String(8),
        unique=True,
        nullable=False,
        default=lambda: generate_posting_ref(),
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    org: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    location: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # Plan-42.C hot fields as columns (postings is the high-volume table).
    seniority: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, index=True
    )
    employment_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    contract_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    onsite_policy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    work_hours: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    hours_per_week_min: Mapped[Optional[float]] = mapped_column(nullable=True)
    hours_per_week_max: Mapped[Optional[float]] = mapped_column(nullable=True)
    travel_class: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    education_level: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    salary_min: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    salary_max: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    salary_period: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Canonical-JSON sha256 of the normalized content — re-sync dedup.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    # Deep-extraction result (plan 31): validated PostingExtract dump with
    # low-confidence fields suppressed; empty until the queued pass runs.
    extract: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    # Prompt/model version that produced `extract` — NULL = never extracted;
    # a lower value than the current EXTRACT_VERSION flags re-extraction
    # (plan-16 staleness pattern).
    extract_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # A field fell below the confidence threshold — moderation attention.
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Only unmapped extras land here (39's declarative feature map consumes).
    posting_facts: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")

    # Mapping result: skill-ID intersection (or AI/manual) onto the catalog.
    catalog_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    catalog_job: Mapped[Optional["Job"]] = relationship()  # noqa: F821
    mapping_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mapping_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mapping_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PostingSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Posting ↔ skill requirement: FK join, never text (the matching edge).

    `required_level`/`priority` exist from day one and are filled by
    plan-31 deep extraction (NULL = not yet extracted)."""

    __tablename__ = "posting_skills"
    __table_args__ = (
        UniqueConstraint(
            "posting_id", "skill_id", name="uq_posting_skills_posting_skill"
        ),
        CheckConstraint(
            "required_level IS NULL OR (required_level >= 1 AND required_level <= 10)",
            name="required_level_range",
        ),
        Index("ix_posting_skills_skill_id", "skill_id"),
    )

    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    evidence: Mapped[str] = mapped_column(
        String(20), nullable=False, default="explicit"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    required_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)


class PostingInteraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user posting state — the single source of posting-state truth
    (mirrors plan-24 semantics; stage is plan-28's pipeline)."""

    __tablename__ = "posting_interactions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "posting_id", name="uq_posting_interactions_user_posting"
        ),
        Index("ix_posting_interactions_posting_id", "posting_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    saved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hidden_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_via_url: Mapped[str] = mapped_column(
        String(1000), nullable=False, default=""
    )
    stage: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PostingFit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cached per-posting match score (plan 32): deterministic dimensions
    over extracted posting data; `inputs_hash` detects staleness (plan-16
    pattern — recompute lazily on view, never silently blended)."""

    __tablename__ = "posting_fits"
    __table_args__ = (
        UniqueConstraint("user_id", "posting_id", name="uq_posting_fits_user_posting"),
        Index("ix_posting_fits_posting_id", "posting_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    breakdown: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    # Canonical-JSON sha256 of every input (skills, weights, profile
    # basics, extract_version, posted_at) — mismatch ⇒ stale ⇒ recompute.
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
