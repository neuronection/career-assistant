"""Seed providers, versions, runs and catalog presets (plan 218 / ADR-0056).

A **provider** is a seed-data publisher: an uploaded pack, a static
``seed-repo.json`` index, or a public git repository. The app ships no pack of
its own. Fetched packs land
as immutable, content-addressed ``seed_source_versions`` rows whose status is
``pending`` until an admin approves the exact digest; only an approved version
is ever applied. Pack content is data — no table here executes anything.

``job_source_presets`` / ``provider_endpoints`` are the applied catalog (the
liveness authority); ``seed_item_provenance`` projects per-entity origin.
``provider_subscriptions`` / ``source_prefs`` carry user-scoped follow/hide.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
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

SEED_SOURCE_KINDS = ("file", "registry", "git")
SEED_TRUST_TIERS = ("official", "operator", "community", "local")
SEED_VERSION_STATUSES = ("pending", "approved", "rejected", "revoked")
SEED_SYNC_TRIGGERS = ("manual", "scheduled")
SEED_SYNC_STATUSES = ("running", "ok", "noop", "failed", "partial")
SEED_IMPORT_MODES = ("plan", "apply", "revoke", "reconcile")
SEED_IMPORT_STATUSES = ("pending", "running", "applied", "conflicted", "failed", "partial")
SEED_ITEM_ACTIONS = ("create", "update", "noop", "conflict", "skip", "override", "retire")
SEED_PROVENANCE_STATES = ("active", "retired", "overridden")
SEED_DEFERRED_STATES = ("pending", "landed", "abandoned")
PRESET_CATEGORIES = ("ats", "remote")
PRESET_STATES = ("active", "retired", "overridden")
ENDPOINT_STATES = ("active", "retired", "overridden")
ENDPOINT_METHODS = ("GET", "POST")
ENDPOINT_AUTH = ("none", "api_key", "bearer", "oauth")
SUBSCRIPTION_MODES = ("all", "selected")
SOURCE_SUPPORT_STATUSES = ("supported", "retired")


class SeedSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One provider the instance knows how to fetch seed packs from.

    ``uri`` is the repository/index URL (``git``/``registry``) or the stored
    upload's content key (``file``). ``ref_spec`` pins
    the git tag/commit. ``current_version_id`` is the *applied* version — the
    pointer moves only on apply, never on sync.
    """

    __tablename__ = "seed_sources"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('file', 'registry', 'git')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "trust_tier IN ('official', 'operator', 'community', 'local')",
            name="trust_allowed",
        ),
        CheckConstraint("scope = 'system'", name="scope_allowed"),
        CheckConstraint("priority >= 0", name="priority_nonneg"),
        CheckConstraint("refresh_minutes >= 0", name="refresh_nonneg"),
        Index("ix_seed_sources_enabled_priority", "enabled", "priority"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="git")
    uri: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    ref_spec: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subpath: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    trust_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="community")
    refresh_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "seed_source_versions.id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    last_check_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    policy: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class SeedSourceVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An immutable fetched pack, identified by its content digest.

    ``manifest`` is the parsed pack manifest verbatim; ``pack_version`` /
    ``schema_version`` / ``vintage`` are typed projections for listing. A
    duplicate ``(source_id, digest)`` is a no-op; the same pack version with a
    different digest is rejected by the sync service.
    """

    __tablename__ = "seed_source_versions"
    __table_args__ = (
        UniqueConstraint("source_id", "digest", name="uq_seed_source_versions_source_digest"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'revoked')",
            name="status_allowed",
        ),
        Index("ix_seed_source_versions_source_status", "source_id", "status"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seed_sources.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    etag: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    digest: Mapped[str] = mapped_column(String(80), nullable=False)
    manifest: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    pack_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    vintage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contract_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class SeedSyncRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One fetch attempt: what the transport saw, never whether it applied."""

    __tablename__ = "seed_sync_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('manual', 'scheduled')", name="trigger_allowed"),
        CheckConstraint(
            "status IN ('ok', 'noop', 'failed', 'partial')",
            name="status_allowed",
        ),
        Index("ix_seed_sync_runs_source_started", "source_id", "started_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seed_sources.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etag: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seed_source_versions.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class SeedImportRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One planner/applier run over an approved version (or a plan preview)."""

    __tablename__ = "seed_import_runs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('plan', 'apply', 'revoke', 'reconcile')",
            name="mode_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'applied', 'conflicted', 'failed', 'partial')",
            name="status_allowed",
        ),
        Index("ix_seed_import_runs_source_started", "source_id", "started_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seed_sources.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seed_source_versions.id", ondelete="SET NULL"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="plan")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    plan: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    stats: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class SeedImportRunItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One ``seed_key`` decision inside an import run (the conflict ledger)."""

    __tablename__ = "seed_import_run_items"
    __table_args__ = (
        CheckConstraint(
            "action IN ('create', 'update', 'noop', 'conflict', 'skip', 'override', 'retire')",
            name="action_allowed",
        ),
        Index("ix_seed_import_run_items_run", "run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seed_import_runs.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    seed_key: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class SeedItemProvenance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Read-only projection of where a catalog row came from.

    ``state`` mirrors the liveness authority (preset/endpoint row); it is
    never the source of truth for whether a row is live.
    """

    __tablename__ = "seed_item_provenance"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_seed_item_provenance_entity"),
        CheckConstraint(
            "state IN ('active', 'retired', 'overridden')",
            name="state_allowed",
        ),
        Index("ix_seed_item_provenance_seed_key", "seed_key"),
    )

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seed_source_versions.id", ondelete="SET NULL"), nullable=True
    )
    seed_key: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    user_modified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class SeedDeferredRef(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reference in an applied pack that could not resolve yet (retried)."""

    __tablename__ = "seed_deferred_refs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'landed', 'abandoned')",
            name="state_allowed",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        Index("ix_seed_deferred_refs_version_state", "source_version_id", "state"),
    )

    source_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seed_source_versions.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")


class JobSourcePreset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An applied ATS/remote catalog preset (the gallery's liveness authority).

    ``seed_key`` is the immutable pack identity; ``slug`` stays the
    ``job_sources.key`` for continuity but is display/UX only. ``enabled`` is
    the admin's per-item overlay; content stays pack-owned.
    """

    __tablename__ = "job_source_presets"
    __table_args__ = (
        UniqueConstraint("scope_key", "seed_key", name="uq_job_source_presets_scope_seed"),
        CheckConstraint("category IN ('ats', 'remote')", name="category_allowed"),
        CheckConstraint(
            "state IN ('active', 'retired', 'overridden')",
            name="state_allowed",
        ),
        CheckConstraint(
            "length(connector_key) BETWEEN 1 AND 80",
            name="connector_key_present",
        ),
        Index("ix_job_source_presets_enabled_state", "enabled", "state"),
        Index("ix_job_source_presets_slug", "slug"),
    )

    scope_key: Mapped[str] = mapped_column(String(40), nullable=False, default="system")
    seed_key: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    connector_key: Mapped[str] = mapped_column(String(80), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    countries: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    regions: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    worldwide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    languages: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    work_modes: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    homepage: Mapped[str | None] = mapped_column(String(400), nullable=True)
    openings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    config: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    seed_source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seed_source_versions.id", ondelete="SET NULL"), nullable=True
    )


class ProviderEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A published public endpoint descriptor (documentation, never a secret)."""

    __tablename__ = "provider_endpoints"
    __table_args__ = (
        UniqueConstraint("scope_key", "seed_key", name="uq_provider_endpoints_scope_seed"),
        CheckConstraint("method IN ('GET', 'POST')", name="method_allowed"),
        CheckConstraint("auth IN ('none', 'api_key', 'bearer', 'oauth')", name="auth_allowed"),
        CheckConstraint(
            "state IN ('active', 'retired', 'overridden')",
            name="state_allowed",
        ),
        Index("ix_provider_endpoints_connector", "connector_key"),
    )

    scope_key: Mapped[str] = mapped_column(String(40), nullable=False, default="system")
    seed_key: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    connector_key: Mapped[str] = mapped_column(String(80), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    server: Mapped[str] = mapped_column(String(400), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    path: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    auth: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    params: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    countries: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    regions: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    worldwide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    languages: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    docs_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    seed_source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seed_source_versions.id", ondelete="SET NULL"), nullable=True
    )


class ProviderSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """User follow of a provider (visibility scope, never source creation)."""

    __tablename__ = "provider_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "seed_source_id", name="uq_provider_subscriptions_user_source"),
        CheckConstraint("mode IN ('all', 'selected')", name="mode_allowed"),
        Index("ix_provider_subscriptions_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    seed_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seed_sources.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="all")
    collections: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    filters: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class SourcePref(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """User-scoped hide/priority overlay for one concrete job source."""

    __tablename__ = "source_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "job_source_id", name="uq_source_prefs_user_source"),
        Index("ix_source_prefs_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False
    )
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    filters: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class MigrationArchive(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Exact pre-fold value kept by a self-contained data migration."""

    __tablename__ = "migration_archive"
    __table_args__ = (UniqueConstraint("key", name="uq_migration_archive_key"),)

    key: Mapped[str] = mapped_column(String(200), nullable=False)
    old_value: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
