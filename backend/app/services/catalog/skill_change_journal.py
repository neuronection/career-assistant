"""The skill change journal seam (plan 148), mirroring the postings
journal's law: one write seam for every skill mutation, the row added in
the SAME transaction as the mutation — never a separate commit, never
best-effort-dropped. ``SkillChangeJournal.record`` computes the capped
field diff, gates on it (empty diff ⇒ no row, ``False``) and snapshots
the skill's key/label so events render after the skill row is gone.

Params-not-content law: ``actor_ref`` carries ids only (user/posting/job
refs); ``detail`` is the capped diff, a merge target or corroboration
counts — WHAT changed, not full content.
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.enums import SkillChangeActor, SkillEventKind
from app.models.taxonomy_model import Skill, SkillChange

#: Diff string cap — same bound as the postings journal: `from`/`to`
#: values longer than this are truncated with an ellipsis marker.
DIFF_STRING_CAP = 200
_TRUNCATION_MARKER = "…"

#: Tracked fields per writer (plan 148): the diffable identity + tree +
#: lifecycle set. ``level_anchors`` diffs by JSON equivalence, not identity.
TRACKED_FIELDS = (
    "label",
    "category",
    "description",
    "status",
    "parent_id",
    "aliases",
    "level_anchors",
)


def _norm(value: Any) -> Any:
    """JSON-safe comparable form (dates/uuids as strings, dicts sorted)."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return str(value)


def _cap(value: Any) -> Any:
    if isinstance(value, str) and len(value) > DIFF_STRING_CAP:
        return value[:DIFF_STRING_CAP] + _TRUNCATION_MARKER
    return value


def snapshot(skill: Skill, fields: tuple[str, ...] = TRACKED_FIELDS) -> dict:
    """Tracked-field snapshot of a skill (the keys ARE the tracked-field
    declaration — nothing else is diffed)."""
    return {field: _norm(getattr(skill, field, None)) for field in fields}


def compute_diff(before: dict | None, after: dict | None) -> dict:
    """Field → ``{from, to}`` over the snapshots' tracked keys."""
    before = before or {}
    after = after or {}
    diff: dict = {}
    for key in sorted(set(before) | set(after)):
        old_n, new_n = _norm(before.get(key)), _norm(after.get(key))
        if old_n != new_n:
            diff[key] = {"from": _cap(old_n), "to": _cap(new_n)}
    return diff


class SkillChangeJournal:
    """The single journal write seam — see the module docstring."""

    @classmethod
    def record(
        cls,
        db: AsyncSession | Session,
        skill: Skill,
        event: SkillEventKind | str,
        actor_kind: SkillChangeActor | str,
        actor_ref: dict | None = None,
        detail: dict | None = None,
        *,
        diff: dict | None = None,
    ) -> bool:
        """Journal one event in the caller's transaction.

        ``diff`` (a precomputed field diff) gates the write: empty ⇒ no
        row, ``False``. Events that carry their own payload (created/
        merged/deleted/auto_promoted) always write — pass
        ``diff=None`` for those.
        """
        if diff is not None and not diff:
            return False
        kind = actor_kind.value if isinstance(actor_kind, SkillChangeActor) else str(actor_kind)
        db.add(
            SkillChange(
                skill_id=skill.id,
                skill_key=skill.key,
                skill_label=skill.label,
                event=(event.value if isinstance(event, SkillEventKind) else str(event)),
                actor_kind=kind,
                actor_ref=actor_ref or None,
                detail=detail if detail is not None else diff,
            )
        )
        return True

    @classmethod
    def record_snapshot_change(
        cls,
        db: AsyncSession | Session,
        skill: Skill,
        before: dict,
        after: dict,
        event: SkillEventKind | str,
        actor_kind: SkillChangeActor | str,
        actor_ref: dict | None = None,
    ) -> bool:
        """Diff two snapshots and journal the change (the ``update_skill``
        path: empty diff ⇒ no row, ``False``)."""
        return cls.record(
            db,
            skill,
            event,
            actor_kind,
            actor_ref=actor_ref,
            diff=compute_diff(before, after),
        )
