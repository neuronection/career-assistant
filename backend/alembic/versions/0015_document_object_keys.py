"""Add the nullable document object key (DDL only).

Documents move from reconstructed `<upload_dir>/<id><ext>` paths to opaque
object keys. This revision only adds `documents.object_key` and its index:
the key/extraction/export backfill is a data migration that must run **after**
`migrate-objects --verify`, never at schema-upgrade time (the object bytes may
not exist yet on this host).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("object_key", sa.String(length=1024), nullable=True))
    op.create_index("ix_documents_object_key", "documents", ["object_key"])


def downgrade() -> None:
    op.drop_index("ix_documents_object_key", table_name="documents")
    op.drop_column("documents", "object_key")
