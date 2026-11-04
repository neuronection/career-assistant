"""Plan 193 — fold bare profile link URLs into https.

``ProfileLink.url`` has required an ``http(s)`` scheme since the initial
release, but rows written before that (or hand-edited local profiles) carry
bare hosts. The profile read validates the stored JSON, so such a row 500s
every profile response. This data-only migration prefixes ``https://`` where
a scheme is missing; no table or column changes.

Downgrade is a documented no-op: nothing records that a scheme was absent, so
un-folding would be a guess. The folded value is valid either way.
"""

import json
import re

import sqlalchemy as sa

from alembic import op

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None

_SCHEME = re.compile(r"^https?://", re.IGNORECASE)


def fold_basics(basics: dict) -> bool:
    """Prefix bare link URLs in place; returns whether anything changed."""
    links = basics.get("links")
    if not isinstance(links, list):
        return False
    changed = False
    for link in links:
        if not isinstance(link, dict):
            continue
        url = str(link.get("url") or "").strip()
        if url and not _SCHEME.match(url):
            link["url"] = f"https://{url.lstrip('/')}"
            changed = True
    return changed


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    statement = (
        "UPDATE profiles SET basics = CAST(:basics AS jsonb) WHERE id = :id"
        if is_postgres
        else "UPDATE profiles SET basics = :basics WHERE id = :id"
    )
    for row in bind.execute(sa.text("SELECT id, basics FROM profiles")).fetchall():
        raw = row.basics
        basics = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        if not fold_basics(basics):
            continue
        bind.execute(
            sa.text(statement),
            {"basics": json.dumps(basics, ensure_ascii=False), "id": row.id},
        )


def downgrade() -> None:
    """No-op: the pre-fold shape is not recorded (see the module docstring)."""
