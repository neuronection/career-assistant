"""Plan 113 — schema future-proofing wave, part 1: purely additive.

The complete target schema for plans 114-125 lands here so none of those
plans needs a migration: the application pipeline (+ its event
timeline), follow-up rules, signed feed tokens, per-channel notification
config, inbound webhook endpoints, catalog label overlays, MCP tokens and
career-path flags, plus the new columns on existing tables (source kind /
health / pause, user locale, proposal origin, career-path branching, fit
analytics) and every mirrored enum CHECK widening.

Model-first (family-migration §1): mirrors ``app.models`` exactly.
``downgrade()`` removes everything this revision added.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

_APPLICATION_STAGE = (
    "stage IN ('applied', 'screening', 'interview', 'offer', 'accepted', 'rejected', 'withdrawn')"
)
_APPLICATION_VIA = "applied_via IN ('url', 'email', 'portal', 'referral', 'event', 'other')"
_APPLICATION_OUTCOME = (
    "outcome IS NULL OR outcome IN ('accepted', 'rejected', 'withdrawn', 'expired', 'ghosted')"
)
_APPLICATION_EVENT_KIND = (
    "kind IN ('stage_change', 'note', 'document_linked', 'followup_sent', "
    "'followup_snoozed', 'interview_scheduled', 'offer_received', "
    "'external_update', 'imported')"
)
_APPLICATION_ACTOR = "actor IN ('user', 'system', 'assistant', 'extension')"
_CHANNEL = "channel IN ('in_app', 'desktop', 'browser', 'email', 'webhook')"
_NOTIFICATION_CHANNEL = "channel IN ('in_app', 'desktop', 'browser')"
_SOURCE_KIND = "kind IN ('posting', 'market', 'university', 'search', 'webhook_in')"
_HEALTH = "last_status IN ('ok', 'degraded', 'failed')"
_WEBHOOK_TARGET = "target IN ('posting_status', 'application_status', 'ingest')"
_LABEL_ENTITY_KIND = (
    "entity_kind IN ('job', 'skill', 'family', 'university', 'department', "
    "'metric_dimension', 'assessment_template', 'cv_template')"
)
_LABEL_FIELD = "field IN ('label', 'description', 'short_description')"
_LABEL_SOURCE = "source IN ('ai_draft', 'human')"
_LABEL_STATUS = "status IN ('draft', 'approved', 'rejected')"
_PATH_FLAG = "flag IN ('interested', 'dismissed', 'pinned')"
_PROPOSAL_SOURCE = "source IN ('chat', 'mcp', 'autopilot', 'import')"
_PROPOSAL_SOURCE_OLD = "source IN ('chat')"


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
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_via", sa.String(length=20), nullable=False),
        sa.Column("applied_via_url", sa.String(length=1000), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_followup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contact", _JSON, nullable=False),
        sa.Column("offer", _JSON, nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cv_id", sa.Uuid(), nullable=True),
        sa.Column("cover_letter_id", sa.Uuid(), nullable=True),
        sa.Column("external_ref", sa.String(length=300), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("meta", _JSON, nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["posting_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cv_id"], ["cv_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cover_letter_id"], ["cv_documents.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "posting_id", name="uq_applications_user_posting"),
        sa.CheckConstraint(_APPLICATION_STAGE, name="stage_allowed"),
        sa.CheckConstraint(_APPLICATION_VIA, name="applied_via_allowed"),
        sa.CheckConstraint(_APPLICATION_OUTCOME, name="outcome_allowed"),
    )
    op.create_index("ix_applications_user_stage", "applications", ["user_id", "stage"])
    op.create_index(
        "ix_applications_user_next_followup", "applications", ["user_id", "next_followup_at"]
    )
    op.create_index("ix_applications_posting_id", "applications", ["posting_id"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("stage_from", sa.String(length=20), nullable=True),
        sa.Column("stage_to", sa.String(length=20), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=12), nullable=False),
        sa.Column("meta", _JSON, nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_APPLICATION_EVENT_KIND, name="kind_allowed"),
        sa.CheckConstraint(_APPLICATION_ACTOR, name="actor_allowed"),
    )
    op.create_index(
        "ix_application_events_application_at", "application_events", ["application_id", "at"]
    )

    op.create_table(
        "followup_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cadence_days", _JSON, nullable=False),
        sa.Column("milestone_checkins", sa.Boolean(), nullable=False),
        sa.Column("channels", _JSON, nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_followup_rules_user"),
    )

    op.create_table(
        "user_feed_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", _JSON, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rotated_from_id"], ["user_feed_tokens.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash", name="uq_user_feed_tokens_token_hash"),
        sa.CheckConstraint("kind IN ('ics', 'rss')", name="kind_allowed"),
    )
    op.create_index("ix_user_feed_tokens_user_kind", "user_feed_tokens", ["user_id", "kind"])

    op.create_table(
        "user_channel_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", _JSON, nullable=False),
        sa.Column("secrets", _JSON, nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "channel", name="uq_user_channel_configs_user_channel"),
        sa.CheckConstraint(_CHANNEL, name="channel_allowed"),
    )

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("target", sa.String(length=24), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=12), nullable=False, server_default="ok"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_id"], ["job_sources.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("key", name="uq_webhook_endpoints_key"),
        sa.UniqueConstraint("token_hash", name="uq_webhook_endpoints_token_hash"),
        sa.CheckConstraint(_WEBHOOK_TARGET, name="target_allowed"),
        sa.CheckConstraint(_HEALTH, name="last_status_allowed"),
    )
    op.create_index("ix_webhook_endpoints_source", "webhook_endpoints", ["source_id"])

    op.create_table(
        "label_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_kind", sa.String(length=24), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("field", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_kind", "entity_id", "locale", "field", name="uq_label_overrides_target"
        ),
        sa.CheckConstraint(_LABEL_ENTITY_KIND, name="entity_kind_allowed"),
        sa.CheckConstraint(_LABEL_FIELD, name="field_allowed"),
        sa.CheckConstraint(_LABEL_SOURCE, name="source_allowed"),
        sa.CheckConstraint(_LABEL_STATUS, name="status_allowed"),
    )

    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", _JSON, nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rotated_from_id"], ["mcp_tokens.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash", name="uq_mcp_tokens_token_hash"),
    )
    op.create_index("ix_mcp_tokens_user", "mcp_tokens", ["user_id"])

    op.create_table(
        "user_path_flags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("path_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=True),
        sa.Column("flag", sa.String(length=12), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["path_id"], ["career_paths.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["career_path_steps.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_PATH_FLAG, name="flag_allowed"),
    )
    op.create_index(
        "uq_user_path_flags_step",
        "user_path_flags",
        ["user_id", "path_id", "step_id"],
        unique=True,
        sqlite_where=sa.text("step_id IS NOT NULL"),
        postgresql_where=sa.text("step_id IS NOT NULL"),
    )
    op.create_index(
        "uq_user_path_flags_path",
        "user_path_flags",
        ["user_id", "path_id"],
        unique=True,
        sqlite_where=sa.text("step_id IS NULL"),
        postgresql_where=sa.text("step_id IS NULL"),
    )

    op.add_column("users", sa.Column("locale", sa.String(length=8), nullable=True))

    with op.batch_alter_table("job_sources") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="posting")
        )
        batch.add_column(sa.Column("schedule_kind", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("last_status", sa.String(length=12), nullable=False, server_default="ok")
        )
        batch.create_check_constraint("kind_allowed", _SOURCE_KIND)
        batch.create_check_constraint("last_status_allowed", _HEALTH)

    with op.batch_alter_table("career_path_steps") as batch:
        batch.add_column(sa.Column("parent_step_id", sa.Uuid(), nullable=True))
        # The server default must SURVIVE the batch rebuild: SQLite copies
        # every existing row into `_alembic_tmp_*`, and a NOT NULL column
        # with no default fails that copy on a populated desktop database.
        batch.add_column(
            sa.Column("edge_label", sa.String(length=120), nullable=False, server_default="")
        )
        batch.create_foreign_key(
            "fk_career_path_steps_parent_step_id_career_path_steps",
            "career_path_steps",
            ["parent_step_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_career_path_steps_parent_step_id", "career_path_steps", ["parent_step_id"])

    with op.batch_alter_table("profile_proposals") as batch:
        batch.alter_column(
            "source",
            existing_type=sa.String(length=12),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
        batch.add_column(sa.Column("origin", _JSON, nullable=False, server_default="{}"))
        batch.drop_constraint("source_allowed", type_="check")
        batch.create_check_constraint("source_allowed", _PROPOSAL_SOURCE)

    op.add_column(
        "posting_fits", sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("posting_fits", sa.Column("fit_version", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE posting_fits SET computed_at = updated_at, fit_version = 5 "
        "WHERE computed_at IS NULL"
    )
    with op.batch_alter_table("posting_fits") as batch:
        batch.alter_column(
            "computed_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch.alter_column("fit_version", existing_type=sa.Integer(), nullable=False)
    op.create_index("ix_posting_fits_user_computed", "posting_fits", ["user_id", "computed_at"])

    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_constraint("channel_allowed", type_="check")
        batch.create_check_constraint("channel_allowed", _CHANNEL)


def downgrade() -> None:
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_constraint("channel_allowed", type_="check")
        batch.create_check_constraint("channel_allowed", _NOTIFICATION_CHANNEL)

    op.drop_index("ix_posting_fits_user_computed", table_name="posting_fits")
    with op.batch_alter_table("posting_fits") as batch:
        batch.drop_column("fit_version")
        batch.drop_column("computed_at")

    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("source_allowed", type_="check")
        batch.create_check_constraint("source_allowed", _PROPOSAL_SOURCE_OLD)
        batch.drop_column("origin")
        batch.alter_column(
            "source",
            existing_type=sa.String(length=16),
            type_=sa.String(length=12),
            existing_nullable=False,
        )

    op.drop_index("ix_career_path_steps_parent_step_id", table_name="career_path_steps")
    with op.batch_alter_table("career_path_steps") as batch:
        batch.drop_constraint(
            "fk_career_path_steps_parent_step_id_career_path_steps", type_="foreignkey"
        )
        batch.drop_column("edge_label")
        batch.drop_column("parent_step_id")

    with op.batch_alter_table("job_sources") as batch:
        batch.drop_constraint("last_status_allowed", type_="check")
        batch.drop_constraint("kind_allowed", type_="check")
        batch.drop_column("last_status")
        batch.drop_column("paused_at")
        batch.drop_column("schedule_kind")
        batch.drop_column("kind")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("locale")

    op.drop_index("uq_user_path_flags_path", table_name="user_path_flags")
    op.drop_index("uq_user_path_flags_step", table_name="user_path_flags")
    op.drop_table("user_path_flags")
    op.drop_index("ix_mcp_tokens_user", table_name="mcp_tokens")
    op.drop_table("mcp_tokens")
    op.drop_table("label_overrides")
    op.drop_index("ix_webhook_endpoints_source", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
    op.drop_table("user_channel_configs")
    op.drop_index("ix_user_feed_tokens_user_kind", table_name="user_feed_tokens")
    op.drop_table("user_feed_tokens")
    op.drop_table("followup_rules")
    op.drop_index("ix_application_events_application_at", table_name="application_events")
    op.drop_table("application_events")
    op.drop_index("ix_applications_posting_id", table_name="applications")
    op.drop_index("ix_applications_user_next_followup", table_name="applications")
    op.drop_index("ix_applications_user_stage", table_name="applications")
    op.drop_table("applications")
