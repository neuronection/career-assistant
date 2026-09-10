"""Semantic-search embeddings: the ai_embeddings table.

The migration also best-effort provisions the pgvector extension on
Postgres (self-hosters without it keep working — the store's JSONB
vector is the single source of truth on every dialect)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _try_enable_pgvector() -> bool:
    """CREATE EXTENSION is best-effort: unprivileged installs keep
    working (the JSONB store never depends on the extension). The
    attempt runs in AUTOCOMMIT so a failure can't poison the
    migration's transaction."""
    if op.get_bind().dialect.name != "postgresql":
        return False
    try:
        conn = op.get_bind().execution_options(isolation_level="AUTOCOMMIT")
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        return True
    except Exception:  # noqa: BLE001 — extension is an optimization only
        return False


def upgrade() -> None:
    _enabled = _try_enable_pgvector()
    op.create_table(
        "ai_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_kind", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "entity_kind", "entity_id", name="uq_ai_embeddings_entity"
        ),
    )
    op.create_index(
        "ix_ai_embeddings_kind_dim", "ai_embeddings", ["entity_kind", "dim"]
    )
    if _enabled:
        # Provisioned for a future operator-accelerated read path; the
        # application never requires it (no schema dependency).
        print("pgvector extension available — acceleration column deferred")


def downgrade() -> None:
    op.drop_index("ix_ai_embeddings_kind_dim", table_name="ai_embeddings")
    op.drop_table("ai_embeddings")
