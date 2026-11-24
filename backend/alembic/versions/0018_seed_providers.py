"""Seed providers, versions, runs and catalog presets (plan 218 / ADR-0056).

Additive foundation only: no data fold, no row delete. The applied pointer
``seed_sources.current_version_id`` and ``seed_source_versions.source_id`` form
a circular FK, created with ``use_alter``; the SQLite lane rebuilds the affected
tables through ``batch_alter_table`` (same pattern as ``0002``/``0011``).

``schedules.kind`` / ``schedules.task`` gain the provider-sync vocabulary so
``0018`` is the single schema stop for the lane.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def _id_column() -> sa.Column:
    return sa.Column("id", sa.Uuid(as_uuid=True), nullable=False)


def _pk() -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint("id")


_KIND_CHECK_OLD = (
    "kind IN ('system_source_sync', 'system_digest', "
    "'system_demand_import', 'system_refit_sweep', "
    "'system_catalog_enrich', 'system_followups', "
    "'system_market_history', 'system_proposal_sweep', "
    "'system_checkpoint_prune', 'system_extension_reconcile', "
    "'system_skill_relation_learn', 'system_vector_reconcile', "
    "'system_retrieval_alerts', 'system_mapping_coverage', "
    "'system_mapping_alerts', "
    "'user_saved_search', 'user_radar_digest', 'user_smart_digest', "
    "'user_checkin', 'user_autopilot')"
)

_KIND_CHECK_NEW = (
    "kind IN ('system_source_sync', 'system_digest', "
    "'system_demand_import', 'system_refit_sweep', "
    "'system_catalog_enrich', 'system_followups', "
    "'system_market_history', 'system_proposal_sweep', "
    "'system_checkpoint_prune', 'system_extension_reconcile', "
    "'system_skill_relation_learn', 'system_vector_reconcile', "
    "'system_retrieval_alerts', 'system_mapping_coverage', "
    "'system_mapping_alerts', 'system_provider_sync', "
    "'user_saved_search', 'user_radar_digest', 'user_smart_digest', "
    "'user_checkin', 'user_autopilot')"
)

_TASK_CHECK_OLD = (
    "task IS NULL OR task IN ('posting_sync', 'digest', "
    "'saved_search_run', 'radar_digest', 'smart_digest', "
    "'fit_refit', 'catalog_enrich', 'autopilot_run', "
    "'followup_sweep', 'market_history_capture', 'proposal_sweep', "
    "'checkpoint_prune', 'extension_reconcile', "
    "'demand_import', 'skill_relation_learn', "
    "'vector_reconcile', 'retrieval_alert_sweep', "
    "'mapping_coverage_capture', 'mapping_alert_sweep')"
)

_TASK_CHECK_NEW = (
    "task IS NULL OR task IN ('posting_sync', 'digest', "
    "'saved_search_run', 'radar_digest', 'smart_digest', "
    "'fit_refit', 'catalog_enrich', 'autopilot_run', "
    "'followup_sweep', 'market_history_capture', 'proposal_sweep', "
    "'checkpoint_prune', 'extension_reconcile', "
    "'demand_import', 'skill_relation_learn', "
    "'vector_reconcile', 'retrieval_alert_sweep', "
    "'mapping_coverage_capture', 'mapping_alert_sweep', "
    "'provider_sync')"
)


def upgrade() -> None:
    op.create_table(
        "seed_sources",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("uri", sa.String(length=600), nullable=False),
        sa.Column("ref_spec", sa.String(length=200), nullable=False),
        sa.Column("subpath", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("trust_tier", sa.String(length=20), nullable=False),
        sa.Column("refresh_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("current_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("policy", _JSON, nullable=False),
        *_timestamps(),
        _id_column(),
        sa.CheckConstraint(
            "kind IN ('bundled', 'file', 'registry', 'git')",
            name="kind_allowed",
        ),
        sa.CheckConstraint(
            "trust_tier IN ('official', 'operator', 'community', 'local')",
            name="trust_allowed",
        ),
        sa.CheckConstraint("scope = 'system'", name="scope_allowed"),
        sa.CheckConstraint("priority >= 0", name="priority_nonneg"),
        sa.CheckConstraint("refresh_minutes >= 0", name="refresh_nonneg"),
        _pk(),
    )
    op.create_index(
        "ix_seed_sources_enabled_priority",
        "seed_sources",
        ["enabled", "priority"],
        unique=False,
    )

    op.create_table(
        "seed_source_versions",
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("etag", sa.String(length=200), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("manifest", _JSON, nullable=False),
        sa.Column("pack_version", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("vintage", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("contract_version", sa.String(length=20), nullable=False),
        sa.Column("approved_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["seed_sources.id"],
            name="fk_seed_source_versions_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name="fk_seed_source_versions_approved_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("source_id", "digest", name="uq_seed_source_versions_source_digest"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'revoked')",
            name="status_allowed",
        ),
        _pk(),
    )
    op.create_index(
        "ix_seed_source_versions_source_status",
        "seed_source_versions",
        ["source_id", "status"],
        unique=False,
    )

    with op.batch_alter_table("seed_sources") as batch:
        batch.create_foreign_key(
            "fk_seed_sources_current_version",
            "seed_source_versions",
            ["current_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "seed_sync_runs",
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("etag", sa.String(length=200), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["seed_sources.id"],
            name="fk_seed_sync_runs_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["seed_source_versions.id"],
            name="fk_seed_sync_runs_version",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("trigger IN ('manual', 'scheduled')", name="trigger_allowed"),
        sa.CheckConstraint(
            "status IN ('ok', 'noop', 'failed', 'partial')",
            name="status_allowed",
        ),
        _pk(),
    )
    op.create_index(
        "ix_seed_sync_runs_source_started",
        "seed_sync_runs",
        ["source_id", "started_at"],
        unique=False,
    )

    op.create_table(
        "seed_import_runs",
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("plan", _JSON, nullable=False),
        sa.Column("stats", _JSON, nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["seed_sources.id"],
            name="fk_seed_import_runs_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["seed_source_versions.id"],
            name="fk_seed_import_runs_version",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "mode IN ('plan', 'apply', 'revoke', 'reconcile')",
            name="mode_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'applied', 'conflicted', 'failed', 'partial')",
            name="status_allowed",
        ),
        _pk(),
    )
    op.create_index(
        "ix_seed_import_runs_source_started",
        "seed_import_runs",
        ["source_id", "started_at"],
        unique=False,
    )

    op.create_table(
        "seed_import_run_items",
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("seed_key", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("detail", _JSON, nullable=False),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["seed_import_runs.id"],
            name="fk_seed_import_run_items_run",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "action IN ('create', 'update', 'noop', 'conflict', 'skip', 'override', 'retire')",
            name="action_allowed",
        ),
        _pk(),
    )
    op.create_index(
        "ix_seed_import_run_items_run",
        "seed_import_run_items",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "seed_item_provenance",
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("seed_key", sa.String(length=200), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("user_modified", sa.Boolean(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["seed_source_versions.id"],
            name="fk_seed_item_provenance_version",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_seed_item_provenance_entity"),
        sa.CheckConstraint(
            "state IN ('active', 'retired', 'overridden')",
            name="state_allowed",
        ),
        _pk(),
    )
    op.create_index(
        "ix_seed_item_provenance_seed_key",
        "seed_item_provenance",
        ["seed_key"],
        unique=False,
    )

    op.create_table(
        "seed_deferred_refs",
        sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("payload", _JSON, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["seed_source_versions.id"],
            name="fk_seed_deferred_refs_version",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'landed', 'abandoned')",
            name="state_allowed",
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        _pk(),
    )
    op.create_index(
        "ix_seed_deferred_refs_version_state",
        "seed_deferred_refs",
        ["source_version_id", "state"],
        unique=False,
    )

    op.create_table(
        "job_source_presets",
        sa.Column("scope_key", sa.String(length=40), nullable=False),
        sa.Column("seed_key", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("connector_key", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("countries", _JSON, nullable=False),
        sa.Column("regions", _JSON, nullable=False),
        sa.Column("worldwide", sa.Boolean(), nullable=False),
        sa.Column("languages", _JSON, nullable=False),
        sa.Column("work_modes", _JSON, nullable=False),
        sa.Column("homepage", sa.String(length=400), nullable=True),
        sa.Column("openings", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.Date(), nullable=True),
        sa.Column("config", _JSON, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("seed_source_version_id", sa.Uuid(as_uuid=True), nullable=True),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["seed_source_version_id"],
            ["seed_source_versions.id"],
            name="fk_job_source_presets_version",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("scope_key", "seed_key", name="uq_job_source_presets_scope_seed"),
        sa.CheckConstraint("category IN ('ats', 'remote')", name="category_allowed"),
        sa.CheckConstraint(
            "state IN ('active', 'retired', 'overridden')",
            name="state_allowed",
        ),
        sa.CheckConstraint(
            "length(connector_key) BETWEEN 1 AND 80",
            name="connector_key_present",
        ),
        _pk(),
    )
    op.create_index(
        "ix_job_source_presets_enabled_state",
        "job_source_presets",
        ["enabled", "state"],
        unique=False,
    )
    op.create_index(
        "ix_job_source_presets_slug",
        "job_source_presets",
        ["slug"],
        unique=False,
    )

    op.create_table(
        "provider_endpoints",
        sa.Column("scope_key", sa.String(length=40), nullable=False),
        sa.Column("seed_key", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("connector_key", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("server", sa.String(length=400), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=400), nullable=False),
        sa.Column("auth", sa.String(length=20), nullable=False),
        sa.Column("params", _JSON, nullable=False),
        sa.Column("countries", _JSON, nullable=False),
        sa.Column("regions", _JSON, nullable=False),
        sa.Column("worldwide", sa.Boolean(), nullable=False),
        sa.Column("languages", _JSON, nullable=False),
        sa.Column("docs_url", sa.String(length=600), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("seed_source_version_id", sa.Uuid(as_uuid=True), nullable=True),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["seed_source_version_id"],
            ["seed_source_versions.id"],
            name="fk_provider_endpoints_version",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("scope_key", "seed_key", name="uq_provider_endpoints_scope_seed"),
        sa.CheckConstraint("method IN ('GET', 'POST')", name="method_allowed"),
        sa.CheckConstraint("auth IN ('none', 'api_key', 'oauth')", name="auth_allowed"),
        sa.CheckConstraint(
            "state IN ('active', 'retired', 'overridden')",
            name="state_allowed",
        ),
        _pk(),
    )
    op.create_index(
        "ix_provider_endpoints_connector",
        "provider_endpoints",
        ["connector_key"],
        unique=False,
    )

    op.create_table(
        "provider_subscriptions",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("seed_source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("collections", _JSON, nullable=False),
        sa.Column("filters", _JSON, nullable=False),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_provider_subscriptions_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["seed_source_id"],
            ["seed_sources.id"],
            name="fk_provider_subscriptions_source",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "seed_source_id", name="uq_provider_subscriptions_user_source"
        ),
        sa.CheckConstraint("mode IN ('all', 'selected')", name="mode_allowed"),
        _pk(),
    )
    op.create_index(
        "ix_provider_subscriptions_user",
        "provider_subscriptions",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "source_prefs",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("filters", _JSON, nullable=False),
        *_timestamps(),
        _id_column(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_source_prefs_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_source_id"],
            ["job_sources.id"],
            name="fk_source_prefs_job_source",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "job_source_id", name="uq_source_prefs_user_source"),
        _pk(),
    )
    op.create_index(
        "ix_source_prefs_user",
        "source_prefs",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "migration_archive",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("old_value", _JSON, nullable=False),
        *_timestamps(),
        _id_column(),
        sa.UniqueConstraint("key", name="uq_migration_archive_key"),
        _pk(),
    )

    with op.batch_alter_table("job_sources") as batch:
        batch.add_column(sa.Column("seed_source_id", sa.Uuid(as_uuid=True), nullable=True))
        batch.add_column(sa.Column("seed_item_key", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("applied_version_id", sa.Uuid(as_uuid=True), nullable=True))
        batch.add_column(
            sa.Column(
                "support_status",
                sa.String(length=20),
                nullable=False,
                server_default="supported",
            )
        )
        batch.create_foreign_key(
            "fk_job_sources_seed_source",
            "seed_sources",
            ["seed_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_job_sources_applied_version",
            "seed_source_versions",
            ["applied_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "support_status_allowed",
            "support_status IN ('supported', 'retired')",
        )

    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _KIND_CHECK_NEW)
        batch.create_check_constraint("task_allowed", _TASK_CHECK_NEW)


def downgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _KIND_CHECK_OLD)
        batch.create_check_constraint("task_allowed", _TASK_CHECK_OLD)

    with op.batch_alter_table("job_sources") as batch:
        batch.drop_constraint("support_status_allowed", type_="check")
        batch.drop_constraint("fk_job_sources_applied_version", type_="foreignkey")
        batch.drop_constraint("fk_job_sources_seed_source", type_="foreignkey")
        batch.drop_column("support_status")
        batch.drop_column("applied_version_id")
        batch.drop_column("seed_item_key")
        batch.drop_column("seed_source_id")

    op.drop_table("migration_archive")
    op.drop_index("ix_source_prefs_user", table_name="source_prefs")
    op.drop_table("source_prefs")
    op.drop_index("ix_provider_subscriptions_user", table_name="provider_subscriptions")
    op.drop_table("provider_subscriptions")
    op.drop_index("ix_provider_endpoints_connector", table_name="provider_endpoints")
    op.drop_table("provider_endpoints")
    op.drop_index("ix_job_source_presets_slug", table_name="job_source_presets")
    op.drop_index("ix_job_source_presets_enabled_state", table_name="job_source_presets")
    op.drop_table("job_source_presets")
    op.drop_index("ix_seed_deferred_refs_version_state", table_name="seed_deferred_refs")
    op.drop_table("seed_deferred_refs")
    op.drop_index("ix_seed_item_provenance_seed_key", table_name="seed_item_provenance")
    op.drop_table("seed_item_provenance")
    op.drop_index("ix_seed_import_run_items_run", table_name="seed_import_run_items")
    op.drop_table("seed_import_run_items")
    op.drop_index("ix_seed_import_runs_source_started", table_name="seed_import_runs")
    op.drop_table("seed_import_runs")
    op.drop_index("ix_seed_sync_runs_source_started", table_name="seed_sync_runs")
    op.drop_table("seed_sync_runs")
    with op.batch_alter_table("seed_sources") as batch:
        batch.drop_constraint(
            "fk_seed_sources_current_version",
            type_="foreignkey",
        )
    op.drop_index("ix_seed_source_versions_source_status", table_name="seed_source_versions")
    op.drop_table("seed_source_versions")
    op.drop_index("ix_seed_sources_enabled_priority", table_name="seed_sources")
    op.drop_table("seed_sources")
