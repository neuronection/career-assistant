"""Plan 50 P2b — mapping provenance for the bounded semantic rerank.

Adds two additive columns to ``job_postings``:

* ``mapping_version`` — the plan-164 decision-version stamp (default 0 for
  rows that predate the v2 decision). The ``POSTING_REMAP`` sweep can use it
  later; this slice only writes it.
* ``mapping_features`` — the bounded, validated audit payload (candidates,
  deterministic/semantic/blend scores, shared taxonomy keys, per-view
  scores, pinned policy thresholds, embedding ``space_key`` and the
  structured degradation reason). ``StructuredJSON`` on both dialects.

Two indexes support the cutover invalidation query
(``mapping_method IN ('semantic','semantic_rerank')`` ordered by id) and the
future version sweep. No ``mapping_dirty`` column is added: this slice's
``POSTING_REMAP`` seam selects by method + recorded ``space_key``, so the
derived flag is not needed yet (plan 164 D15 remains the scale follow-up).

Downgrade drops both indexes and both columns; the payload is derived audit
data and is rebuilt by re-deciding the postings.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("job_postings", sa.Column("mapping_features", _JSON, nullable=True))
    op.create_index("ix_postings_mapping_version", "job_postings", ["mapping_version"])
    op.create_index("ix_postings_mapping_method", "job_postings", ["mapping_method"])


def downgrade() -> None:
    op.drop_index("ix_postings_mapping_method", table_name="job_postings")
    op.drop_index("ix_postings_mapping_version", table_name="job_postings")
    op.drop_column("job_postings", "mapping_features")
    op.drop_column("job_postings", "mapping_version")
