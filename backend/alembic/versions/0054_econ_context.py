"""Plan 127 §3.0 — economic-context foundation, purely additive (design
review in 113 §1.J).

The money-flow evidence layer: canonical region join keys + alias cache,
versioned dataset packs, dimensional series with evidence-bearing
observations (four provenance tiers), code crosswalks, occupation
exposure scores, the scenario/claim registries and per-user watches.
Sits beside ``market_snapshots`` (which stays posting-derived).

Model-first (family-migration §1): mirrors ``app.models.econ_model``
exactly. ``downgrade()`` removes everything this revision added.

Revision id: ``0054`` — the plan's ``0053_econ_context`` slot was taken
by ``0053_demand_import_task`` (plan 122 phase 3) before this wave
opened; sequential ids win over plan text.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

_GEO_KIND = "kind IN ('country', 'nuts1', 'nuts2', 'metro', 'itl1', 'city')"
_LICENSE = "license_class IN ('public_domain', 'open_data', 'attribution', 'research_only')"
_PACK_KIND = "kind IN ('pack', 'live', 'harvested')"
_PACK_STATUS = "status IN ('proposed', 'active', 'superseded')"
_COVERAGE_LEVEL = "coverage_level IN ('full', 'regional', 'country', 'modelled_estimate')"
_PROVENANCE_TIER = "provenance_tier IN ('official', 'extracted', 'derived', 'ai_estimated')"
_CROSSWALK_METHOD = "method IN ('official', 'ai', 'manual')"
_EXPOSURE_METHOD = "method IN ('ilo_genai', 'onet_task')"
_SCENARIO_SCOPE = "scope_kind IN ('global', 'geo', 'sector', 'occupation', 'job')"
_SCENARIO_STATUS = "status IN ('proposed', 'active', 'refuted', 'retired')"
_CLAIM_STATUS = "status IN ('open', 'supported', 'contested', 'resolved')"
_CLAIM_ACTION = "action IN ('accept', 'reject', 'reopen', 'resolve', 'note')"
_WATCH_SCOPE = "scope_kind IN ('geo', 'sector', 'series', 'indicator')"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "geo_regions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country", "kind", "code", name="uq_geo_regions_country_kind_code"),
        sa.CheckConstraint(_GEO_KIND, name="kind_allowed"),
    )
    op.create_index("ix_geo_regions_country", "geo_regions", ["country"])

    op.create_table(
        "geo_region_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("geo_region_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["geo_region_id"], ["geo_regions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("alias", "geo_region_id", name="uq_geo_region_aliases_alias_region"),
    )
    op.create_index("ix_geo_region_aliases_alias", "geo_region_aliases", ["alias"])
    op.create_index("ix_geo_region_aliases_region", "geo_region_aliases", ["geo_region_id"])

    op.create_table(
        "econ_packs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("pack_id", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("dataset_vintage", sa.String(length=32), nullable=False),
        sa.Column("license_class", sa.String(length=20), nullable=False),
        sa.Column("coverage", _JSON, nullable=False),
        sa.Column("coverage_schema_version", sa.Integer(), nullable=False),
        sa.Column("manifest", _JSON, nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pack_id", "version", name="uq_econ_packs_pack_id_version"),
        sa.CheckConstraint(_PACK_KIND, name="kind_allowed"),
        sa.CheckConstraint(_PACK_STATUS, name="status_allowed"),
        sa.CheckConstraint(_LICENSE, name="license_class_allowed"),
    )
    op.create_index("ix_econ_packs_provider", "econ_packs", ["provider"])

    op.create_table(
        "econ_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("econ_pack_id", sa.Uuid(), nullable=False),
        sa.Column("series_key", sa.String(length=200), nullable=False),
        sa.Column("dataset_code", sa.String(length=80), nullable=False),
        sa.Column("metric", sa.String(length=80), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("freq", sa.String(length=20), nullable=False),
        sa.Column("geo_region_id", sa.Uuid(), nullable=False),
        sa.Column("sector_code", sa.String(length=32), nullable=True),
        sa.Column("occ_code", sa.String(length=32), nullable=True),
        sa.Column("coverage_level", sa.String(length=20), nullable=False),
        sa.Column("license_class", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("provider_dims", _JSON, nullable=False),
        sa.Column("provider_dims_schema_version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["econ_pack_id"], ["econ_packs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["geo_region_id"], ["geo_regions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("econ_pack_id", "series_key", name="uq_econ_series_pack_series_key"),
        sa.CheckConstraint(_COVERAGE_LEVEL, name="coverage_level_allowed"),
        sa.CheckConstraint(_LICENSE, name="license_class_allowed"),
    )
    op.create_index("ix_econ_series_geo", "econ_series", ["geo_region_id"])

    op.create_table(
        "econ_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(18, 4), nullable=False),
        sa.Column("vintage", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_estimate", sa.Boolean(), nullable=False),
        sa.Column("provenance_tier", sa.String(length=16), nullable=False),
        sa.Column("publisher", sa.String(length=120), nullable=True),
        sa.Column("evidence", _JSON, nullable=False),
        sa.Column("evidence_schema_version", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["series_id"], ["econ_series.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "series_id",
            "period",
            "revision",
            name="uq_econ_observations_series_period_revision",
        ),
        sa.CheckConstraint(_PROVENANCE_TIER, name="provenance_tier_allowed"),
    )
    op.create_index("ix_econ_observations_series", "econ_observations", ["series_id"])

    op.create_table(
        "code_crosswalks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("from_system", sa.String(length=32), nullable=False),
        sa.Column("from_code", sa.String(length=32), nullable=False),
        sa.Column("to_system", sa.String(length=32), nullable=False),
        sa.Column("to_code", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_system",
            "from_code",
            "to_system",
            "to_code",
            name="uq_code_crosswalks_from_to",
        ),
        sa.CheckConstraint(_CROSSWALK_METHOD, name="method_allowed"),
    )
    op.create_index("ix_code_crosswalks_from", "code_crosswalks", ["from_system", "from_code"])

    op.create_table(
        "exposure_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occ_code", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Numeric(6, 4), nullable=False),
        sa.Column("horizon", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("license_class", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "occ_code",
            "method",
            "horizon",
            name="uq_exposure_scores_occ_method_horizon",
        ),
        sa.CheckConstraint(_EXPOSURE_METHOD, name="method_allowed"),
        sa.CheckConstraint(_LICENSE, name="license_class_allowed"),
    )
    op.create_index("ix_exposure_scores_occ", "exposure_scores", ["occ_code"])

    op.create_table(
        "scenarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.String(length=12), nullable=False),
        sa.Column("scope_key", sa.String(length=120), nullable=False),
        sa.Column("assumptions", _JSON, nullable=False),
        sa.Column("indicators", _JSON, nullable=False),
        sa.Column("falsifiers", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_scenarios_key"),
        sa.CheckConstraint(_SCENARIO_SCOPE, name="scope_kind_allowed"),
        sa.CheckConstraint(_SCENARIO_STATUS, name="status_allowed"),
    )

    op.create_table(
        "scenario_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=80), nullable=False),
        sa.Column("scope_key", sa.String(length=120), nullable=False),
        sa.Column("horizon", sa.Date(), nullable=False),
        sa.Column("p10", sa.Numeric(18, 4), nullable=False),
        sa.Column("p50", sa.Numeric(18, 4), nullable=False),
        sa.Column("p90", sa.Numeric(18, 4), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "scenario_id",
            "metric",
            "scope_key",
            "horizon",
            name="uq_scenario_points_scenario_metric_scope_horizon",
        ),
    )
    op.create_index("ix_scenario_points_scenario", "scenario_points", ["scenario_id"])

    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("testable_form", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("evidence_refs", _JSON, nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_claims_key"),
        sa.CheckConstraint(_CLAIM_STATUS, name="status_allowed"),
    )

    op.create_table(
        "claim_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_CLAIM_ACTION, name="action_allowed"),
    )
    op.create_index("ix_claim_events_claim", "claim_events", ["claim_id"])
    op.create_index("ix_claim_events_user", "claim_events", ["user_id"])

    op.create_table(
        "econ_watchlist",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scope_kind", sa.String(length=12), nullable=False),
        sa.Column("scope_key", sa.String(length=120), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "scope_kind", "scope_key", name="uq_econ_watchlist_user_scope"
        ),
        sa.CheckConstraint(_WATCH_SCOPE, name="scope_kind_allowed"),
    )
    op.create_index("ix_econ_watchlist_user", "econ_watchlist", ["user_id"])


def downgrade() -> None:
    op.drop_table("econ_watchlist")
    op.drop_table("claim_events")
    op.drop_table("claims")
    op.drop_table("scenario_points")
    op.drop_table("scenarios")
    op.drop_table("exposure_scores")
    op.drop_table("code_crosswalks")
    op.drop_table("econ_observations")
    op.drop_table("econ_series")
    op.drop_table("econ_packs")
    op.drop_table("geo_region_aliases")
    op.drop_table("geo_regions")
