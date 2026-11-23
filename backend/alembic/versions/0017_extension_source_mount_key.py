"""Operator feeder: extension_sources.mount_key / mount_path (ADR-0071).

A mounted source records the operator's folder (``mount_path``) and a stable
identity for ``(resolved folder, subpath)`` (``mount_key``, unique). Both are
host-local provenance: the staged repository path remains the transport
``origin``. Nullable, no backfill — existing rows are git/local sources.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extension_sources", sa.Column("mount_key", sa.String(length=32), nullable=True))
    op.add_column(
        "extension_sources", sa.Column("mount_path", sa.String(length=600), nullable=True)
    )
    op.create_index(
        "ix_extension_sources_mount_key", "extension_sources", ["mount_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_extension_sources_mount_key", table_name="extension_sources")
    op.drop_column("extension_sources", "mount_path")
    op.drop_column("extension_sources", "mount_key")
