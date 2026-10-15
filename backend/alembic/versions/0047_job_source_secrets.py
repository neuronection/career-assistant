"""Plan 32 Phase 1 / ADR-0040 D19: job-source secrets move out of plaintext
``job_sources.config`` into atrest-sealed slots.

New column ``job_sources.secrets`` (StructuredJSON): a map of secret-slot
id → ``enc::``-sealed value, exactly the ``ai_providers.api_key_encrypted``
discipline (settings-map INV-4: the product secret store, never plaintext
config). The one legacy plaintext credential (``ats_api``'s
``config.api_token``) is MOVED — sealed into the new slot and stripped
from config — so no secret survives in plaintext storage.

Destructive by doctrine (pre-release databases are dev artifacts): the
downgrade drops the column — sealed values are deleted, never leaked back
into config.

Revision ID: 0047
Revises: 0046
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# Mirrors app.models.base.StructuredJSON (JSONB on PostgreSQL, JSON on
# SQLite) — inline so this history keeps matching the stored column.
_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0047"
down_revision = "0046"

_job_sources = sa.table(
    "job_sources",
    sa.column("id", sa.UUID),
    sa.column("config", _JSON),
    sa.column("secrets", _JSON),
)


def upgrade() -> None:
    op.add_column(
        "job_sources",
        sa.Column("secrets", _JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    bind = op.get_bind()
    from app.core.encryption import encrypt_secret

    for row in bind.execute(sa.select(_job_sources.c.id, _job_sources.c.config)).fetchall():
        config = row.config if isinstance(row.config, dict) else {}
        token = config.get("api_token")
        if not token:
            continue
        bind.execute(
            sa.update(_job_sources)
            .where(_job_sources.c.id == row.id)
            .values(
                secrets={"api_token": encrypt_secret(str(token))},
                config={k: v for k, v in config.items() if k != "api_token"},
            )
        )


def downgrade() -> None:
    """Sealed values are deleted, never leaked back into plaintext config."""
    op.drop_column("job_sources", "secrets")
