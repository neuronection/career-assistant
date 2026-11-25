"""Drop the boot-provisioned bundled seed provider (plan 218).

The app no longer ships a seed catalog: packs arrive from an uploaded zip, a
Git/index provider, or the official repository (which boot registers as
disabled tiles). Existing databases may still carry the system row boot used
to create ("Bundled presets", ``kind='bundled'``); this revision removes it
with its versions, runs, catalog rows and provenance, and narrows the kind
vocabulary to ``file``/``registry``/``git``.

The bundled content itself left the tree in the same change, so the downgrade
restores the previous check constraint but cannot restore the deleted rows.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BUNDLED = "SELECT id FROM seed_sources WHERE kind = 'bundled'"
_BUNDLED_VERSIONS = f"SELECT id FROM seed_source_versions WHERE source_id IN ({_BUNDLED})"


def _purge_bundled(bind: sa.Connection) -> None:
    """Delete the boot-created bundled provider and everything it owns."""
    statements = (
        f"DELETE FROM seed_import_run_items WHERE run_id IN ("
        f"SELECT id FROM seed_import_runs WHERE source_id IN ({_BUNDLED}))",
        f"DELETE FROM seed_import_runs WHERE source_id IN ({_BUNDLED})",
        f"DELETE FROM seed_sync_runs WHERE source_id IN ({_BUNDLED})",
        f"DELETE FROM seed_deferred_refs WHERE source_version_id IN ({_BUNDLED_VERSIONS})",
        f"DELETE FROM seed_item_provenance WHERE source_version_id IN ({_BUNDLED_VERSIONS})",
        f"DELETE FROM job_source_presets WHERE seed_source_version_id IN ({_BUNDLED_VERSIONS})",
        f"DELETE FROM provider_endpoints WHERE seed_source_version_id IN ({_BUNDLED_VERSIONS})",
        f"DELETE FROM provider_subscriptions WHERE seed_source_id IN ({_BUNDLED})",
        "UPDATE seed_sources SET current_version_id = NULL WHERE kind = 'bundled'",
        f"DELETE FROM seed_source_versions WHERE source_id IN ({_BUNDLED})",
        "DELETE FROM seed_sources WHERE kind = 'bundled'",
    )
    for statement in statements:
        bind.execute(sa.text(statement))


def upgrade() -> None:
    _purge_bundled(op.get_bind())
    with op.batch_alter_table("seed_sources") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint(
            "kind_allowed",
            "kind IN ('file', 'registry', 'git')",
        )


def downgrade() -> None:
    with op.batch_alter_table("seed_sources") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint(
            "kind_allowed",
            "kind IN ('bundled', 'file', 'registry', 'git')",
        )
