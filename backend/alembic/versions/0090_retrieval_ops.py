"""Plan 51 Q1a — the retrieval-ops migration checkpoint.

Adds the three data seams the family retrieval-operations contract
(``app/storage/retrieval_ops.py``) pins at Q0:

* ``ai_generations.metadata`` — caller-supplied embedding tags
  (``space_id``/``kind``/``view``/``chunk_index``), ``JSONB`` on PostgreSQL
  and ``JSON`` on SQLite, ``NOT NULL`` default ``'{}'``. The gateway writes
  exactly what the caller handed it and never invents a tag.
* ``ai_generations.metadata_schema_version`` — the sibling version pin
  (``SMALLINT``, default 1), so an incompatible tag-shape change is explicit.
* ``background_jobs.idempotency_key`` / ``background_jobs.lock_key`` — the
  nullable request-replay and single-active-run handles. Two partial unique
  indexes over ``status IN ('queued', 'running')`` are the DB-level
  invariant; terminal rows never block a retry. The runtime that allocates
  them lands in Q1b.

The two bounded rollup stores (``retrieval_query_rollups`` /
``retrieval_coverage_snapshots``) already exist from ``0087`` and are
deliberately not recreated here. Downgrade drops the two indexes and four
columns; the tags are derived audit metadata and the migration checkpoint is
the only writer of the shape.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_ACTIVE = "status IN ('queued', 'running')"
_IDEMPOTENCY_WHERE = sa.text(f"idempotency_key IS NOT NULL AND {_ACTIVE}")
_LOCK_KEY_WHERE = sa.text(f"lock_key IS NOT NULL AND {_ACTIVE}")


def upgrade() -> None:
    op.add_column(
        "ai_generations",
        sa.Column("metadata", _JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "ai_generations",
        sa.Column("metadata_schema_version", sa.SmallInteger(), nullable=False, server_default="1"),
    )

    op.add_column(
        "background_jobs", sa.Column("idempotency_key", sa.String(length=120), nullable=True)
    )
    op.add_column("background_jobs", sa.Column("lock_key", sa.String(length=120), nullable=True))

    op.create_index(
        "uq_background_jobs_idempotency_active",
        "background_jobs",
        ["job_type", "idempotency_key"],
        unique=True,
        postgresql_where=_IDEMPOTENCY_WHERE,
        sqlite_where=_IDEMPOTENCY_WHERE,
    )
    op.create_index(
        "uq_background_jobs_lock_key_active",
        "background_jobs",
        ["lock_key"],
        unique=True,
        postgresql_where=_LOCK_KEY_WHERE,
        sqlite_where=_LOCK_KEY_WHERE,
    )


def downgrade() -> None:
    op.drop_index("uq_background_jobs_lock_key_active", table_name="background_jobs")
    op.drop_index("uq_background_jobs_idempotency_active", table_name="background_jobs")
    op.drop_column("background_jobs", "lock_key")
    op.drop_column("background_jobs", "idempotency_key")
    op.drop_column("ai_generations", "metadata_schema_version")
    op.drop_column("ai_generations", "metadata")
