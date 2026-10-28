"""The posting change journal seam (plan 142 D3).

One write seam for every posting mutation: writers snapshot the tracked
fields before and after, ``PostingChangeJournal.record`` computes the
capped field diff, digest-gates it (empty diff ⇒ no row, ``False``) and
adds the row in the SAME transaction as the mutation — never a separate
commit, never best-effort-dropped. No SQLAlchemy event listeners: every
writer calls the seam explicitly (the codebase's seam style), and the
AST gate test pins that every mutator does.

Params-not-content law: ``actor_ref``/``operation`` carry ids and knobs
only (run/job/generation ids, model, trigger, thresholds); prompt and
response bodies live in ``ai_generations`` and ``job_postings.raw`` and
are never duplicated here. Diff values are capped — the journal shows
WHAT changed, not full content.
"""

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.enums import PostingChangeKind, PostingChangeOutcome
from app.models.posting_model import JobPosting, PostingChange

#: Diff string cap (plan 142 D5): `from`/`to` values longer than this are
#: truncated with an ellipsis marker — never full content.
DIFF_STRING_CAP = 200
_TRUNCATION_MARKER = "…"

#: Tracked-field sets per writer (D5) — the journal's reviewable core:
#: each writer passes exactly these through ``snapshot``; anything not
#: listed is mechanical bookkeeping (hashes, counters) the journal
#: deliberately ignores.
SYNC_FIELDS = (
    "title",
    "org",
    "location",
    "url",
    "posted_at",
    "expires_at",
    "seniority",
    "employment_type",
    "contract_type",
    "onsite_policy",
    "work_hours",
    "travel_class",
    "education_level",
    "salary_currency",
    "salary_min",
    "salary_max",
    "salary_period",
    "salary_basis",
    "status",
)
EXTRACT_FIELDS = (
    "extract_version",
    "needs_review",
    "seniority",
    "employment_type",
    "onsite_policy",
    "education_level",
    "salary_currency",
    "salary_min",
    "salary_max",
    "salary_period",
    "salary_basis",
    "location",
)
DETAIL_FIELDS = (
    "seniority",
    "employment_type",
    "contract_type",
    "onsite_policy",
    "location",
    "salary_currency",
    "salary_min",
    "salary_max",
    "salary_period",
    "salary_basis",
)
ORG_MATCH_FIELDS = ("org_id", "org_match_state")
RETAG_FIELDS = (
    "catalog_job_id",
    "mapping_method",
    "mapping_confidence",
    "status",
    "mapping_reason",
)
EXPIRY_FIELDS = ("status",)


