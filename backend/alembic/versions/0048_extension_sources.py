"""Plan 32 Phase 3 / ADR-0040 D13+D22: the extension import layer's store.

Two tables: ``extension_sources`` (git sources — https production
descriptors + the dev/test local variant) and ``extension_installs``
(digest-pinned, consent-tracked imported extensions; content-addressed on
disk under data_dir/extensions/<id>/<digest>/, never importlib'd).

Rider: the scheduler gains the ``system_extension_reconcile`` slot whose
``extension_reconcile`` job runs the GitOps desired-state reconcile at a
fixed cadence (boot reconcile rides the app lifespan) — both mirrored
CHECKs widen in the same commit (the enum members land with this
migration).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "system_source_sync",
    "system_digest",
    "system_demand_import",
    "system_refit_sweep",
    "system_catalog_enrich",
    "system_followups",
    "system_market_history",
    "system_proposal_sweep",
    "system_checkpoint_prune",
    "user_saved_search",
    "user_checkin",
    "user_autopilot",
)
NEW_KINDS = (*OLD_KINDS, "system_extension_reconcile")

OLD_TASKS = (
    "posting_sync",
    "digest",
    "saved_search_run",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
    "followup_sweep",
    "market_history_capture",
    "proposal_sweep",
    "checkpoint_prune",
)
NEW_TASKS = (*OLD_TASKS, "extension_reconcile")


def _constraint_sql(kinds: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{kind}'" for kind in kinds)
    return f"kind IN ({joined})"


def _task_sql(tasks: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{task}'" for task in tasks)
    return f"task IS NULL OR task IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "extension_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("origin", sa.String(length=600), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("descriptor", _JSON, nullable=False),
        sa.Column("candidates", _JSON, nullable=False),
        sa.Column("secrets", _JSON, nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("origin", name="uq_extension_sources_origin"),
        sa.CheckConstraint("kind IN ('git', 'local')", name="source_kind_allowed"),
        sa.CheckConstraint(
            "status IN ('ok', 'degraded', 'failing', 'stale')",
            name="source_status_allowed",
        ),
        sa.CheckConstraint("consecutive_failures >= 0", name="source_failures_nonneg"),
    )
    op.create_table(
        "extension_installs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("extension_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("manifest", _JSON, nullable=False),
        sa.Column("pin_ref", sa.String(length=200), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("content_path", sa.String(length=1024), nullable=False),
        sa.Column("tier", sa.String(length=4), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("managed_by", sa.String(length=10), nullable=False),
        sa.Column("source_key", sa.String(length=80), nullable=True),
        sa.Column("consents", _JSON, nullable=False),
        sa.Column("pin_history", _JSON, nullable=False),
        sa.Column("update", _JSON, nullable=False),
        sa.Column("parked", sa.Boolean, nullable=False),
        sa.Column("installed_by", sa.Uuid(), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["extension_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["installed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("extension_id", name="uq_extension_installs_extension"),
        sa.CheckConstraint(
            "state IN ('installed', 'disabled', 'self-disabled', 'removed')",
            name="install_state_allowed",
        ),
        sa.CheckConstraint("managed_by IN ('manual', 'gitops')", name="install_managed_by_allowed"),
        sa.CheckConstraint("tier IN ('T0', 'T3')", name="install_tier_allowed"),
    )
    op.create_index("ix_extension_installs_source", "extension_installs", ["source_id"])
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(NEW_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(NEW_TASKS))


def downgrade() -> None:
    op.execute("DELETE FROM schedules WHERE kind = 'system_extension_reconcile'")
    op.execute("DELETE FROM background_jobs WHERE job_type = 'extension_reconcile'")
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(OLD_KINDS))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", _task_sql(OLD_TASKS))
    op.drop_index("ix_extension_installs_source", table_name="extension_installs")
    op.drop_table("extension_installs")
    op.drop_table("extension_sources")
