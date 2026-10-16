"""Plan 32 Phase 5 / ADR-0030 (Python port): the T2 sandbox runner's store.

Three shapes in one migration:

* ``extension_installs.tier`` widens to carry ``T2`` — tier is provenance
  at install time (D2): an imported connector whose artifact is a
  capability-RPC module (``extension.py``) is a T2 sandbox extension, and
  the install row is the provenance record;
* ``extension_installs.extension_state`` — the T2 ``state.*`` seam home
  (charter `state` capability): extension-owned persistent key/values,
  host-quota'd by ``limits.stateMaxBytes`` per instance, evictable,
  distinct from sync cursors (which never cross the seam);
* ``extension_sandbox_runs`` — one row per spawned sandbox process
  (outcome + capped reason); boot reconciliation closes host-restart
  orphans as ``interrupted``, sandbox death self-disables the extension
  (ADR-0030's AppService boot pattern, ported).

Model-first (family-migration §1): mirrors
``app.models.extension_model`` exactly.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")
revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extension_installs") as batch:
        batch.drop_constraint("install_tier_allowed", type_="check")
        batch.create_check_constraint("install_tier_allowed", "tier IN ('T0', 'T2', 'T3')")
        batch.add_column(
            sa.Column(
                "extension_state",
                _JSON,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
    op.create_table(
        "extension_sandbox_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("install_id", sa.Uuid(), nullable=False),
        sa.Column("extension_id", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["install_id"], ["extension_installs.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "outcome IN ('running', 'completed', 'disposed', 'crashed', 'watchdog', "
            "'protocol-violation', 'interrupted')",
            name="sandbox_run_outcome_allowed",
        ),
    )
    op.create_index(
        "ix_extension_sandbox_runs_install",
        "extension_sandbox_runs",
        ["install_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_extension_sandbox_runs_install", table_name="extension_sandbox_runs")
    op.drop_table("extension_sandbox_runs")
    with op.batch_alter_table("extension_installs") as batch:
        batch.drop_column("extension_state")
        batch.drop_constraint("install_tier_allowed", type_="check")
        batch.create_check_constraint("install_tier_allowed", "tier IN ('T0', 'T3')")