def _norm(value: Any) -> Any:
    """JSON-safe comparable form (dicts sorted, dates/uuids as strings)."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return str(value)


def _cap(value: Any) -> Any:
    if isinstance(value, str) and len(value) > DIFF_STRING_CAP:
        return value[:DIFF_STRING_CAP] + _TRUNCATION_MARKER
    return value


def _skills_diff(before: list[dict], after: list[dict]) -> dict | None:
    """Set-diff over the posting_skills relation (plan 142 amendment 4):
    added/removed keys plus per-skill level/priority changes for the
    surviving keys. ``None`` when the relation did not change."""
    before_map = {entry["key"]: entry for entry in before}
    after_map = {entry["key"]: entry for entry in after}
    added = sorted(set(after_map) - set(before_map))
    removed = sorted(set(before_map) - set(after_map))
    changed: dict[str, dict] = {}
    for key in sorted(set(before_map) & set(after_map)):
        old, new = before_map[key], after_map[key]
        entry: dict = {}
        for field in ("level", "priority"):
            if _norm(old.get(field)) != _norm(new.get(field)):
                entry[field] = {
                    "from": _cap(_norm(old.get(field))),
                    "to": _cap(_norm(new.get(field))),
                }
        if entry:
            changed[key] = entry
    if not (added or removed or changed):
        return None
    diff: dict = {}
    if added:
        diff["added"] = added
    if removed:
        diff["removed"] = removed
    if changed:
        diff["changed"] = changed
    return diff


def compute_diff(before: dict | None, after: dict | None) -> dict:
    """Field → ``{from, to}`` over the snapshots' tracked keys, with the
    ``skills`` key rendered as the relation set-diff."""
    before = before or {}
    after = after or {}
    diff: dict = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if key == "skills":
            relation = _skills_diff(old or [], new or [])
            if relation is not None:
                diff["skills"] = relation
            continue
        old_n, new_n = _norm(old), _norm(new)
        if old_n != new_n:
            diff[key] = {"from": _cap(old_n), "to": _cap(new_n)}
    return diff


def snapshot(posting: JobPosting, fields: tuple[str, ...]) -> dict:
    """Tracked-field snapshot of a posting (the keys ARE the writer's
    tracked-field declaration — nothing else is diffed)."""
    return {field: _norm(getattr(posting, field, None)) for field in fields}


def raw_summary(posting: JobPosting) -> dict:
    """Compact stand-in for the raw JSONB: sizes, never content."""
    raw = posting.raw or {}
    description = str(raw.get("description") or "")
    return {
        "description_chars": len(description),
        "skills_raw_count": len(raw.get("_skills_raw") or []),
    }


def extract_summary(posting: JobPosting) -> dict:
    """Compact stand-in for the extract envelope: version, the cleaned
    description's head (the one content-bearing field users see), and
    list-field counts."""
    extract = posting.extract or {}
    return {
        "description_clean": _cap(_norm(str(extract.get("description_clean") or ""))),
        "skills_count": len(extract.get("skills") or []),
        "prerequisites_count": len(extract.get("prerequisites") or []),
        "suppressed_count": len(extract.get("_suppressed_fields") or []),
    }


def facts_summary(posting: JobPosting) -> dict:
    """Compact stand-in for the posting_facts JSONB: per-key sizes."""
    return {key: len(value) for key, value in sorted((posting.posting_facts or {}).items())}


async def skills_state(db: AsyncSession, posting_id) -> list[dict]:
    """The posting_skills relation as a diffable list of
    ``{key, level, priority}`` (keyed by the taxonomy's stable slug)."""
    from app.models.posting_model import PostingSkill
    from app.models.taxonomy_model import Skill

    rows = await db.execute(
        select(Skill.key, PostingSkill.required_level, PostingSkill.priority)
        .join(PostingSkill, PostingSkill.skill_id == Skill.id)
        .where(PostingSkill.posting_id == posting_id)
    )
    return [
        {"key": key, "level": level, "priority": priority} for key, level, priority in rows.all()
    ]


class PostingChangeJournal:
    """The single journal write seam — see the module docstring."""

    @classmethod
    def record(
        cls,
        db: AsyncSession | Session,
        posting_id,
        actor_kind: PostingChangeKind | str,
        actor_ref: dict | None = None,
        operation: dict | None = None,
        duration_ms: int | None = None,
        before: dict | None = None,
        after: dict | None = None,
        outcome: PostingChangeOutcome | str = PostingChangeOutcome.OK,
    ) -> bool:
        """Compute the diff from the before/after snapshots and journal
        it in the caller's transaction. Empty diff ⇒ no row, ``False``.

        ``actor_ref``/``operation`` must contain ids and knobs only —
        never prompt/response bodies (they live in ``ai_generations``).
        """
        kind = actor_kind.value if isinstance(actor_kind, PostingChangeKind) else str(actor_kind)
        diff = compute_diff(before, after)
        if not diff:
            return False
        pid = posting_id if isinstance(posting_id, uuid.UUID) else uuid.UUID(str(posting_id))
        db.add(
            PostingChange(
                posting_id=pid,
                actor_kind=kind,
                actor_ref=actor_ref or None,
                operation=operation or None,
                duration_ms=duration_ms,
                diff=diff,
                outcome=(
                    outcome.value if isinstance(outcome, PostingChangeOutcome) else str(outcome)
                ),
            )
        )
        return True
