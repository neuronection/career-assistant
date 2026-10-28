"""Skill taxonomy graph (plan 138): `skill_relations`, the typed edge
table over `skills` (is_a | synonym | part_of | related_to; proposed →
approved | rejected negative edge), plus the `schedules.kind_allowed`
widen that reserves the `system_skill_relation_learn` slot early (safe —
a wider CHECK rejects nothing that used to pass; the enum member ships
with this widen to keep the enum↔CHECK parity wall green).

Symmetric kinds are stored canonically ordered (from_skill_id = the
lower UUID) so one unordered pair can never carry two rows; the
`symmetric_pair_ordered` CHECK enforces it at the schema level.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")
_UUID = UUID().with_variant(sa.Text(), "sqlite")

revision = "0067"
down_revision = "0066"
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
    "system_extension_reconcile",
    "user_saved_search",
    "user_radar_digest",
    "user_checkin",
    "user_autopilot",
)
NEW_KINDS = (*OLD_KINDS, "system_skill_relation_learn")


def _constraint_sql(kinds: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{kind}'" for kind in kinds)
    return f"kind IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "skill_relations",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("from_skill_id", _UUID, nullable=False),
        sa.Column("to_skill_id", _UUID, nullable=False),
        sa.Column("relation", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("evidence", _JSON, nullable=True),
        sa.Column("decided_by", _UUID, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["from_skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "from_skill_id", "to_skill_id", "relation", name="uq_skill_relation_edge"
        ),
        sa.CheckConstraint("from_skill_id != to_skill_id", name="no_self_loop"),
        sa.CheckConstraint(
            "relation IN ('is_a', 'synonym', 'part_of', 'related_to')",
            name="relation_allowed",
        ),
        sa.CheckConstraint("status IN ('proposed', 'approved', 'rejected')", name="status_allowed"),
        sa.CheckConstraint(
            "source IN ('llm', 'manual', 'import', 'derived')", name="source_allowed"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "relation IN ('is_a', 'part_of') OR from_skill_id <= to_skill_id",
            name="symmetric_pair_ordered",
        ),
    )
    op.create_index("ix_skill_relations_from", "skill_relations", ["from_skill_id"])
    op.create_index("ix_skill_relations_to", "skill_relations", ["to_skill_id"])
    op.create_index("ix_skill_relations_relation_status", "skill_relations", ["relation", "status"])
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(NEW_KINDS))


def downgrade() -> None:
    op.execute("DELETE FROM schedules WHERE kind = 'system_skill_relation_learn'")
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(OLD_KINDS))
    op.drop_index("ix_skill_relations_relation_status", table_name="skill_relations")
    op.drop_index("ix_skill_relations_to", table_name="skill_relations")
    op.drop_index("ix_skill_relations_from", table_name="skill_relations")
    op.drop_table("skill_relations")
