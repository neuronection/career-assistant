"""Detail enrichment: per-posting fetch state + the config fold that
replaces the ``fetch_details`` bool with the ``detail_mode`` enum.

``detail_fetched_at`` is NULL until the posting's job-description page
was fetched; ``detail_attempts`` counts tried fetches (a permanently
failing id stops being queued). The data fold maps stored
``fetch_details`` (true → ``sample``, otherwise ``off``) and drops the
old key — the mode enum is the only user-facing shape from here on.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("detail_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column("detail_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_postings_detail", "job_postings", ["source_id", "detail_fetched_at"])

    bind = op.get_bind()
    sources = sa.table("job_sources", sa.column("id", sa.Uuid()), sa.column("config", _JSON))
    for row in bind.execute(sa.select(sources.c.id, sources.c.config)).fetchall():
        config = dict(row.config or {})
        if "fetch_details" not in config:
            continue
        enabled = bool(config.pop("fetch_details"))
        config["detail_mode"] = "sample" if enabled else "off"
        bind.execute(sources.update().where(sources.c.id == row.id).values(config=config))


def downgrade() -> None:
    bind = op.get_bind()
    sources = sa.table("job_sources", sa.column("id", sa.Uuid()), sa.column("config", _JSON))
    for row in bind.execute(sa.select(sources.c.id, sources.c.config)).fetchall():
        config = dict(row.config or {})
        if "detail_mode" not in config:
            continue
        enabled = str(config.pop("detail_mode")) == "sample"
        config["fetch_details"] = enabled
        bind.execute(sources.update().where(sources.c.id == row.id).values(config=config))

    op.drop_index("ix_postings_detail", table_name="job_postings")
    op.drop_column("job_postings", "detail_attempts")
    op.drop_column("job_postings", "detail_fetched_at")
