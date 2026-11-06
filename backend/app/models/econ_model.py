"""Economic context (plan 127 §3.0 — the money-flow evidence layer).

Versioned dataset packs, dimensional series with evidence-bearing
observations, code crosswalks, occupation exposure scores, the scenario
and claim registries, and per-user watches. Sibling of
``market_snapshots`` (posting-derived), never a replacement.

Retention: hard delete everywhere. Pack/series/observation rows
hard-delete with their provider pack; alias, watch and event rows
hard-delete with their parent/user. No tombstones — the provenance
columns are the audit trail.
"""

import uuid
from datetime import UTC, date, datetime

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)

_LICENSE = "license_class IN ('public_domain', 'open_data', 'attribution', 'research_only')"


class GeoRegion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Canonical region join key (country → metro). Reference data, retained."""

    __tablename__ = "geo_regions"
    __table_args__ = (
        UniqueConstraint("country", "kind", "code", name="uq_geo_regions_country_kind_code"),
        CheckConstraint(
            "kind IN ('country', 'nuts1', 'nuts2', 'metro', 'itl1', 'city')",
            name="kind_allowed",
        ),
        Index("ix_geo_regions_country", "country"),
    )

    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)


class GeoRegionAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Profile country/city strings resolved to a region. Operational cache."""

    __tablename__ = "geo_region_aliases"
    __table_args__ = (
        UniqueConstraint("alias", "geo_region_id", name="uq_geo_region_aliases_alias_region"),
        Index("ix_geo_region_aliases_alias", "alias"),
        Index("ix_geo_region_aliases_region", "geo_region_id"),
    )

    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    geo_region_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("geo_regions.id", ondelete="CASCADE"), nullable=False
    )


class EconPack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One dataset pack or live provider instance with its vintage and license.

    Record — retained with its provider source; hard-deletes only when the
    source is removed. ``manifest`` embeds its own ``pack_format`` version.
    """

    __tablename__ = "econ_packs"
    __table_args__ = (
        UniqueConstraint("pack_id", "version", name="uq_econ_packs_pack_id_version"),
        CheckConstraint(
            "kind IN ('pack', 'live', 'harvested')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "status IN ('proposed', 'active', 'superseded')",
            name="status_allowed",
        ),
        CheckConstraint(_LICENSE, name="license_class_allowed"),
        Index("ix_econ_packs_provider", "provider"),
    )

    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    pack_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_vintage: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    license_class: Mapped[str] = mapped_column(String(20), nullable=False)
    coverage: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    coverage_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    manifest: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class EconSeries(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One dimensional series (geo x category x metric) inside a pack.

    Record — retained with its pack. ``series_key`` is the pack-stable
    identity; dimensions the app filters or joins on are typed columns.
    """

    __tablename__ = "econ_series"
    __table_args__ = (
        UniqueConstraint("econ_pack_id", "series_key", name="uq_econ_series_pack_series_key"),
        CheckConstraint(
            "coverage_level IN ('full', 'regional', 'country', 'modelled_estimate')",
            name="coverage_level_allowed",
        ),
        CheckConstraint(_LICENSE, name="license_class_allowed"),
        Index("ix_econ_series_geo", "geo_region_id"),
    )

    econ_pack_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("econ_packs.id", ondelete="CASCADE"), nullable=False
    )
    series_key: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    freq: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    geo_region_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("geo_regions.id", ondelete="CASCADE"), nullable=False
    )
    sector_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    occ_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    coverage_level: Mapped[str] = mapped_column(String(20), nullable=False)
    license_class: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provider_dims: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    provider_dims_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class EconObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One observed or harvested value of a series at a period and revision.

    Record — revisions are kept side by side, never overwritten.
    ``evidence`` (verbatim span + locator + content hash) is what makes a
    harvested value ``extracted``; without a verified span it stays
    ``ai_estimated`` or is dropped.
    """

    __tablename__ = "econ_observations"
    __table_args__ = (
        UniqueConstraint(
            "series_id",
            "period",
            "revision",
            name="uq_econ_observations_series_period_revision",
        ),
        CheckConstraint(
            "provenance_tier IN ('official', 'extracted', 'derived', 'ai_estimated')",
            name="provenance_tier_allowed",
        ),
        Index("ix_econ_observations_series", "series_id"),
    )

    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("econ_series.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    vintage: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observed_at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=lambda: datetime.now(UTC)
    )
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provenance_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    evidence_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class CodeCrosswalk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Typed mapping between code systems (dataset category → sector → occupation).

    Record — retained with its taxonomy source. ``method`` + ``confidence``
    make AI-proposed mappings reviewable before they apportion anything.
    """

    __tablename__ = "code_crosswalks"
    __table_args__ = (
        UniqueConstraint(
            "from_system",
            "from_code",
            "to_system",
            "to_code",
            name="uq_code_crosswalks_from_to",
        ),
        CheckConstraint("method IN ('official', 'ai', 'manual')", name="method_allowed"),
        Index("ix_code_crosswalks_from", "from_system", "from_code"),
    )

    from_system: Mapped[str] = mapped_column(String(32), nullable=False)
    from_code: Mapped[str] = mapped_column(String(32), nullable=False)
    to_system: Mapped[str] = mapped_column(String(32), nullable=False)
    to_code: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class ExposureScore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Machine/AI exposure score per occupation and method (ILO GenAI, O*NET).

    Record — retained with its published source; cited, never blended.
    """

    __tablename__ = "exposure_scores"
    __table_args__ = (
        UniqueConstraint(
            "occ_code",
            "method",
            "horizon",
            name="uq_exposure_scores_occ_method_horizon",
        ),
        CheckConstraint("method IN ('ilo_genai', 'onet_task')", name="method_allowed"),
        CheckConstraint(_LICENSE, name="license_class_allowed"),
        Index("ix_exposure_scores_occ", "occ_code"),
    )

    occ_code: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    license_class: Mapped[str] = mapped_column(String(20), nullable=False)


class Scenario(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named, falsifiable scenario: thesis + assumptions + indicators + falsifiers.

    Record — a scenario's lifecycle is evidence, not churn. Points live in
    ``scenario_points`` as distributions (p10/p50/p90), never single lines.
    """

    __tablename__ = "scenarios"
    __table_args__ = (
        UniqueConstraint("key", name="uq_scenarios_key"),
        CheckConstraint(
            "scope_kind IN ('global', 'geo', 'sector', 'occupation', 'job')",
            name="scope_kind_allowed",
        ),
        CheckConstraint(
            "status IN ('proposed', 'active', 'refuted', 'retired')",
            name="status_allowed",
        ),
    )

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False, default="*")
    assumptions: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    indicators: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    falsifiers: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(10), nullable=False)


class ScenarioPoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One distribution point of a scenario: p10/p50/p90 for a metric and horizon."""

    __tablename__ = "scenario_points"
    __table_args__ = (
        UniqueConstraint(
            "scenario_id",
            "metric",
            "scope_key",
            "horizon",
            name="uq_scenario_points_scenario_metric_scope_horizon",
        ),
        Index("ix_scenario_points_scenario", "scenario_id"),
    )

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False, default="*")
    horizon: Mapped[date] = mapped_column(Date, nullable=False)
    p10: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    p50: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    p90: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)


class Claim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A thesis-dossier claim, tracked as a testable hypothesis.

    Record — the claim timeline is the point of the dossier. Evidence refs
    point at series/observation rows, never prose alone.
    """

    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("key", name="uq_claims_key"),
        CheckConstraint(
            "status IN ('open', 'supported', 'contested', 'resolved')",
            name="status_allowed",
        ),
    )

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    testable_form: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    evidence_refs: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class ClaimEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Timeline entry for a claim: user verdicts and system evidence updates.

    ``user_id`` nulls on user erasure (the claim outlives its author); the
    erasure path must scrub ``note`` prose on that transition.
    """

    __tablename__ = "claim_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('accept', 'reject', 'reopen', 'resolve', 'note')",
            name="action_allowed",
        ),
        Index("ix_claim_events_claim", "claim_id"),
        Index("ix_claim_events_user", "user_id"),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class EconWatchEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A watched geo/sector/series/indicator scope per user.

    Operational — hard-deletes with the user; notifications flow through
    the single NotificationService funnel.
    """

    __tablename__ = "econ_watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_kind", "scope_key", name="uq_econ_watchlist_user_scope"),
        CheckConstraint(
            "scope_kind IN ('geo', 'sector', 'series', 'indicator')",
            name="scope_kind_allowed",
        ),
        Index("ix_econ_watchlist_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False)
