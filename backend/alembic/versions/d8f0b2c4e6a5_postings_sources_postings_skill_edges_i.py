"""postings: sources, postings, skill edges, interactions + scope/kind checks (Phase 26)

Revision ID: d8f0b2c4e6a5
Revises: c5e7a9b1d3f2
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "d8f0b2c4e6a5"
down_revision: Union[str, None] = "c5e7a9b1d3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _widen_checks() -> None:
    """search_history.scope gains 'postings'; notification_rules.kind gains
    'new_posting_match' (destructive recreation — pre-launch, no BC)."""
    if _is_sqlite():
        with op.batch_alter_table("search_history") as batch:
            batch.drop_constraint(
                op.f("ck_search_history_scope_allowed"), type_="check"
            )
            batch.create_check_constraint(
                op.f("ck_search_history_scope_allowed"),
                "scope IN ('catalog', 'rankings', 'universities', 'postings')",
            )
        with op.batch_alter_table("notification_rules") as batch:
            batch.drop_constraint(
                op.f("ck_notification_rules_kind_supported"), type_="check"
            )
            batch.create_check_constraint(
                op.f("ck_notification_rules_kind_supported"),
                "kind IN ('fit_threshold', 'new_in_family', 'new_posting_match')",
            )
    else:
        op.execute(
            "ALTER TABLE search_history DROP CONSTRAINT "
            "ck_search_history_scope_allowed"
        )
        op.execute(
            "ALTER TABLE search_history ADD CONSTRAINT "
            "ck_search_history_scope_allowed CHECK (scope IN "
            "('catalog', 'rankings', 'universities', 'postings'))"
        )
        op.execute(
            "ALTER TABLE notification_rules DROP CONSTRAINT "
            "ck_notification_rules_kind_supported"
        )
        op.execute(
            "ALTER TABLE notification_rules ADD CONSTRAINT "
            "ck_notification_rules_kind_supported CHECK (kind IN "
            "('fit_threshold', 'new_in_family', 'new_posting_match'))"
        )


def upgrade() -> None:
    op.bulk_insert(
        sa.table(
            "notification_kinds",
            sa.column("id", sa.Uuid),
            sa.column("key", sa.String),
            sa.column("label", sa.String),
            sa.column("group", sa.String),
            sa.column("severity", sa.String),
            sa.column("default_enabled", sa.Boolean),
            sa.column("default_channels", sa.JSON),
            sa.column("mutable", sa.Boolean),
        ),
        [
            {
                "id": UUID("a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8003"),
                "key": "new_posting_match",
                "label": "New posting match",
                "group": "postings",
                "severity": "info",
                "default_enabled": True,
                "default_channels": ["in_app"],
                "mutable": True,
            }
        ],
    )
    op.create_table(
        "job_sources",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("connector_key", sa.String(length=80), nullable=False),
        sa.Column("config", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_state", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_sources")),
        sa.UniqueConstraint("key", name=op.f("uq_job_sources_key")),
        sa.CheckConstraint(
            "length(connector_key) BETWEEN 1 AND 80",
            name=op.f("ck_job_sources_connector_key_present"),
        ),
    )

    op.create_table(
        "job_postings",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("org", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("location", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("seniority", sa.String(length=20), nullable=True),
        sa.Column("employment_type", sa.String(length=20), nullable=True),
        sa.Column("contract_type", sa.String(length=60), nullable=True),
        sa.Column("onsite_policy", sa.String(length=20), nullable=True),
        sa.Column("work_hours", sa.String(length=60), nullable=True),
        sa.Column("hours_per_week_min", sa.Float(), nullable=True),
        sa.Column("hours_per_week_max", sa.Float(), nullable=True),
        sa.Column("travel_class", sa.String(length=60), nullable=True),
        sa.Column("education_level", sa.String(length=40), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("salary_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("salary_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("salary_period", sa.String(length=10), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw", StructuredJSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("posting_facts", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("catalog_job_id", sa.Uuid(), nullable=True),
        sa.Column("mapping_method", sa.String(length=20), nullable=True),
        sa.Column("mapping_confidence", sa.Float(), nullable=True),
        sa.Column("mapping_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_postings")),
        sa.ForeignKeyConstraint(
            ["source_id"], ["job_sources.id"],
            name=op.f("fk_job_postings_source_id_job_sources"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_job_id"], ["jobs.id"],
            name=op.f("fk_job_postings_catalog_job_id_jobs"), ondelete="SET NULL",
        ),
        sa.UniqueConstraint("source_id", "external_id",
                            name="uq_postings_source_external"),
        sa.CheckConstraint(
            "status IN ('new', 'mapped', 'expired', 'hidden')",
            name=op.f("ck_job_postings_status_allowed"),
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name=op.f("ck_job_postings_salary_range_sane"),
        ),
    )
    op.create_index(
        op.f("ix_job_postings_seniority"), "job_postings", ["seniority"], unique=False
    )
    op.create_index(
        "ix_postings_status_posted", "job_postings", ["status", "posted_at"],
        unique=False,
    )
    op.create_index(
        "ix_postings_catalog_job", "job_postings", ["catalog_job_id"], unique=False
    )
    op.create_index(
        "ix_postings_expires_at", "job_postings", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_postings_salary_min", "job_postings", ["salary_min"], unique=False
    )

    op.create_table(
        "posting_skills",
        sa.Column("posting_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("evidence", sa.String(length=20), nullable=False,
                  server_default="explicit"),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("required_level", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posting_skills")),
        sa.ForeignKeyConstraint(
            ["posting_id"], ["job_postings.id"],
            name=op.f("fk_posting_skills_posting_id_job_postings"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"],
            name=op.f("fk_posting_skills_skill_id_skills"), ondelete="CASCADE",
        ),
        sa.UniqueConstraint("posting_id", "skill_id",
                            name="uq_posting_skills_posting_skill"),
        sa.CheckConstraint(
            "required_level IS NULL OR (required_level >= 1 AND required_level <= 10)",
            name=op.f("ck_posting_skills_required_level_range"),
        ),
    )
    op.create_index(
        "ix_posting_skills_skill_id", "posting_skills", ["skill_id"], unique=False
    )

    op.create_table(
        "posting_interactions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_via_url", sa.String(length=1000), nullable=False,
                  server_default=""),
        sa.Column("stage", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posting_interactions")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_posting_interactions_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"], ["job_postings.id"],
            name=op.f("fk_posting_interactions_posting_id_job_postings"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "posting_id",
                            name="uq_posting_interactions_user_posting"),
    )
    op.create_index(
        "ix_posting_interactions_posting_id", "posting_interactions",
        ["posting_id"], unique=False,
    )
    op.create_index(
        op.f("ix_posting_interactions_user_id"), "posting_interactions",
        ["user_id"], unique=False,
    )

    _widen_checks()


def downgrade() -> None:
    op.execute(
        "DELETE FROM notifications WHERE kind_id = "
        "(SELECT id FROM notification_kinds WHERE key = 'new_posting_match')"
    )
    op.execute(
        "DELETE FROM notification_kinds WHERE key = 'new_posting_match'"
    )
    if not _is_sqlite():
        op.execute(
            "ALTER TABLE search_history DROP CONSTRAINT "
            "ck_search_history_scope_allowed"
        )
        op.execute(
            "ALTER TABLE search_history ADD CONSTRAINT "
            "ck_search_history_scope_allowed CHECK (scope IN "
            "('catalog', 'rankings', 'universities'))"
        )
        op.execute(
            "ALTER TABLE notification_rules DROP CONSTRAINT "
            "ck_notification_rules_kind_supported"
        )
        op.execute(
            "ALTER TABLE notification_rules ADD CONSTRAINT "
            "ck_notification_rules_kind_supported CHECK (kind IN "
            "('fit_threshold', 'new_in_family'))"
        )
    else:
        with op.batch_alter_table("search_history") as batch:
            batch.drop_constraint(
                op.f("ck_search_history_scope_allowed"), type_="check"
            )
            batch.create_check_constraint(
                op.f("ck_search_history_scope_allowed"),
                "scope IN ('catalog', 'rankings', 'universities')",
            )
        with op.batch_alter_table("notification_rules") as batch:
            batch.drop_constraint(
                op.f("ck_notification_rules_kind_supported"), type_="check"
            )
            batch.create_check_constraint(
                op.f("ck_notification_rules_kind_supported"),
                "kind IN ('fit_threshold', 'new_in_family')",
            )
    op.drop_index(op.f("ix_posting_interactions_user_id"),
                  table_name="posting_interactions")
    op.drop_index("ix_posting_interactions_posting_id",
                  table_name="posting_interactions")
    op.drop_table("posting_interactions")
    op.drop_index("ix_posting_skills_skill_id", table_name="posting_skills")
    op.drop_table("posting_skills")
    op.drop_index("ix_postings_salary_min", table_name="job_postings")
    op.drop_index("ix_postings_expires_at", table_name="job_postings")
    op.drop_index("ix_postings_catalog_job", table_name="job_postings")
    op.drop_index("ix_postings_status_posted", table_name="job_postings")
    op.drop_index(op.f("ix_job_postings_seniority"), table_name="job_postings")
    op.drop_table("job_postings")
    op.drop_table("job_sources")
