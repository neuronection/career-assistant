"""Plan 148 — skill change journal.

Append-only ``skill_changes``: one row per real skill lifecycle change
(created/updated/promoted/auto_promoted/deprecated/restored/merged/
deleted) with its actor, written through the single
``SkillChangeJournal.record`` seam by every writer (admin taxonomy
seams, the plan-147 corroboration auto-promotion, proposal creation,
tree-maintenance writes). ``skill_id`` is nullable with ON DELETE SET
NULL and every row carries denormalized ``skill_key``/``skill_label``
snapshots — deleting a skill keeps its audit trail. The empty-diff gate
keeps no-op writes out; ``actor_ref``/``detail`` carry ids and capped
diffs only. Downgrade drops the table (rows are operational history,
like ``posting_changes``).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_EVENT = (
    "event IN ("
    "'created', 'updated', 'promoted', 'auto_promoted', "
    "'deprecated', 'restored', 'merged', 'deleted')"
)
_ACTOR_KIND = "actor_kind IN ('admin', 'system', 'sync', 'job', 'user')"

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=True),
        sa.Column("skill_key", sa.String(length=80), nullable=False),
        sa.Column("skill_label", sa.String(length=120), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event", sa.String(length=20), nullable=False),
        sa.Column("actor_kind", sa.String(length=20), nullable=False),
        sa.Column("actor_ref", _JSON, nullable=True),
        sa.Column("detail", _JSON, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_EVENT, name="event_allowed"),
        sa.CheckConstraint(_ACTOR_KIND, name="actor_kind_allowed"),
    )
    op.create_index("ix_skill_changes_skill_occurred", "skill_changes", ["skill_id", "occurred_at"])
    op.create_index("ix_skill_changes_key_occurred", "skill_changes", ["skill_key", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_skill_changes_key_occurred", table_name="skill_changes")
    op.drop_index("ix_skill_changes_skill_occurred", table_name="skill_changes")
    op.drop_table("skill_changes")
