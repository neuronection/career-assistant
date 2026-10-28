"""External job postings (Phase 26): sources, postings, skill edges,
user interactions. column policy applied: every filtered/sorted
hot field is a real indexed column; money is NUMERIC + ISO currency +
period; JSONB keeps content only."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    TZDateTime,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import HealthStatus, SourceKind, SourceQueryMode

# Crockford base32 (no I, L, O, U) — unambiguous when read aloud or typed.
REF_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

if TYPE_CHECKING:
    from app.models.job_model import Job


def generate_posting_ref(length: int = 8) -> str:
    """A fresh 8-char Crockford base32 reference id."""
    import secrets

    return "".join(secrets.choice(REF_ALPHABET) for _ in range(length))


class JobSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An enabled posting source: connector key (data, not code) + config.

    `connector_key` references a registered connector (built-in or plugin);
    config is validated against that connector's `config_model()` at write.
    """

    __tablename__ = "job_sources"
    __table_args__ = (
        CheckConstraint("length(connector_key) BETWEEN 1 AND 80", name="connector_key_present"),
        CheckConstraint(
            "kind IN ('posting', 'market', 'university', 'search', 'webhook_in')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "last_status IN ('ok', 'degraded', 'failed')",
            name="last_status_allowed",
        ),
        CheckConstraint(
            "query_mode IN ('static', 'radar')",
            name="query_mode_allowed",
        ),
        CheckConstraint(
            "query_batch_size BETWEEN 1 AND 3",
            name="query_batch_size_allowed",
        ),
    )

    key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    connector_key: Mapped[str] = mapped_column(String(80), nullable=False)
    # What this source feeds: postings today, wider data families later.
    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SourceKind.POSTING.value,
        server_default=SourceKind.POSTING.value,
    )
    # Scheduler trigger this source runs under (NULL = manual only).
    schedule_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_status: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default=HealthStatus.OK.value,
        server_default=HealthStatus.OK.value,
    )
    config: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    # Secret slots (D19/INV-4): slot id -> atrest-sealed value; never
    # plaintext, never returned by APIs (mask/hint only).
    secrets: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    # Connector sync state: etag / last_modified / cursor / watermark.
    sync_state: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    # Where the search query comes from (plan 130): static config vs the
    # merged job-radar overlay.
    query_mode: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default=SourceQueryMode.STATIC.value,
        server_default=SourceQueryMode.STATIC.value,
    )
    # The merged-query artifact (plan 130): {query, provenance, radar_ids,
    # curated, computed_at, radar_fp} — rebuilt on radar change, read by
    # sync as the call-time query overlay.
    query_cache: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    # How many rotating role groups one sync searches (plan 130b batch
    # policy): 1 = today's single focused query; executed strictly
    # sequentially with a jittered interval the connector enforces.
    query_batch_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class SourceRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One ingestion attempt for a job source (plan 134 run ledger).

    The management page's history: when it ran, under which trigger, how
    long it took, what landed and why it did not. One row per
    ``sync_source`` call — job-level retries are honest extra attempts."""

    __tablename__ = "source_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('manual', 'scheduled')", name="trigger_allowed"),
        CheckConstraint(
            "status IN ('running', 'ok', 'degraded', 'failed', 'skipped')",
            name="status_allowed",
        ),
        Index("ix_source_runs_source_started", "source_id", "started_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(
        String(12), nullable=False, default="scheduled", server_default="scheduled"
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_synced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    report: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)


class JobPosting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One real vacancy, normalized from a connector and mapped to the
    catalog by skill-ID intersection (never label matching)."""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_postings_source_external"),
        CheckConstraint(
            "status IN ('new', 'mapped', 'expired', 'hidden')",
            name="status_allowed",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="salary_range_sane",
        ),
        CheckConstraint(
            "salary_basis IS NULL OR salary_basis IN ('gross', 'net')",
            name="salary_basis_allowed",
        ),
        CheckConstraint(
            "org_match_state IS NULL OR org_match_state IN ('linked', 'pending', 'rejected')",
            name="org_match_state_allowed",
        ),
        Index("ix_postings_status_posted", "status", "posted_at"),
        Index("ix_postings_detail", "source_id", "detail_fetched_at"),
        Index("ix_postings_catalog_job", "catalog_job_id"),
        Index("ix_postings_expires_at", "expires_at"),
        Index("ix_postings_salary_min", "salary_min"),
        Index("ix_postings_org_match_state", "org_match_state"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    # Short public reference (Crockford base32): the chat + display
    # surface; UUIDs stay internal PKs. Generated on insert, unique.
    ref: Mapped[str] = mapped_column(
        String(8),
        unique=True,
        nullable=False,
        default=lambda: generate_posting_ref(),
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # Raw org label (audit); the normalized entity is `org_id`.
    org: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    org_match: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    # Queryable projection of org_match.state (JSONB is not filterable
    # cross-dialect) — kept in sync by the matcher and the triage service.
    org_match_state: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    location: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # hot fields as columns (postings is the high-volume table).
    seniority: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    employment_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contract_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    onsite_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    work_hours: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hours_per_week_min: Mapped[float | None] = mapped_column(nullable=True)
    hours_per_week_max: Mapped[float | None] = mapped_column(nullable=True)
    travel_class: Mapped[str | None] = mapped_column(String(60), nullable=True)
    education_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    salary_basis: Mapped[str | None] = mapped_column(String(10), nullable=True)
    salary_normalized_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_normalized_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    # Canonical-JSON sha256 of the normalized content — re-sync dedup.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    # Deep-extraction result: validated PostingExtract dump with
    # low-confidence fields suppressed; empty until the queued pass runs.
    extract: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    # Prompt/model version that produced `extract` — NULL = never extracted;
    # a lower value than the current EXTRACT_VERSION flags re-extraction
    # .
    extract_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A field fell below the confidence threshold — moderation attention.
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Detail enrichment: NULL = the job description page was never
    # fetched; attempts counts tried fetches (a permanently failing id
    # stops being queued).
    detail_fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    detail_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Only unmapped extras land here (39's declarative feature map consumes).
    posting_facts: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")

    # Mapping result: skill-ID intersection (or AI/manual) onto the catalog.
    catalog_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    catalog_job: Mapped[Optional["Job"]] = relationship()
    mapping_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mapping_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    mapping_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PostingChange(UUIDPrimaryKeyMixin, Base):
    """Append-only posting mutation journal (plan 142): one row per real
    change, with its actor, operation parameters, duration and capped
    field diff.

    Written ONLY through `PostingChangeJournal.record` in the SAME
    transaction as the mutation — the digest gate keeps no-op writes out.
    `actor_ref`/`operation` carry ids and knobs only; prompt/response
    content lives in `ai_generations`/`job_postings.raw`, never here."""

    __tablename__ = "posting_changes"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ("
            "'sync_run', 'extract_llm', 'detail_fetch', 'company_match', "
            "'retag', 'manual', 'expiry')",
            name="actor_kind_allowed",
        ),
        CheckConstraint("outcome IN ('ok', 'partial', 'error')", name="outcome_allowed"),
        Index("ix_posting_changes_posting_occurred", "posting_id", "occurred_at"),
    )

    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=lambda: datetime.now(UTC)
    )
    actor_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # ids and knobs only: run_id (source_runs.id), job_id
    # (background_jobs.id = ai_generations.run_id), ai_generation_id,
    # user_id, mode/model/prompt_version, trigger.
    actor_ref: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    # the operation's own parameters (thresholds, layers, sources) —
    # links, never content.
    operation: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # field → {from, to} (strings capped at 200 chars) plus the skills
    # set-diff shape `{"skills": {"added": [...], "removed": [...],
    # "changed": {...}}}` for relation re-tags.
    diff: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ok", server_default="ok"
    )


class PostingSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Posting ↔ skill requirement: FK join, never text (the matching edge).

    `required_level`/`priority` exist from day one and are filled by
    deep extraction (NULL = not yet extracted)."""

    __tablename__ = "posting_skills"
    __table_args__ = (
        UniqueConstraint("posting_id", "skill_id", name="uq_posting_skills_posting_skill"),
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
    evidence: Mapped[str] = mapped_column(String(20), nullable=False, default="explicit")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    required_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)


class PostingFilterPreset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One saved filter preset (plan 136): a named, tagged snapshot of
    the postings filter spec. Profile-scoped — the fit score and saved
    state differ per profile. The ``filters`` JSONB is versioned at the
    API seam (pydantic); the row never interprets it."""

    __tablename__ = "posting_filter_presets"
    __table_args__ = (
        UniqueConstraint("profile_id", "name", name="uq_posting_filter_presets_profile_name"),
        Index("ix_posting_filter_presets_profile", "profile_id"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    tags: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    filters: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class PostingInteraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user posting engagement state — seen / saved / hidden only.

    Application state (stage, applied date, notes, documents) lives in
    `applications` since plan 113; this table never carries it again.
    """

    __tablename__ = "posting_interactions"
    __table_args__ = (
        UniqueConstraint("user_id", "posting_id", name="uq_posting_interactions_user_posting"),
        Index("ix_posting_interactions_posting_id", "posting_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    seen_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    saved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class WebhookEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Inbound-webhook endpoint (dormant until plan 122 phase 3).

    `key` names the endpoint; `token_hash` is the sha256 of the secret it
    authenticates with. `target` decides which pipeline consumes the
    event.
    """

    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        CheckConstraint(
            "target IN ('posting_status', 'application_status', 'ingest')",
            name="target_allowed",
        ),
        CheckConstraint(
            "last_status IN ('ok', 'degraded', 'failed')",
            name="last_status_allowed",
        ),
        Index("ix_webhook_endpoints_source", "source_id"),
    )

    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_sources.id", ondelete="SET NULL"), nullable=True
    )
    target: Mapped[str] = mapped_column(String(24), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_event_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_status: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default=HealthStatus.OK.value,
        server_default=HealthStatus.OK.value,
    )


def current_fit_version() -> int:
    """The fit engine's current formula version.

    Imported lazily: ORM models never depend on the services layer at
    module import time.
    """
    from app.services.postings.fit.dimensions import FIT_VERSION

    return FIT_VERSION


class PostingFit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cached per-posting match score: deterministic dimensions
    over extracted posting data; `inputs_hash` detects staleness —
    recompute lazily on view, never silently blended."""

    __tablename__ = "posting_fits"
    __table_args__ = (
        UniqueConstraint("user_id", "posting_id", name="uq_posting_fits_user_posting"),
        Index("ix_posting_fits_posting_id", "posting_id"),
        Index("ix_posting_fits_user_computed", "user_id", "computed_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    breakdown: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    # Canonical-JSON sha256 of every input (skills, weights, profile
    # basics, extract_version, posted_at) — mismatch ⇒ stale ⇒ recompute.
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Analytics window for 120's bounded recompute + refit progress.
    computed_at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=lambda: datetime.now(UTC)
    )
    fit_version: Mapped[int] = mapped_column(Integer, nullable=False, default=current_fit_version)
