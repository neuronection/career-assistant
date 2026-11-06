"""Full-entity snapshots for proposals (plan 99 AD7; plan 123.1)."""

from datetime import date, datetime
from typing import Any

from app.models.enums import ProposalKind

#: Columns excluded from full-entity snapshots (plan 99 AD7): identity,
#: ownership and stamps — the payload shapes carry everything else.
_SNAPSHOT_SKIP = {
    "id",
    "user_id",
    "org_id",
    "university_id",
    "department_id",
    "skill_id",
    "created_at",
    "updated_at",
}


def _snapshot_children(kind: str, entity: Any) -> dict:
    """Experience child rows with stable ids (same payload shape the
    read tool serves — skills also keep ``skill_label`` for rendering).
    """
    if kind != ProposalKind.EXPERIENCE_ITEM.value:
        return {}
    return {
        "skills": [
            {
                "id": str(link.id),
                "skill_key": link.skill.key if link.skill else str(link.skill_id),
                "skill_label": link.skill.label if link.skill else None,
                "role_in_item": link.role_in_item,
                "level_claim": link.level_claim,
                "last_used": (link.last_used.isoformat() if link.last_used else None),
            }
            for link in entity.skills or []
        ],
        "achievements": [
            {"id": str(row.id), "text": row.text, "metric": row.metric}
            for row in entity.achievements or []
        ],
    }


def _full_snapshot(kind: str, entity: Any) -> dict:
    """KIND_SPECS-shaped full entity dict incl. children (plan 99 AD7).

    Walks the table's own columns — raw stored values (dates iso'd),
    never diff-capped. Used for ``base_snapshot``/``after_snapshot`` and
    for delete payloads (recreate-with-children on revert).
    """
    snapshot: dict[str, Any] = {}
    for column in entity.__table__.columns:
        if column.name in _SNAPSHOT_SKIP:
            continue
        value = getattr(entity, column.key, None)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        snapshot[column.key] = value
    snapshot.update(_snapshot_children(kind, entity))
    return snapshot
