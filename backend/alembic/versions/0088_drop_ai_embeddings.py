"""Plan 50 P1d: the destructive cutover — the legacy embeddings store is gone.

Deployment order (the reason this is its own revision, not a rewrite of the
P1a one):

1. ship the P1a/P1b/P1c store, run the backfill
   (``POST /api/v1/admin/retrieval/reconcile`` or
   ``scripts/reindex_vectors.py``) and confirm coverage for ``posting``,
   ``profile`` and ``skill`` in ``retrieval_coverage_snapshots``;
2. deploy this revision. It drops ``ai_embeddings`` — the old single-vector
   JSONB store — because every read now goes through ``vector_spaces`` /
   ``vector_documents`` / ``vector_records`` and the retrieval service.

Also folded in, because they are the same cutover:

* the ``schedules`` vocabulary swaps ``system_embeddings_reconcile`` /
  ``embeddings_reconcile`` for ``system_vector_reconcile`` /
  ``vector_reconcile`` (the job is now the store-wide reconcile, not the
  skill-only one), so the boot-provisioned row passes the CHECK;
* the obsolete ``catalog.semantic_rescue`` switch row is deleted — the
  semantic rescue lived on ``ai_embeddings`` and returns on the family store
  with the long-text matcher (plan 50 P2).

Downgrade recreates ``ai_embeddings`` exactly as revision 0021 defined it and
restores the previous vocabulary; the embed *rows* are not restored — they are
derived data, rebuilt by running the old recompute path.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_OLD_KINDS = (
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
    "system_skill_relation_learn",
    "system_embeddings_reconcile",
    "user_saved_search",
    "user_radar_digest",
    "user_smart_digest",
    "user_checkin",
    "user_autopilot",
)
_NEW_KINDS = tuple(
    "system_vector_reconcile" if value == "system_embeddings_reconcile" else value
    for value in _OLD_KINDS
)

_OLD_TASKS = (
    "posting_sync",
    "digest",
    "saved_search_run",
    "radar_digest",
    "smart_digest",
    "fit_refit",
    "catalog_enrich",
    "autopilot_run",
    "followup_sweep",
    "market_history_capture",
    "proposal_sweep",
    "checkpoint_prune",
    "extension_reconcile",
    "demand_import",
    "skill_relation_learn",
    "embeddings_reconcile",
)
_NEW_TASKS = tuple(
    "vector_reconcile" if value == "embeddings_reconcile" else value for value in _OLD_TASKS
)


def _in_sql(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


def _set_vocabulary(kinds: tuple[str, ...], tasks: tuple[str, ...]) -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _in_sql("kind", kinds))
        batch.drop_constraint("task_allowed", type_="check")
        batch.create_check_constraint("task_allowed", f"task IS NULL OR {_in_sql('task', tasks)}")


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM schedules WHERE kind = 'system_embeddings_reconcile' "
            "OR task = 'embeddings_reconcile'"
        )
    )
    _set_vocabulary(_NEW_KINDS, _NEW_TASKS)
    op.execute(sa.text("DELETE FROM app_settings WHERE key = 'catalog.semantic_rescue'"))
    op.drop_index("ix_ai_embeddings_kind_dim", table_name="ai_embeddings")
    op.drop_table("ai_embeddings")


def downgrade() -> None:
    op.create_table(
        "ai_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_kind", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entity_kind", "entity_id", name="uq_ai_embeddings_entity"),
    )
    op.create_index("ix_ai_embeddings_kind_dim", "ai_embeddings", ["entity_kind", "dim"])
    op.execute(
        sa.text(
            "DELETE FROM schedules WHERE kind = 'system_vector_reconcile' "
            "OR task = 'vector_reconcile'"
        )
    )
    _set_vocabulary(_OLD_KINDS, _OLD_TASKS)
