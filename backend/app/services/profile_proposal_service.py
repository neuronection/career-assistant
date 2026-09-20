"""HITL profile proposals (plan 77): create → diff → persist → idempotent resolve.

The chatbot proposes, the user resolves. Every apply dispatches to the
same service methods the REST forms use — this module owns only the
proposal lifecycle: payload validation (REST schemas, reused verbatim),
field-diff computation, conflict detection against ``base_updated_at``,
and idempotent resolve. Cards are first-class rows: they survive chat
session deletion and expire after ``PROPOSAL_TTL``.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, ValidationError as PydanticValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from app.models.enums import ProposalAction, ProposalKind, ProposalStatus
from app.models.experience_model import ExperienceItem, ExperienceSkill
from app.models.profile_entities_model import (
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.profile_proposal_model import ProfileProposal
from app.models.user_model import Profile, UserSkill
from app.schemas.cv import CvContextSelection
from app.schemas.experience import ExperienceItemIn, ExperienceItemUpdate
from app.schemas.profile import (
    AcademicsSection,
    BasicSection,
    ConstraintsSection,
    PreferencesSection,
    ProfileSectionUpdate,
    WorkPreferencesSection,
)
from app.schemas.profile_entities import (
    CertificationIn,
    CertificationPatch,
    EducationItemIn,
    EducationItemPatch,
    ProfileAchievementIn,
    ProfileAchievementPatch,
)
from app.schemas.profile_proposal import (
    CollectionEdit,
    CvSetBulletsOpPayload,
    CvSynthOpPayload,
    ProfileSectionPatchIn,
    TextEdit,
    UserSkillAddIn,
    UserSkillPatchIn,
)

PROPOSAL_TTL = timedelta(days=14)
# 2000, not 200 (plan 99): the diff must distinguish an anchored edit
# inside a long description — capped-at-200 before/after strings compare
# equal and the change row silently vanishes. TextDiffView folds
# unchanged lines, so the card stays readable.
DIFF_VALUE_CAP = 2000

#: Same-DB clock tolerance for the revert guard (plan 99 AD10): an
#: update bumped ``entity.updated_at`` at most this much after
#: ``resolved_at`` still counts as the apply itself, not a later edit.
#: Pinned by ``test_revert_guard_tolerance``.
_REVERT_TOLERANCE = timedelta(seconds=2)

#: Kinds whose update/delete ops require the target's full content to
#: have been read in the same turn (plan 99.1 read-before-edit gate).
#: ``user_skill`` rows are fully visible in the my_skills digest (a
#: scalar update has no silent-loss surface) and ``cv_synth`` is not an
#: entity edit — both are exempt, as are create ops (nothing to
#: overwrite). The grounding set carries ``read:{kind}:{id-or-section}``
#: keys for every entity whose full content the model has seen.
GROUNDED_KINDS = frozenset(
    {
        ProposalKind.EXPERIENCE_ITEM.value,
        ProposalKind.EDUCATION_ITEM.value,
        ProposalKind.CERTIFICATION.value,
        ProposalKind.PROFILE_ACHIEVEMENT.value,
    }
)
SECTION_NAMES = ("basics", "academics", "work_preferences", "constraints")

#: Per-kind prose fields an anchored ``text_edit`` may target (plan 99.2).
TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    ProposalKind.EXPERIENCE_ITEM.value: ("description",),
    ProposalKind.EDUCATION_ITEM.value: ("description",),
    ProposalKind.PROFILE_ACHIEVEMENT.value: ("detail",),
}


def read_key_for_op(op: dict, entity_id: Optional[uuid.UUID]) -> Optional[str]:
    """The grounding key an op must have been read under, or None when
    the op is exempt from the read-before-edit gate."""
    kind = str(op.get("kind") or "")
    action = str(op.get("action") or "")
    if action == ProposalAction.CREATE.value:
        return None
    if kind == ProposalKind.PROFILE_SECTION.value:
        section = str((op.get("payload") or {}).get("section") or "")
        return f"read:{kind}:{section}" if section in SECTION_NAMES else None
    if kind in GROUNDED_KINDS:
        return f"read:{kind}:{entity_id}" if entity_id is not None else None
    return None


async def resolve_cv_synth_payload(
    db: AsyncSession, user_id: uuid.UUID, payload: dict
) -> dict:
    """Plan 101 AD1 ref resolution: human labels for a cv_synth op.

    Resolves each ref once against its registered CV context source
    (ownership enforced by the source resolvers' ``user_id`` filter) and
    names the target posting by its public ``ref``. A ref whose source
    row is missing resolves to ``"Unknown item (<source_key>)"`` — never
    a raw UUID; the underlying op validation errors at apply time.
    """
    refs = [
        {
            "source_key": str(ref.get("source_key") or ""),
            "item_id": str(ref.get("item_id") or ""),
        }
        for ref in payload.get("refs") or []
        if ref.get("item_id")
    ]
    by_key: dict[str, set[str]] = {}
    for ref in refs:
        by_key.setdefault(ref["source_key"], set()).add(ref["item_id"])
    labels: dict[str, str] = {}
    if by_key:
        from app.services.cv_context_service import CV_CONTEXT_SOURCES

        for source_key, item_ids in by_key.items():
            definition = CV_CONTEXT_SOURCES.get(source_key)
            resolved: dict[str, str] = {}
            if definition is not None:
                try:
                    rows = await definition.resolver(db, user_id)
                except Exception as exc:  # noqa: BLE001 - a dead source degrades its row, never the card
                    logger.warning(
                        "cv_synth source resolution failed (%s): %s",
                        source_key,
                        str(exc)[:200],
                    )
                    rows = []
                resolved = {
                    str(row.item_id): str(row.label).strip()
                    for row in rows
                    if str(row.label or "").strip()
                }
            for item_id in sorted(item_ids):
                labels[f"{source_key}:{item_id}"] = resolved.get(item_id) or (
                    f"Unknown item ({source_key})"
                )
    resolved_refs = [
        {
            "label": labels[f"{ref['source_key']}:{ref['item_id']}"],
            "source_key": ref["source_key"],
            "item_id": ref["item_id"],
        }
        for ref in refs
    ]
    posting_label = ""
    posting_title = ""
    posting_id = payload.get("posting_id")
    if posting_id:
        from app.models.posting_model import JobPosting

        try:
            parsed = uuid.UUID(str(posting_id))
        except ValueError:
            parsed = None
        posting = None
        if parsed is not None:
            rows = await db.execute(select(JobPosting).where(JobPosting.id == parsed))
            posting = rows.scalars().first()
        if posting is not None:
            posting_label = str(posting.ref)
            posting_title = str(posting.title)
        else:
            posting_label = "Unknown posting"
    return {
        "resolved_refs": resolved_refs,
        "resolved_posting": posting_label,
        "resolved_posting_title": posting_title,
    }


async def resolve_cv_set_bullets(
    db: AsyncSession, user_id: uuid.UUID, payload: dict
) -> dict:
    """Plan 107: ground a cv_set_bullets op in server truth.

    Loads the owned CV, resolves the target row through the context
    engine (the same rows the renderer draws) and captures the CURRENT
    bullet list — the override when one exists, the profile-snapshot
    list otherwise — so the card renders an informed before/after and
    revert can restore exactly what was there.
    """
    from app.services.cv_builder_service import CvBuilderService
    from app.services.cv_service import CvService

    cv = await CvService(db).get_owned(payload["cv_id"], user_id)
    source_key = payload["source_key"]
    item_id = payload["item_id"]
    resolution = await CvBuilderService(db).resolution(cv)
    rows = resolution.snapshot.get(source_key)
    row: dict | None = None
    if isinstance(rows, list):
        for candidate in rows:
            if isinstance(candidate, dict) and str(candidate.get("id")) == str(item_id):
                row = candidate
                break
    if row is None:
        raise ValidationError(
            "Target item is not on this CV's context — include it first"
        )
    selection = CvContextSelection.model_validate(cv.context or {})
    pinned_id = (selection.synth_pins or {}).get(f"{source_key}:{item_id}:bullets")
    variant_entries: list[dict] | None = None
    if pinned_id:
        from app.services.cv_synth_service import CvSynthService

        variant = await CvSynthService(db).get_owned(uuid.UUID(str(pinned_id)), user_id)
        entries = (variant.payload or {}).get("achievements") or []
        variant_entries = [
            {"text": str(entry.get("text") or "")}
            for entry in entries
            if isinstance(entry, dict)
        ]
    base = [
        {"text": str(entry.get("text") or "")}
        for entry in row.get("achievements") or []
        if isinstance(entry, dict)
    ]
    return {
        "cv_title": cv.title,
        "item_label": str(row.get("title") or row.get("program") or item_id),
        "before": variant_entries if variant_entries is not None else base,
        "prior": variant_entries,
        "prior_variant_id": pinned_id,
        "cv_updated_at": cv.updated_at,
    }


def cv_synth_narration_refs(op: dict, resolved: dict | None) -> list[str]:
    """Prepared_ops rows for a cv_synth op (plan 101 AD5): resolved ref
    labels ("Sample Internship (projects)"), never raw ids."""
    rows = (resolved or {}).get("resolved_refs") or []
    labels = []
    for row in rows:
        label = str(row.get("label") or "")
        source_key = str(row.get("source_key") or "")
        labels.append(
            label
            if label == f"Unknown item ({source_key})"
            else f"{label} ({source_key})"
        )
    if labels:
        return labels
    return [
        f"{ref.get('source_key')}:{ref.get('item_id')}"
        for ref in (op.get("payload") or {}).get("refs") or []
    ]


logger = logging.getLogger(__name__)
ACTION_VERBS = {
    ProposalAction.CREATE.value: "Add",
    ProposalAction.UPDATE.value: "Update",
    ProposalAction.DELETE.value: "Delete",
}

_SECTION_MODELS: dict[str, type[BaseModel]] = {
    "basics": BasicSection,
    "academics": AcademicsSection,
    "work_preferences": WorkPreferencesSection,
    "preferences": PreferencesSection,
    "constraints": ConstraintsSection,
}


@dataclass(frozen=True)
class KindSpec:
    """Registry entry: payload schemas + diff field vocabulary per kind."""

    label: str
    model: Optional[type]
    create_model: Optional[type[BaseModel]]
    update_model: Optional[type[BaseModel]]
    fields: tuple[tuple[str, str], ...]


KIND_SPECS: dict[str, KindSpec] = {
    ProposalKind.EXPERIENCE_ITEM.value: KindSpec(
        label="experience",
        model=ExperienceItem,
        create_model=ExperienceItemIn,
        update_model=ExperienceItemUpdate,
        fields=(
            ("title", "Title"),
            ("kind", "Type"),
            ("org_name", "Organization"),
            ("start", "Start date"),
            ("end", "End date"),
            ("open_ended", "Open-ended"),
            ("hours_per_week", "Hours per week"),
            ("onsite_policy", "On-site policy"),
            ("status", "Status"),
            ("description", "Description"),
        ),
    ),
    ProposalKind.EDUCATION_ITEM.value: KindSpec(
        label="education",
        model=EducationItem,
        create_model=EducationItemIn,
        update_model=EducationItemPatch,
        fields=(
            ("institution", "Institution"),
            ("program", "Program"),
            ("level", "Level"),
            ("start", "Start date"),
            ("end", "End date"),
            ("in_progress", "In progress"),
            ("description", "Description"),
            ("status", "Status"),
        ),
    ),
    ProposalKind.CERTIFICATION.value: KindSpec(
        label="certification",
        model=Certification,
        create_model=CertificationIn,
        update_model=CertificationPatch,
        fields=(
            ("name", "Name"),
            ("issuer", "Issuer"),
            ("issued", "Issued"),
            ("expires", "Expires"),
            ("credential_id", "Credential ID"),
            ("link", "Link"),
            ("status", "Status"),
        ),
    ),
    ProposalKind.PROFILE_ACHIEVEMENT.value: KindSpec(
        label="achievement",
        model=ProfileAchievement,
        create_model=ProfileAchievementIn,
        update_model=ProfileAchievementPatch,
        fields=(
            ("kind", "Type"),
            ("title", "Title"),
            ("issuer", "Issuer"),
            ("date", "Date"),
            ("detail", "Detail"),
            ("link", "Link"),
        ),
    ),
    ProposalKind.USER_SKILL.value: KindSpec(
        label="skill",
        model=UserSkill,
        create_model=UserSkillAddIn,
        update_model=UserSkillPatchIn,
        fields=(
            ("level", "Level (1–10)"),
            ("derive_enabled", "Derivation enabled"),
        ),
    ),
    ProposalKind.PROFILE_SECTION.value: KindSpec(
        label="profile section",
        model=Profile,
        create_model=None,
        update_model=ProfileSectionPatchIn,
        fields=(),
    ),
    ProposalKind.CV_SYNTH.value: KindSpec(
        label="CV variants",
        model=None,
        create_model=None,
        update_model=None,
        fields=(),
    ),
    ProposalKind.CV_SET_BULLETS.value: KindSpec(
        label="CV bullets",
        model=None,
        create_model=None,
        update_model=None,
        fields=(),
    ),
}


def _jsonish(value: Any) -> Any:
    """Diff-safe scalar rendering: primitives stay native, the rest
    becomes a compact JSON string capped at ``DIFF_VALUE_CAP``."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) > DIFF_VALUE_CAP:
        return text[: DIFF_VALUE_CAP - 1] + "…"
    return text


def _instance_jsonish(value: Any) -> Any:
    """One ORM child row as the payload shape the after-side uses —
    `getattr(entity, "skills")` returns ``ExperienceSkill`` rows whose
    ``json.dumps(default=str)`` repr is the ugly `<module … object>`
    diff the user once saw."""
    if isinstance(value, ExperienceSkill):
        return {
            "id": str(value.id),
            "skill_key": value.skill.key if value.skill is not None else None,
            "skill_label": value.skill.label if value.skill is not None else None,
            "role_in_item": value.role_in_item,
            "level_claim": value.level_claim,
            "last_used": value.last_used.isoformat() if value.last_used else None,
        }
    if hasattr(value, "text"):
        return {
            "id": str(value.id),
            "text": value.text,
            "metric": getattr(value, "metric", None),
        }
    return value


def _structured_entries(field: str, entries: Any) -> list[dict]:
    """Collection rows as structured chip data (plan 99 AD6): skills keep
    key + label + role/level, achievements keep text + metric, links keep
    url — used per-row when the pipeline produced dict entries."""
    out: list[dict] = []
    for entry in entries or []:
        row = entry if isinstance(entry, dict) else _instance_jsonish(entry)
        if not isinstance(row, dict):
            continue
        if field == "skills":
            key = row.get("skill_key")
            out.append(
                {
                    "id": row.get("id"),
                    "skill_key": key,
                    "skill_label": row.get("skill_label") or key,
                    "role_in_item": row.get("role_in_item"),
                    "level_claim": row.get("level_claim"),
                    "last_used": row.get("last_used"),
                }
            )
        elif field == "achievements":
            out.append(
                {
                    "id": row.get("id"),
                    "text": row.get("text"),
                    "metric": row.get("metric"),
                }
            )
        else:
            out.append(row)
    return out


def _before_value(value: Any) -> Any:
    """``before`` rendering for update diffs: relationship collections of
    ORM rows become payload-shaped dicts instead of the debug
    ``<module.Object at 0x…>`` strings."""
    if isinstance(value, list):
        return [_instance_jsonish(entry) for entry in value]
    return value


# Collection fields render as scalar lists (skill keys, achievement
# texts, link urls) — chips in the card UI, and shape-equal comparisons
# drop unchanged collections from update diffs.
_LIST_FIELDS = {"skills", "achievements", "links"}
_LIST_FIELD_KEYS = {"skills": "skill_key", "achievements": "text", "links": "url"}


def _scalar_list(value: Any) -> list[str]:
    entries: list[str] = []
    for entry in value or []:
        if isinstance(entry, dict):
            entry = next(
                (
                    entry[key]
                    for key in ("skill_key", "text", "url", "name")
                    if isinstance(entry.get(key), str)
                ),
                "",
            )
        text = str(entry).strip()
        if text:
            entries.append(text)
    return entries[:15]


def _payload_value(field: str, value: Any) -> Any:
    if field in _LIST_FIELDS and isinstance(value, list):
        return _scalar_list(value)
    return value


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


def _truncate(text: str, cap: int = 60) -> str:
    text = (text or "").strip()
    if len(text) <= cap:
        return text
    return text[: cap - 1] + "…"


def _edit_summary_rows(edit_ops: Optional[dict]) -> list[dict]:
    """One legible row per edit entry, in order (plan 99 AD6): the card
    shows each change ("replaces '…'", "adds skill: docker (secondary)")
    without unfolding the full before/after."""
    if not edit_ops:
        return []
    rows: list[dict] = []

    def row(text: str) -> None:
        rows.append({"field": "edit", "label": "Change", "before": None, "after": text})

    for edit in edit_ops.get("text_edits") or []:
        field = edit.get("field") or ""
        text = _truncate(str(edit.get("text") or ""))
        op = edit.get("op")
        if op == "replace":
            row(f"replaces '{_truncate(str(edit.get('find') or ''))}' in {field}")
        elif op == "append":
            row(f"appends to {field}: '{text}'")
        else:
            row(f"prepends to {field}: '{text}'")
    for edit in edit_ops.get("collection_edits") or []:
        collection = edit.get("collection") or ""
        match = edit.get("match") or {}
        if edit.get("op") == "remove":
            if collection == "skills":
                row(f"removes skill: {match.get('skill_key') or match.get('id')}")
            elif collection == "achievements":
                row(f"removes achievement: '{_truncate(str(match.get('text') or ''))}'")
            else:
                row(f"removes link: {match.get('url')}")
        else:
            value = edit.get("value") or {}
            if not isinstance(value, dict):
                value = (
                    _as_skill_entry(value)
                    if collection == "skills"
                    else _as_achievement_entry(value)
                    if collection == "achievements"
                    else _as_link_entry(value)
                )
            if collection == "skills":
                suffix = ""
                if value.get("role_in_item") and value["role_in_item"] != "primary":
                    suffix = f" ({value['role_in_item']})"
                row(f"adds skill: {value.get('skill_key')}{suffix}")
            elif collection == "achievements":
                row(f"adds achievement: '{_truncate(str(value.get('text') or ''))}'")
            else:
                row(f"adds link: {value.get('url')}")
    return rows


def proposal_title(proposal: ProfileProposal) -> str:
    """Card title: "Update experience · Siemens internship"."""
    spec = KIND_SPECS.get(proposal.kind)
    noun = spec.label if spec is not None else proposal.kind
    verb = ACTION_VERBS.get(proposal.action, proposal.action.title())
    return f"{verb} {noun}" + (
        f" · {proposal.entity_label}" if proposal.entity_label else ""
    )


def proposal_event(proposal: ProfileProposal) -> dict:
    """SSE/metadata card payload — the one serialization shared by the
    chat stream and the list endpoint (never drift between the two)."""
    return {
        "id": str(proposal.id),
        "kind": proposal.kind,
        "action": proposal.action,
        "status": proposal.status,
        "title": proposal_title(proposal),
        "entity_id": str(proposal.entity_id) if proposal.entity_id else None,
        "entity_label": proposal.entity_label,
        "diff": proposal.diff_json or [],
        "destructive": proposal.action == ProposalAction.DELETE.value,
        "source": proposal.source,
        "chat_session_id": (
            str(proposal.chat_session_id) if proposal.chat_session_id else None
        ),
        "created_at": proposal.created_at.isoformat(),
    }


def _ts(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _as_skill_entry(raw: Any) -> dict:
    """Model-emitted skill labels (`"electron"`, `{"name": "…"}`) become
    `{skill_key}` — the apply path finds or proposes free-text keys."""
    if isinstance(raw, str):
        return {"skill_key": raw}
    if isinstance(raw, dict) and not raw.get("skill_key"):
        label = raw.get("key") or raw.get("name") or raw.get("label")
        if isinstance(label, str):
            entry = dict(raw)
            entry["skill_key"] = label
            return entry
    return raw


def _as_achievement_entry(raw: Any) -> dict:
    """Model-emitted achievement strings become `{"text": …}`."""
    if isinstance(raw, str):
        return {"text": raw}
    if isinstance(raw, dict) and not raw.get("text"):
        text = raw.get("description") or raw.get("title")
        if isinstance(text, str):
            entry = dict(raw)
            entry["text"] = text
            return entry
    return raw


def _as_link_entry(raw: Any) -> dict:
    """Model-emitted bare URLs become `{"url": …}` link objects."""
    if isinstance(raw, str):
        return {"url": raw}
    return raw


def _resolve_text_edits(
    kind: str,
    entity: Any,
    payload: dict,
    text_edits: list[dict],
) -> dict:
    """Resolve anchored text edits into plain field values (plan 99.2).

    Edits apply IN ORDER, each anchored against the result of the
    previous — a later anchor may legitimately quote earlier output.
    Every anchor is validated against the current content, so a silent
    overwrite is structurally impossible: ``replace`` must match
    exactly once, ``append``/``prepend`` only add.
    """
    allowed = TEXT_FIELDS.get(kind, ())
    working: dict[str, str] = {}
    for raw in text_edits:
        edit = TextEdit.model_validate(raw)
        if edit.field not in allowed:
            raise ValidationError(
                f"anchor_mismatch: {kind} has no editable text field "
                f"{edit.field!r} (editable: {', '.join(allowed) or 'none'})"
            )
        if edit.field in payload:
            raise ValidationError(
                f"conflicting_edit: {edit.field} is set in both payload "
                "and text_edits — one way to express a change"
            )
        if edit.field not in working:
            working[edit.field] = getattr(entity, edit.field, None) or ""
        current = working[edit.field]
        if edit.op == "replace":
            find = edit.find or ""
            count = current.count(find)
            if count == 0:
                raise ValidationError(
                    f"anchor_mismatch: the quoted text does not appear in "
                    f"{edit.field} — quote it verbatim from the read result"
                )
            if count > 1:
                raise ValidationError(
                    f"anchor_ambiguous: the quoted text appears {count}x in "
                    f"{edit.field} — include more surrounding context"
                )
            working[edit.field] = current.replace(find, edit.text, 1)
        elif edit.op == "append":
            working[edit.field] = f"{current}\n{edit.text}" if current else edit.text
        else:
            working[edit.field] = f"{edit.text}\n{current}" if current else edit.text
    payload.update(working)
    return payload


def _resolve_collection_edits(
    entity: Any,
    payload: dict,
    collection_edits: list[dict],
) -> dict:
    """Resolve granular collection edits into full child lists (plan 99.2).

    Adds append to the current children (duplicate skill keys / link
    urls are conflicting edits); removes match by stable child id first
    ({skill_key} for skills, exact text for achievements, exact url for
    links as fallback) — an unknown anchor is an anchor mismatch, never
    a partial rewrite. Row ids ride a temporary ``_row_id`` key for
    matching and are stripped from the resolved lists.
    """
    skills: list[dict] = [
        {
            "_row_id": str(link.id),
            "skill_key": link.skill.key if link.skill else str(link.skill_id),
            "role_in_item": link.role_in_item,
            "level_claim": link.level_claim,
        }
        for link in entity.skills or []
    ]
    achievements: list[dict] = [
        {"_row_id": str(row.id), "text": row.text, "metric": row.metric}
        for row in entity.achievements or []
    ]
    links: list[dict] = [
        dict(_as_link_entry(link)) for link in entity.links or [] if link
    ]

    touched: set[str] = set()

    def _drop(rows: list[dict], index: int, what: str) -> None:
        if index < 0:
            raise ValidationError(
                f"anchor_mismatch: no such {what} on this item — match by "
                "child id (from the read result) or exact content"
            )
        rows.pop(index)

    for raw in collection_edits:
        edit = CollectionEdit.model_validate(raw)
        touched.add(edit.collection)
        if edit.op == "add":
            value = edit.value or {}
            if edit.collection == "skills":
                entry = _as_skill_entry(value)
                key = entry.get("skill_key")
                if not key:
                    raise ValidationError(
                        "anchor_mismatch: skill add needs a skill_key from "
                        "the my_skills digest or the item's skills"
                    )
                if any(row.get("skill_key") == key for row in skills):
                    raise ValidationError(
                        f"conflicting_edit: skill {key!r} is already linked "
                        "to this item"
                    )
                skills.append(
                    {
                        "skill_key": key,
                        "role_in_item": entry.get("role_in_item", "primary"),
                        "level_claim": entry.get("level_claim"),
                    }
                )
            elif edit.collection == "achievements":
                entry = _as_achievement_entry(value)
                if not entry.get("text"):
                    raise ValidationError("anchor_mismatch: achievement add needs text")
                achievements.append(
                    {"text": entry["text"], "metric": entry.get("metric")}
                )
            else:
                entry = _as_link_entry(value)
                url = entry.get("url")
                if not url:
                    raise ValidationError("anchor_mismatch: link add needs a url")
                if any(row.get("url") == url for row in links):
                    raise ValidationError(
                        f"conflicting_edit: link {url!r} already exists"
                    )
                links.append(entry)
        else:
            match = edit.match or {}
            if edit.collection == "skills":
                index = next(
                    (
                        i
                        for i, row in enumerate(skills)
                        if row.get("_row_id") == match.get("id")
                        or row.get("skill_key") == match.get("skill_key")
                    ),
                    -1,
                )
                _drop(skills, index, "skill")
            elif edit.collection == "achievements":
                index = next(
                    (
                        i
                        for i, row in enumerate(achievements)
                        if row.get("_row_id") == match.get("id")
                        or row.get("text") == match.get("text")
                    ),
                    -1,
                )
                _drop(achievements, index, "achievement")
            else:
                index = next(
                    (
                        i
                        for i, row in enumerate(links)
                        if row.get("url") == match.get("url")
                    ),
                    -1,
                )
                _drop(links, index, "link")

    resolved: dict = {}
    if "skills" in touched:
        resolved["skills"] = [
            {k: v for k, v in row.items() if k != "_row_id"} for row in skills
        ]
    if "achievements" in touched:
        resolved["achievements"] = [
            {k: v for k, v in row.items() if k != "_row_id"} for row in achievements
        ]
    if "links" in touched:
        resolved["links"] = links
    for field in resolved:
        if field in payload:
            raise ValidationError(
                f"conflicting_edit: {field} is set in both payload and "
                "collection_edits — full-replacement update semantics are "
                "retired; use collection_edits"
            )
    return resolved


def _resolve_edit_ops(
    kind: str,
    entity: Any,
    payload: dict,
    text_edits: list[dict],
    collection_edits: list[dict],
) -> tuple[dict, dict]:
    """Apply both edit families to one op's payload; return the resolved
    payload plus the raw instructions for ``_edit_ops`` (audit + card
    copy + preview highlighting)."""
    edit_ops: dict = {}
    if text_edits:
        if kind not in TEXT_FIELDS:
            raise ValidationError(
                f"text_edits apply to {sorted(TEXT_FIELDS)} — not {kind!r}"
            )
        payload = _resolve_text_edits(kind, entity, payload, text_edits)
        edit_ops["text_edits"] = [
            TextEdit.model_validate(raw).model_dump(mode="json") for raw in text_edits
        ]
    if collection_edits:
        if kind != ProposalKind.EXPERIENCE_ITEM.value:
            raise ValidationError("collection_edits apply to experience_item only")
        payload.update(_resolve_collection_edits(entity, payload, collection_edits))
        edit_ops["collection_edits"] = [
            CollectionEdit.model_validate(raw).model_dump(mode="json")
            for raw in collection_edits
        ]
    return payload, edit_ops


def _normalize_experience_payload(payload: dict, *, action: str) -> dict:
    """Trust-boundary normalization for chat-sourced experience ops.

    Real providers routinely emit looser shapes than the REST schema
    accepts: label-string skills (`["electron", …]` vs
    `{skill_key, …}` rows), prose-string achievements and bare-URL
    links. Normalizing here keeps them reviewable as cards instead of
    dropping every suggestion; genuine field errors still drop with
    their reason. Projects without dates default to open-ended (the
    model cannot know the schema's period rule).
    """
    payload = dict(payload)
    if (
        action == ProposalAction.CREATE.value
        and not (payload.get("end"))
        and not payload.get("open_ended")
    ):
        payload["open_ended"] = True
    if isinstance(payload.get("skills"), list):
        payload["skills"] = [_as_skill_entry(s) for s in payload["skills"]]
    if isinstance(payload.get("achievements"), list):
        payload["achievements"] = [
            _as_achievement_entry(a) for a in payload["achievements"]
        ]
    if isinstance(payload.get("links"), list):
        payload["links"] = [_as_link_entry(link) for link in payload["links"]]
    return payload


async def notify_proposals(db, user_id, proposals, session_id) -> None:
    """ADR-0015 fanout: proposal cards outlive the chat window.

    Best-effort — a notification failure never breaks the chat turn.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        from app.services.notification_service import NotificationService

        titles = [p.entity_label or p.kind for p in proposals[:3]]
        summary = ", ".join(titles)
        if len(proposals) > 3:
            summary = f"{summary} +{len(proposals) - 3} more"
        plural = "s" if len(proposals) > 1 else ""
        await NotificationService(db).emit(
            "profile_proposal",
            [user_id],
            title=f"Profile edit proposal{plural} waiting for review",
            body=summary,
            payload={
                "link": "/profile",
                "proposal_ids": [str(p.id) for p in proposals],
                "chat_session_id": str(session_id),
            },
            source_ref={"chat_session_id": str(session_id)},
            dedup_key=f"profile-proposal:{proposals[0].id}",
        )
    except Exception:  # noqa: BLE001 — never break the turn
        logger.warning("profile-proposal notification failed", exc_info=True)


def drop_code(reason: str) -> str:
    """Stable drop-reason token (``unread_target`` …) from a drop message
    — the telemetry bucket for ``profile_op_outcomes``."""
    return str(reason).split(":", 1)[0].strip()[:40]


async def resolve_ops(
    db: AsyncSession,
    user_id: uuid.UUID,
    ops: list[dict],
    grounding: set[str],
) -> tuple[list[dict], list[dict]]:
    """Shared op validation (plan 99.3): gate + duplicate-target +
    normalization + anchored-edit resolution — WITHOUT persisting.

    One implementation serves both the draft pipeline and
    ``create_from_ops``. Returns ``(resolved_ops, failures)``; resolved
    ops are PLAIN create kwargs — anchored instructions are resolved
    into the payload (with ``_edit_ops`` attached) and the instruction
    lists are emptied, so a downstream re-validation can never apply
    them twice.
    """
    service = ProfileProposalService(db)
    resolved_ops: list[dict] = []
    failures: list[dict] = []
    seen_targets: set[tuple[str, str]] = set()
    for op in ops:
        try:
            action = str(op.get("action") or "")
            entity_id = op.get("entity_id")
            if isinstance(entity_id, str) and entity_id:
                entity_id = uuid.UUID(entity_id)
            kind = str(op.get("kind") or "")
            target_key: Optional[tuple[str, str]] = None
            if entity_id is not None:
                target_key = (kind, str(entity_id))
            elif kind == ProposalKind.PROFILE_SECTION.value:
                section = str((op.get("payload") or {}).get("section") or "")
                if section:
                    target_key = (kind, section)
            if target_key is not None and target_key in seen_targets:
                raise ValidationError(
                    f"duplicate_target: a second op edits the same "
                    f"{kind} — put all its changes (text_edits / "
                    "collection_edits) into ONE op"
                )
            read_key = read_key_for_op(op, entity_id)
            if read_key is not None and read_key not in grounding:
                raise ValidationError(
                    f"unread_target: the full content of {op.get('kind')} "
                    "was not read this turn — read it before proposing "
                    "changes"
                )
            payload = op.get("payload") or {}
            if op.get("kind", "") == ProposalKind.EXPERIENCE_ITEM.value:
                payload = _normalize_experience_payload(
                    payload,
                    action=op.get("action", ""),
                )
            if (
                op.get("kind", "") == ProposalKind.EXPERIENCE_ITEM.value
                and op.get("action") == ProposalAction.UPDATE.value
                and op.get("edit_ops") is None
                and any(
                    field in payload for field in ("skills", "achievements", "links")
                )
            ):
                raise ValidationError(
                    "conflicting_edit: full-replacement of skills, "
                    "achievements or links in an update payload is "
                    "retired — use collection_edits"
                )
            text_edits = list(op.get("text_edits") or [])
            collection_edits = list(op.get("collection_edits") or [])
            edit_ops: Optional[dict] = op.get("edit_ops")
            if text_edits or collection_edits:
                if op.get("action") != ProposalAction.UPDATE.value:
                    raise ValidationError(
                        "text_edits/collection_edits apply to update ops "
                        "only — creates carry full values in the payload"
                    )
                entity, _ = await service._load_entity(kind, user_id, entity_id)
                payload, edit_ops = _resolve_edit_ops(
                    kind, entity, dict(payload), text_edits, collection_edits
                )
            elif edit_ops is not None:
                edit_ops = op.get("edit_ops")
            spec = KIND_SPECS.get(kind)
            if spec is None:
                raise ValidationError(f"Unknown proposal kind: {kind}")
            # Dry-run the REST schema: a resolve-level pass means the
            # create() call below cannot fail on validation — a dropped
            # sibling op must not poison this target (seen_targets is
            # marked when the resolved op survives).
            if kind == ProposalKind.PROFILE_SECTION.value:
                patch = ProfileSectionPatchIn.model_validate(payload)
                _SECTION_MODELS[patch.section].model_validate(patch.value)
            elif kind == ProposalKind.CV_SYNTH.value:
                CvSynthOpPayload.model_validate(payload)
            elif kind == ProposalKind.CV_SET_BULLETS.value:
                CvSetBulletsOpPayload.model_validate(payload)
            elif action == ProposalAction.CREATE.value:
                assert spec.create_model is not None
                spec.create_model.model_validate(payload)
            else:
                assert spec.update_model is not None
                spec.update_model.model_validate(payload)
            if target_key is not None:
                seen_targets.add(target_key)
            resolved_ops.append(
                {
                    "kind": op.get("kind", ""),
                    "action": op.get("action", ""),
                    "payload": payload,
                    "entity_id": str(entity_id) if entity_id else None,
                    "edit_ops": edit_ops,
                }
            )
        except (
            DomainError,
            PydanticValidationError,
            ValueError,
            KeyError,
        ) as exc:
            logger.warning(
                "Profile op dropped (kind=%r action=%r): %s",
                op.get("kind"),
                op.get("action"),
                str(exc)[:500],
            )
            failures.append({"op": op, "reason": str(exc)})
    return resolved_ops, failures


class ProfileProposalService:
    """Proposal lifecycle; apply always dispatches to the form services."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------ create

    async def create(
        self,
        user_id: uuid.UUID,
        *,
        kind: str,
        action: str,
        payload: dict,
        entity_id: Optional[uuid.UUID] = None,
        source: str = "chat",
        edit_ops: Optional[dict] = None,
        chat_session_id: Optional[uuid.UUID] = None,
        chat_message_id: Optional[uuid.UUID] = None,
        ai_generation_id: Optional[uuid.UUID] = None,
    ) -> ProfileProposal:
        """Validate one op against its REST schema and persist the card.

        ``edit_ops`` (plan 99.2) carries the raw anchored-edit
        instructions; they merge into ``payload_json`` after schema
        validation (the REST schema stays clean) for audit, card copy
        and preview highlighting.
        """
        spec = KIND_SPECS.get(kind)
        if spec is None:
            raise ValidationError(f"Unknown proposal kind: {kind}")
        if action not in ACTION_VERBS:
            raise ValidationError(f"Unknown proposal action: {action}")
        if kind == ProposalKind.PROFILE_SECTION.value:
            if action != ProposalAction.UPDATE.value:
                raise ValidationError("Profile sections support update only")
        elif kind == ProposalKind.CV_SYNTH.value:
            if action != ProposalAction.CREATE.value:
                raise ValidationError("CV variant ops support create only")
            if entity_id is not None:
                raise ValidationError("cv_synth ops carry no entity_id")
        elif kind == ProposalKind.CV_SET_BULLETS.value:
            if action != ProposalAction.UPDATE.value:
                raise ValidationError("CV bullet ops support update only")
            if entity_id is not None:
                raise ValidationError("cv_set_bullets ops carry no entity_id")
        elif action == ProposalAction.CREATE.value:
            if entity_id is not None:
                raise ValidationError("create ops carry no entity_id")
        else:
            if entity_id is None:
                raise ValidationError(f"{action} ops require entity_id")
            if action == ProposalAction.DELETE.value:
                payload = {}

        entity: Any = None
        label = ""
        base_updated_at: Optional[datetime] = None
        diff: list[dict] = []
        # Plan 99 AD7: KIND_SPECS-shaped before/after snapshots for the
        # grounded entity kinds — the preview endpoint reads them lazily
        # and revert inverse-applies them. Never diff-capped.
        base_snapshot: Optional[dict] = None
        after_snapshot: Optional[dict] = None

        if kind == ProposalKind.PROFILE_SECTION.value:
            patch = ProfileSectionPatchIn.model_validate(payload)
            section_model = _SECTION_MODELS[patch.section]
            section_model.model_validate(patch.value)
            stored_payload = {
                "section": patch.section,
                "value": patch.value,
            }
            profile = await self._load_profile(user_id)
            base_updated_at = profile.updated_at
            label = patch.section.replace("_", " ")
            diff = self._section_diff(profile, patch.section, patch.value)
        elif kind == ProposalKind.CV_SYNTH.value:
            op_payload = CvSynthOpPayload.model_validate(payload)
            stored_payload = op_payload.model_dump(mode="json")
            # Plan 101 AD1: resolve every ref to a human label ONCE at
            # card creation; the labels live in payload_json (audit +
            # preview reuse) and drive both the title and the diff rows.
            stored_payload.update(
                await resolve_cv_synth_payload(self.db, user_id, stored_payload)
            )
            label = self._cv_synth_label(stored_payload)
            diff = self._cv_synth_diff(stored_payload)
        elif kind == ProposalKind.CV_SET_BULLETS.value:
            op_payload = CvSetBulletsOpPayload.model_validate(payload)
            stored_payload = op_payload.model_dump(mode="json")
            # Plan 107: ground in server truth ONCE at card creation —
            # the card shows the CURRENT bullets (override ?? snapshot)
            # against the proposal, and revert restores `prior`.
            resolved = await resolve_cv_set_bullets(self.db, user_id, stored_payload)
            base_updated_at = resolved["cv_updated_at"]
            entity_id = op_payload.cv_id
            stored_payload.update(
                {
                    "cv_title": resolved["cv_title"],
                    "item_label": resolved["item_label"],
                    "before": resolved["before"],
                    "prior": resolved["prior"],
                    "cv_updated_at": resolved["cv_updated_at"].isoformat(),
                }
            )
            label = self._cv_bullets_label(stored_payload)
            diff = self._cv_bullets_diff(stored_payload)
        elif action == ProposalAction.CREATE.value:
            model = spec.create_model
            assert model is not None
            validated = model.model_validate(payload)
            stored_payload = validated.model_dump(mode="json")
            label = self._create_label(kind, stored_payload)
            diff = self._create_diff(spec, stored_payload)
            after_snapshot = dict(stored_payload)
        else:
            entity, base_updated_at = await self._load_entity(kind, user_id, entity_id)
            label = self._entity_label(kind, entity)
            if action == ProposalAction.DELETE.value:
                stored_payload = {"snapshot": _full_snapshot(kind, entity)}
                after_snapshot = None
                diff = [
                    {
                        "field": field,
                        "label": field_label,
                        "before": _jsonish(value),
                        "after": None,
                    }
                    for field, field_label in spec.fields
                    if (value := getattr(entity, field, None)) not in (None, "", [])
                ]
            else:
                model = spec.update_model
                assert model is not None
                validated = model.model_validate(payload)
                stored_payload = validated.model_dump(mode="json", exclude_unset=True)
                if not stored_payload:
                    raise ValidationError("update payload sets no fields")
                diff = self._update_diff(spec, entity, stored_payload)
                base_snapshot = _full_snapshot(kind, entity)
                after_snapshot = {**base_snapshot, **stored_payload}

        if edit_ops:
            diff = [*diff, *_edit_summary_rows(edit_ops)]
            stored_payload = {**stored_payload, "_edit_ops": edit_ops}

        if kind in GROUNDED_KINDS:
            stored_payload["base_snapshot"] = base_snapshot
            stored_payload["after_snapshot"] = after_snapshot

        if edit_ops:
            stored_payload = {**stored_payload, "_edit_ops": edit_ops}

        proposal = ProfileProposal(
            user_id=user_id,
            kind=kind,
            action=action,
            entity_id=entity_id,
            entity_label=label[:200],
            payload_json=stored_payload,
            base_updated_at=base_updated_at,
            diff_json=diff,
            status=ProposalStatus.PENDING.value,
            source=source,
            chat_session_id=chat_session_id,
            chat_message_id=chat_message_id,
            ai_generation_id=ai_generation_id,
        )
        self.db.add(proposal)
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal

    async def create_from_ops(
        self,
        user_id: uuid.UUID,
        ops: list[dict],
        *,
        grounding: set[str],
        chat_session_id: Optional[uuid.UUID] = None,
        chat_message_id: Optional[uuid.UUID] = None,
        ai_generation_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[ProfileProposal], list[dict]]:
        """Best-effort batch creation: ops fail per-item with a reason.

        ``grounding`` is the plan-99 read-before-edit set —
        ``read:{kind}:{id-or-section}`` keys for every entity whose full
        content the model has seen this turn (or freshly cached). Ops
        editing unread targets are dropped with ``unread_target``, never
        silently applied.
        """
        resolved_ops, dropped = await resolve_ops(self.db, user_id, ops, grounding)
        created: list[ProfileProposal] = []
        for resolved in resolved_ops:
            try:
                created.append(
                    await self.create(
                        user_id,
                        chat_session_id=chat_session_id,
                        chat_message_id=chat_message_id,
                        ai_generation_id=ai_generation_id,
                        **resolved,
                    )
                )
            except (
                DomainError,
                PydanticValidationError,
                ValueError,
                KeyError,
            ) as exc:
                logger.warning(
                    "Profile op dropped (kind=%r action=%r): %s",
                    resolved.get("kind"),
                    resolved.get("action"),
                    str(exc)[:500],
                )
                dropped.append({"op": resolved, "reason": str(exc)})
        return created, dropped

    # ------------------------------------------------------------ queries

    async def list_(
        self,
        user_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[ProfileProposal]:
        query = select(ProfileProposal).where(ProfileProposal.user_id == user_id)
        if status is not None:
            query = query.where(ProfileProposal.status == status)
        query = query.order_by(
            (ProfileProposal.status == ProposalStatus.PENDING.value).desc(),
            ProfileProposal.created_at.desc(),
        ).limit(limit)
        rows = await self.db.execute(query)
        return list(rows.scalars().all())

    async def pending_count(self, user_id: uuid.UUID) -> int:
        rows = await self.db.execute(
            select(ProfileProposal.id).where(
                ProfileProposal.user_id == user_id,
                ProfileProposal.status == ProposalStatus.PENDING.value,
            )
        )
        return len(rows.scalars().all())

    async def preview(self, user_id: uuid.UUID, proposal_id: uuid.UUID) -> dict:
        """Lazy before/after payloads for the render modal (plan 99 AD7).

        Reads the snapshots persisted at creation — deterministic and
        offline of entity drift. Owner-scoped by ``get``; rows of the
        non-entity kinds and cards created before 99 shipped have no
        snapshots and 404 (the frontend hides the button).

        ``cv_synth`` (plan 101 AD2) previews before-only: the user's own
        KIND_SPECS-shaped snapshots of the referenced sources, fresh at
        preview time; sources deleted since the card degrade to
        label-only rows. The variant output itself does not exist until
        approve drafts it.
        """
        proposal = await self.get(user_id, proposal_id)
        payload = proposal.payload_json or {}
        if proposal.kind == ProposalKind.CV_SYNTH.value:
            resolved_refs = payload.get("resolved_refs")
            if not resolved_refs:
                raise NotFoundError("No preview for this proposal")
            sources = await self._cv_synth_sources(user_id, payload)
            if not sources:
                raise NotFoundError("No preview for this proposal")
            return {
                "before": sources,
                "after": None,
                "edits": {
                    "kind": ProposalKind.CV_SYNTH.value,
                    "action": payload.get("action") or "summarize",
                    "language": payload.get("language") or "en",
                    "resolved_refs": resolved_refs,
                    "posting": payload.get("resolved_posting") or "",
                    "posting_title": payload.get("resolved_posting_title") or "",
                },
            }
        if proposal.kind == ProposalKind.CV_SET_BULLETS.value:
            before = payload.get("before") or []
            bullets = payload.get("bullets") or []
            return {
                "before": [{"text": str(b)} for b in before],
                "after": [{"text": str(b)} for b in bullets],
                "edits": {
                    "kind": ProposalKind.CV_SET_BULLETS.value,
                    "cv_title": payload.get("cv_title") or "",
                    "item_label": payload.get("item_label") or "",
                },
            }
        if proposal.kind not in GROUNDED_KINDS:
            raise NotFoundError("No preview for this proposal")
        if proposal.action == ProposalAction.CREATE.value:
            if "after_snapshot" not in payload:
                raise NotFoundError("No preview for this proposal")
            return {
                "before": None,
                "after": payload["after_snapshot"],
                "edits": payload.get("_edit_ops") or {},
            }
        if proposal.action == ProposalAction.DELETE.value:
            before = payload.get("snapshot")
            if before is None:
                raise NotFoundError("No preview for this proposal")
            return {
                "before": before,
                "after": None,
                "edits": payload.get("_edit_ops") or {},
            }
        if "base_snapshot" not in payload:
            raise NotFoundError("No preview for this proposal")
        return {
            "before": payload["base_snapshot"],
            "after": payload.get("after_snapshot"),
            "edits": payload.get("_edit_ops") or {},
        }

    #: Entity kinds with KIND_SPECS-shaped snapshots available for the
    #: cv_synth preview; every other source key degrades to a label row.
    _CV_SYNTH_SNAPSHOT_KINDS = {
        "experience",
        "projects",
        "volunteer",
        "education",
        "certifications",
        "achievements",
    }

    def _cv_synth_kind_for(self, source_key: str) -> str:
        return {
            "experience": ProposalKind.EXPERIENCE_ITEM.value,
            "projects": ProposalKind.EXPERIENCE_ITEM.value,
            "volunteer": ProposalKind.EXPERIENCE_ITEM.value,
            "education": ProposalKind.EDUCATION_ITEM.value,
            "certifications": ProposalKind.CERTIFICATION.value,
            "achievements": ProposalKind.PROFILE_ACHIEVEMENT.value,
        }.get(source_key, "")

    async def _cv_synth_sources(
        self, user_id: uuid.UUID, payload: dict
    ) -> Optional[list[dict]]:
        """One stacked before-row per referenced source (plan 101 AD2):
        ref identity + the fresh KIND_SPECS snapshot, label-only when
        the source row is gone; the posting joins as its own row."""
        resolved_refs = payload.get("resolved_refs") or []
        by_key: dict[str, set[str]] = {}
        for ref in resolved_refs:
            source_key = str(ref.get("source_key") or "")
            item_id = str(ref.get("item_id") or "")
            if source_key and item_id:
                by_key.setdefault(source_key, set()).add(item_id)
        labels = {
            f"{ref.get('source_key')}:{ref.get('item_id')}": str(ref.get("label") or "")
            for ref in resolved_refs
        }
        sources: list[dict] = []
        for source_key, item_ids in by_key.items():
            kind = self._cv_synth_kind_for(source_key)
            spec = KIND_SPECS.get(kind)
            for item_id in sorted(item_ids):
                label = labels.get(f"{source_key}:{item_id}") or ""
                entry: dict[str, Any] = {
                    "source_key": source_key,
                    "item_id": item_id,
                    "label": label,
                    "snapshot": None,
                }
                if spec is not None and spec.model is not None:
                    try:
                        parsed = uuid.UUID(item_id)
                        entity, _ = await self._load_entity(kind, user_id, parsed)
                    except (NotFoundError, ValueError):
                        entity = None
                    if entity is not None:
                        entry["snapshot"] = _full_snapshot(kind, entity)
                sources.append(entry)
        posting_id = payload.get("posting_id")
        if posting_id:
            from app.models.posting_model import JobPosting

            try:
                parsed = uuid.UUID(str(posting_id))
            except ValueError:
                parsed = None
            posting = None
            if parsed is not None:
                rows = await self.db.execute(
                    select(JobPosting).where(JobPosting.id == parsed)
                )
                posting = rows.scalars().first()
            if posting is not None:
                sources.append(
                    {
                        "source_key": "posting",
                        "item_id": str(posting.id),
                        "label": str(posting.ref),
                        "snapshot": {
                            "ref": str(posting.ref),
                            "title": str(posting.title),
                            "org": str(posting.org),
                        },
                    }
                )
        if not any(entry["snapshot"] is not None for entry in sources):
            # Plan 101 AD2: all sources gone or unresolvable — the
            # preview has nothing truthful to show.
            return None
        return sources

    async def revert(
        self, user_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> ProfileProposal:
        """Inverse-apply an approved card through the form services
        (plan 99 AD10): update restores ``base_snapshot`` as the patch,
        delete recreates entity + children from the payload snapshot,
        create deletes the created entity. Blocks when the target moved
        after the apply — no silent clobber of later edits. ``reverted``
        is a terminal status.

        A direct user action on their own applied change — never a
        proposal card. Only the snapshot-backed entity kinds support
        revert.
        """
        proposal = await self.get(user_id, proposal_id)
        if proposal.status == ProposalStatus.REVERTED.value:
            return proposal
        if proposal.status != ProposalStatus.APPROVED.value:
            raise ValidationError(
                f"Only approved proposals can be reverted ({proposal.status})"
            )
        if proposal.kind not in GROUNDED_KINDS and proposal.kind not in (
            ProposalKind.CV_SET_BULLETS.value,
        ):
            raise ValidationError(f"Revert is not available for {proposal.kind}")
        payload = dict(proposal.payload_json or {})
        if proposal.action == ProposalAction.CREATE.value:
            if proposal.entity_id is None:
                raise NotFoundError("Created before revert existed — no target id")
        if (
            proposal.action
            in (
                ProposalAction.CREATE.value,
                ProposalAction.UPDATE.value,
            )
            and proposal.resolved_at is not None
        ):
            entity, updated_at = await self._load_entity(
                proposal.kind, user_id, proposal.entity_id
            )
            if _ts(updated_at) > _ts(proposal.resolved_at + _REVERT_TOLERANCE):
                raise ConflictError("Changed since it was applied — edit state moved")

        if proposal.kind == ProposalKind.CV_SET_BULLETS.value:
            restore = dict(payload)
            restore["bullets"] = list(payload.get("prior") or [])
            restore["restore"] = True
            await self._apply(
                proposal.kind,
                ProposalAction.UPDATE.value,
                proposal.entity_id,
                restore,
                user_id,
            )
        elif proposal.action == ProposalAction.UPDATE.value:
            base_snapshot = payload.get("base_snapshot")
            if not base_snapshot:
                raise NotFoundError("No snapshot — created before revert existed")
            await self._apply(
                proposal.kind,
                ProposalAction.UPDATE.value,
                proposal.entity_id,
                dict(base_snapshot),
                user_id,
            )
        elif proposal.action == ProposalAction.DELETE.value:
            snapshot = payload.get("snapshot")
            if not snapshot:
                raise NotFoundError("No snapshot — created before revert existed")
            await self._apply(
                proposal.kind,
                ProposalAction.CREATE.value,
                None,
                dict(snapshot),
                user_id,
            )
        else:
            await self._apply(
                proposal.kind,
                ProposalAction.DELETE.value,
                proposal.entity_id,
                {},
                user_id,
            )
        proposal.status = ProposalStatus.REVERTED.value
        await self.db.commit()
        return proposal

    async def get(self, user_id: uuid.UUID, proposal_id: uuid.UUID) -> ProfileProposal:
        rows = await self.db.execute(
            select(ProfileProposal).where(
                ProfileProposal.id == proposal_id,
                ProfileProposal.user_id == user_id,
            )
        )
        proposal = rows.scalars().first()
        if proposal is None:
            raise NotFoundError("Proposal not found")
        return proposal

    # ------------------------------------------------------------ resolve

    async def approve(
        self, user_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> tuple[ProfileProposal, Optional[dict], bool]:
        """Apply a pending proposal; idempotent once approved."""
        proposal = await self.get(user_id, proposal_id)
        if proposal.status == ProposalStatus.APPROVED.value:
            return proposal, None, True
        if proposal.status != ProposalStatus.PENDING.value:
            raise ValidationError(f"Cannot approve a {proposal.status} proposal")
        # cv_synth apply drafts rows in a self-committing service (the
        # audit rule), so the card must reach its terminal state BEFORE
        # the apply — a crash mid-apply leaves an approved card with a
        # resolve_error, never a retryable pending one (a retry would
        # duplicate the whole batch).
        terminal_first = proposal.kind == ProposalKind.CV_SYNTH.value
        if terminal_first:
            proposal.status = ProposalStatus.APPROVED.value
            proposal.resolved_at = datetime.now(timezone.utc)
            await self.db.commit()
        try:
            applied = await self._apply_checked(proposal)
        except ConflictError:
            raise
        except NotFoundError:
            proposal.status = ProposalStatus.EXPIRED.value
            proposal.resolve_error = "Target no longer exists"
            proposal.resolved_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise
        except DomainError as exc:
            proposal.resolve_error = str(exc)[:400]
            await self.db.commit()
            raise
        proposal.status = ProposalStatus.APPROVED.value
        proposal.resolved_at = datetime.now(timezone.utc)
        proposal.resolve_error = ""
        # Create ops link back to the created row only after apply —
        # revert of a create needs the id (plan 99 AD10).
        if (
            proposal.action == ProposalAction.CREATE.value
            and proposal.entity_id is None
            and applied is not None
            and applied.get("kind") == proposal.kind
            and applied.get("id")
        ):
            try:
                proposal.entity_id = uuid.UUID(str(applied["id"]))
            except ValueError:
                logger.warning("create proposal returned a non-UUID id")
        await self.db.commit()
        return proposal, applied, False

    async def reject(
        self, user_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> ProfileProposal:
        """Idempotent reject; applied proposals cannot be un-applied."""
        proposal = await self.get(user_id, proposal_id)
        if proposal.status == ProposalStatus.REJECTED.value:
            return proposal
        if proposal.status != ProposalStatus.PENDING.value:
            raise ValidationError(f"Cannot reject a {proposal.status} proposal")
        proposal.status = ProposalStatus.REJECTED.value
        proposal.resolved_at = datetime.now(timezone.utc)
        await self.db.commit()
        return proposal

    async def sweep_expired(self) -> int:
        """Flip stale pending cards to expired (scheduler-driven)."""
        cutoff = datetime.now(timezone.utc) - PROPOSAL_TTL
        result = await self.db.execute(
            update(ProfileProposal)
            .where(
                ProfileProposal.status == ProposalStatus.PENDING.value,
                ProfileProposal.created_at < cutoff,
            )
            .values(
                status=ProposalStatus.EXPIRED.value,
                resolved_at=datetime.now(timezone.utc),
                resolve_error="Expired",
            )
        )
        await self.db.commit()
        return int(result.rowcount or 0)

    # ------------------------------------------------------ apply plumbing

    async def _apply_checked(self, proposal: ProfileProposal) -> Optional[dict]:
        """Conflict-check, then dispatch to the form services."""
        kind = proposal.kind
        payload = dict(proposal.payload_json or {})
        user_id = proposal.user_id

        if proposal.base_updated_at is not None:
            entity, updated_at = await self._load_entity(
                kind, user_id, proposal.entity_id
            )
            if _ts(updated_at) != _ts(proposal.base_updated_at):
                if kind == ProposalKind.PROFILE_SECTION.value:
                    proposal.diff_json = self._section_diff(
                        entity, payload.get("section"), payload.get("value") or {}
                    )
                elif kind == ProposalKind.CV_SET_BULLETS.value:
                    proposal.diff_json = await self._cv_bullets_conflict_diff(
                        entity, payload
                    )
                else:
                    spec = KIND_SPECS[kind]
                    proposal.diff_json = self._update_diff(
                        spec, entity, self._patch_fields(kind, payload)
                    )
                if payload.get("_edit_ops"):
                    proposal.diff_json = [
                        *proposal.diff_json,
                        *_edit_summary_rows(payload["_edit_ops"]),
                    ]
                proposal.status = ProposalStatus.CONFLICT.value
                proposal.resolved_at = datetime.now(timezone.utc)
                await self.db.commit()
                raise ConflictError(
                    "Changed since it was proposed — review the updated diff"
                )
        return await self._apply(
            kind, proposal.action, proposal.entity_id, payload, user_id
        )

    def _patch_fields(self, kind: str, payload: dict) -> dict:
        if kind == ProposalKind.USER_SKILL.value:
            return payload
        model = KIND_SPECS[kind].update_model
        assert model is not None
        validated = model.model_validate(payload)
        return validated.model_dump(mode="json", exclude_unset=True)

    async def _apply_cv_synth(self, user_id: uuid.UUID, payload: dict) -> dict:
        """Draft variants for an approved cv_synth card (plan 82).

        The card approval is the human review, so rows are activated
        through the same `update` path the Synth Library button uses —
        slot supersede retires the previous owner (plan-62 semantics),
        never draft-purgatory. Small batches run inline; larger ones
        enqueue the existing `cv_synth` job with `activate` set (the
        completion notification announces active variants). Refs resolve
        against the user's context inside the service — stale/foreign
        ids surface as a resolve_error.
        """
        from app.schemas.cv_synth import CvSynthItemGenerate, CvSynthItemUpdate
        from app.services.cv_synth_service import CvSynthService, SYNC_LIMIT

        service = CvSynthService(self.db)
        request = CvSynthItemGenerate.model_validate(payload)
        if len(request.refs) > SYNC_LIMIT:
            from app.services.job_worker import enqueue

            job = await enqueue(
                self.db,
                "cv_synth",
                {"request": payload, "activate": True},
                user_id=user_id,
            )
            return {"queued": True, "job_id": str(job.id), "kind": "cv_synth"}
        rows = await service.generate(user_id, request)
        activated = []
        for row in rows:
            if row.status == "draft":
                row = await service.update(
                    row.id, user_id, CvSynthItemUpdate(status="active")
                )
            activated.append(row)
        return {
            "queued": False,
            "kind": "cv_synth",
            "items": [
                {"id": str(row.id), "variant_key": row.variant_key} for row in activated
            ],
        }

    async def _apply(
        self,
        kind: str,
        action: str,
        entity_id: Optional[uuid.UUID],
        payload: dict,
        user_id: uuid.UUID,
    ) -> Optional[dict]:
        """One dispatch table: the same calls the REST routers make."""
        from app.services.experience_service import ExperienceService
        from app.services.profile_service import ProfileService
        from app.services.profile_entities_service import ProfileEntitiesService
        from app.services.skills_service import SkillService

        entity: Any = None
        if kind == ProposalKind.CV_SYNTH.value:
            return await self._apply_cv_synth(user_id, payload)
        if kind == ProposalKind.CV_SET_BULLETS.value:
            return await self._apply_cv_set_bullets(payload, user_id)
        if kind == ProposalKind.EXPERIENCE_ITEM.value:
            service = ExperienceService(self.db)
            if action == ProposalAction.CREATE.value:
                entity = await service.create_item(user_id, dict(payload))
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                entity = await service.update_item(user_id, entity_id, dict(payload))
            else:
                assert entity_id is not None
                await service.delete_item(user_id, entity_id)
        elif kind == ProposalKind.EDUCATION_ITEM.value:
            service = ProfileEntitiesService(self.db)
            if action == ProposalAction.CREATE.value:
                entity = await service.create_education(
                    user_id, EducationItemIn.model_validate(payload)
                )
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                entity = await service.update_education(
                    entity_id, user_id, EducationItemPatch.model_validate(payload)
                )
            else:
                assert entity_id is not None
                await service.delete_education(entity_id, user_id)
        elif kind == ProposalKind.CERTIFICATION.value:
            service = ProfileEntitiesService(self.db)
            if action == ProposalAction.CREATE.value:
                entity = await service.create_certification(
                    user_id, CertificationIn.model_validate(payload)
                )
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                entity = await service.update_certification(
                    entity_id, user_id, CertificationPatch.model_validate(payload)
                )
            else:
                assert entity_id is not None
                await service.delete_certification(entity_id, user_id)
        elif kind == ProposalKind.PROFILE_ACHIEVEMENT.value:
            service = ProfileEntitiesService(self.db)
            if action == ProposalAction.CREATE.value:
                entity = await service.create_achievement(
                    user_id, ProfileAchievementIn.model_validate(payload)
                )
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                entity = await service.update_achievement(
                    entity_id, user_id, ProfileAchievementPatch.model_validate(payload)
                )
            else:
                assert entity_id is not None
                await service.delete_achievement(entity_id, user_id)
        elif kind == ProposalKind.USER_SKILL.value:
            service = SkillService(self.db)
            if action == ProposalAction.CREATE.value:
                add = UserSkillAddIn.model_validate(payload)
                row = await service.upsert_user_skill(
                    user_id, add.skill_key, add.level, add.confidence
                )
                return {
                    "id": str(row.id),
                    "kind": kind,
                    "label": add.skill_key,
                }
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                row = await self._owned_user_skill(user_id, entity_id)
                patch = UserSkillPatchIn.model_validate(payload)
                if patch.level is not None:
                    row.level = patch.level
                if patch.derive_enabled is not None:
                    row.derive_enabled = patch.derive_enabled
                await self.db.commit()
                await self.db.refresh(row)
                entity = row
            else:
                assert entity_id is not None
                row = await self._owned_user_skill(user_id, entity_id)
                await service.delete_user_skill(user_id, row.skill_id)
        elif kind == ProposalKind.PROFILE_SECTION.value:
            patch = ProfileSectionPatchIn.model_validate(payload)
            service = ProfileService(self.db)
            entity = await service.update(
                user_id, ProfileSectionUpdate(**{patch.section: patch.value})
            )
        else:
            raise ValidationError(f"Unknown proposal kind: {kind}")

        if entity is None:
            return None
        return {
            "id": str(getattr(entity, "id", uuid.uuid4())),
            "kind": kind,
            "label": self._entity_label(kind, entity),
        }

    # ---------------------------------------------------------- loaders

    async def _apply_cv_set_bullets(self, payload: dict, user_id: uuid.UUID) -> dict:
        """Write the approved bullet list through the two-layer model:
        a bullets VARIANT pinned on this CV. Restore (revert) unpins —
        the profile bullets render again. Overrides never carry
        achievements."""
        from app.schemas.cv_synth import (
            CvSynthBullet,
            CvSynthItemCreate,
            CvSynthItemUpdate,
            CvSynthPayload,
            CvSynthVoice,
        )
        from app.services.cv_service import CvService
        from app.services.cv_synth_service import CvSynthService

        cv = await CvService(self.db).get_owned(
            uuid.UUID(str(payload["cv_id"])), user_id
        )
        source_key = payload["source_key"]
        item_id = payload["item_id"]
        pin_key = f"{source_key}:{item_id}:bullets"
        selection = CvContextSelection.model_validate(cv.context or {})
        service = CvSynthService(self.db)
        if payload.get("restore"):
            selection.synth_pins = {
                key: value
                for key, value in (selection.synth_pins or {}).items()
                if key != pin_key
            }
        else:
            bullets_payload = CvSynthPayload(
                achievements=[
                    CvSynthBullet(text=str(bullet))
                    for bullet in payload.get("bullets") or []
                ]
            )
            pinned_id = (selection.synth_pins or {}).get(pin_key)
            if pinned_id:
                await service.update(
                    uuid.UUID(str(pinned_id)),
                    user_id,
                    CvSynthItemUpdate(payload=bullets_payload),
                )
            else:
                row = await service.create_manual(
                    user_id,
                    CvSynthItemCreate(
                        refs=[{"source_key": source_key, "item_id": item_id}],
                        scope="bullets",
                        payload=bullets_payload,
                        voice=CvSynthVoice(language=str(cv.language or "en")),
                    ),
                )
                selection.synth_pins = {
                    **(selection.synth_pins or {}),
                    pin_key: str(row.id),
                }
        cv.context = selection.model_dump(mode="json")
        await self.db.flush()
        return {"kind": ProposalKind.CV_SET_BULLETS.value, "id": str(cv.id)}

    async def _cv_bullets_conflict_diff(self, cv: Any, payload: dict) -> list[dict]:
        """Fresh before-side when the CV moved since the card was
        proposed — the resolver's stored `before` is stale."""
        from app.services.cv_synth_service import CvSynthService

        selection = CvContextSelection.model_validate(cv.context or {})
        pinned_id = (selection.synth_pins or {}).get(
            f"{payload.get('source_key')}:{payload.get('item_id')}:bullets"
        )
        entries = None
        if pinned_id:
            variant = await CvSynthService(self.db).get_owned(
                uuid.UUID(str(pinned_id)), cv.user_id
            )
            entries = (variant.payload or {}).get("achievements")
        before = [
            str(entry.get("text") or "")
            for entry in entries or []
            if isinstance(entry, dict)
        ]
        after = [str(b) for b in payload.get("bullets") or []]
        rows = [
            {"field": "removed_bullet", "from": b, "to": None}
            for b in before
            if b not in after
        ]
        rows.extend(
            {"field": "added_bullet", "from": None, "to": b}
            for b in after
            if b not in before
        )
        return rows

    def _cv_bullets_label(self, payload: dict) -> str:
        return (
            f"Bullets of {payload.get('item_label') or 'item'}"
            f" on {payload.get('cv_title') or 'CV'}"
        )

    def _cv_bullets_diff(self, payload: dict) -> list[dict]:
        before = [
            str(b.get("text") or "") if isinstance(b, dict) else str(b)
            for b in payload.get("before") or []
        ]
        after = [str(b) for b in payload.get("bullets") or []]
        removed = [b for b in before if b not in after]
        added = [b for b in after if b not in before]
        rows = [{"field": "removed_bullet", "from": b, "to": None} for b in removed]
        rows.extend({"field": "added_bullet", "from": None, "to": b} for b in added)
        return rows

    async def _load_entity(
        self,
        kind: str,
        user_id: uuid.UUID,
        entity_id: Optional[uuid.UUID],
    ) -> tuple[Any, Optional[datetime]]:
        if kind == ProposalKind.USER_SKILL.value:
            if entity_id is None:
                raise NotFoundError("Target skill row not found")
            row = await self._owned_user_skill(user_id, entity_id)
            return row, row.updated_at
        if kind == ProposalKind.PROFILE_SECTION.value:
            profile = await self._load_profile(user_id)
            return profile, profile.updated_at
        if kind == ProposalKind.CV_SET_BULLETS.value:
            from app.services.cv_service import CvService

            assert entity_id is not None
            cv = await CvService(self.db).get_owned(entity_id, user_id)
            return cv, cv.updated_at
        model = KIND_SPECS[kind].model
        assert model is not None
        query = select(model).where(model.id == entity_id, model.user_id == user_id)
        if model is ExperienceItem:
            # The update diff reads every patched field via getattr — the
            # skill/achievement collections lazy-load and would raise
            # MissingGreenlet in this async context unless eager-loaded;
            # the skill key needs the nested ExperienceSkill.skill join.
            query = query.options(
                selectinload(ExperienceItem.skills).selectinload(ExperienceSkill.skill),
                selectinload(ExperienceItem.achievements),
            )
        rows = await self.db.execute(query)
        entity = rows.scalars().first()
        if entity is None:
            raise NotFoundError("Target entity not found")
        return entity, entity.updated_at

    async def _owned_user_skill(
        self, user_id: uuid.UUID, row_id: uuid.UUID
    ) -> UserSkill:
        rows = await self.db.execute(
            select(UserSkill)
            .options(selectinload(UserSkill.skill))
            .where(UserSkill.id == row_id, UserSkill.user_id == user_id)
        )
        row = rows.scalars().first()
        if row is None:
            raise NotFoundError("Target skill row not found")
        return row

    async def _load_profile(self, user_id: uuid.UUID) -> Profile:
        from app.services.profile_service import ProfileService

        return await ProfileService(self.db).get(user_id)

    # ------------------------------------------------------- read tools

    async def read_entity_content(
        self, kind: str, user_id: uuid.UUID, entity_id: uuid.UUID
    ) -> dict:
        """Full content of one profile entity (plan 99.1 read-before-edit).

        The chat tool payload: every field at its current value (raw
        stored text, not the digest truncation) plus experience children
        with stable ids — the remove-anchors for granular edits.
        """
        if kind not in GROUNDED_KINDS:
            raise ValidationError(f"kind {kind!r} has no readable entity")
        entity, updated_at = await self._load_entity(kind, user_id, entity_id)
        skip = {
            "id",
            "user_id",
            "org_id",
            "university_id",
            "department_id",
            "skill_id",
            "created_at",
            "updated_at",
        }
        content: dict[str, Any] = {}
        for column in entity.__table__.columns:
            if column.name in skip:
                continue
            value = getattr(entity, column.key, None)
            content[column.key] = (
                value.isoformat() if isinstance(value, (datetime, date)) else value
            )
        if kind == ProposalKind.EXPERIENCE_ITEM.value:
            content["skills"] = [
                {
                    "id": str(link.id),
                    "skill_key": link.skill.key if link.skill else None,
                    "skill_label": link.skill.label if link.skill else None,
                    "role_in_item": link.role_in_item,
                    "level_claim": link.level_claim,
                }
                for link in entity.skills or []
            ]
            content["achievements"] = [
                {"id": str(row.id), "text": row.text, "metric": row.metric}
                for row in entity.achievements or []
            ]
        return {
            "kind": kind,
            "entity_id": str(entity.id),
            "label": self._entity_label(kind, entity),
            "updated_at": updated_at.isoformat() if updated_at else None,
            "content": content,
            "note": "Exact current content — quote it verbatim in edit ops.",
        }

    async def read_section_content(self, user_id: uuid.UUID, section: str) -> dict:
        """Full JSON of one profile section (plan 99.1 read-before-edit)."""
        if section not in SECTION_NAMES:
            raise ValidationError(f"unknown profile section {section!r}")
        profile = await self._load_profile(user_id)
        return {
            "kind": ProposalKind.PROFILE_SECTION.value,
            "section": section,
            "updated_at": (
                profile.updated_at.isoformat() if profile.updated_at else None
            ),
            "content": getattr(profile, section, None),
            "note": "Exact current content — full-section replacement needs it.",
        }

    # ------------------------------------------------------- diff helpers

    def _create_label(self, kind: str, payload: dict) -> str:
        if kind == ProposalKind.EXPERIENCE_ITEM.value:
            return str(payload.get("title") or "")
        if kind == ProposalKind.EDUCATION_ITEM.value:
            return str(payload.get("institution") or "")
        if kind == ProposalKind.CERTIFICATION.value:
            return str(payload.get("name") or "")
        if kind == ProposalKind.PROFILE_ACHIEVEMENT.value:
            return str(payload.get("title") or "")
        if kind == ProposalKind.USER_SKILL.value:
            return str(payload.get("skill_key") or "")
        return ""

    def _cv_synth_label(self, payload: dict) -> str:
        """Card label (plan 101 AD1): resolved ref labels, ≤2 abbreviated
        ("Sample Internship (+2)"), the posting ref when posting-aimed.
        Pre-101 payloads (no ``resolved_refs``) keep the count fallback."""
        refs = payload.get("refs") or []
        posting_id = payload.get("posting_id")
        posting = (
            f" · posting {payload.get('resolved_posting')}"
            if posting_id and payload.get("resolved_posting")
            else " · posting fit"  # legacy shape
            if posting_id
            else ""
        )
        resolved = payload.get("resolved_refs") or []
        labels = [
            str(row.get("label") or "").strip()
            for row in resolved
            if str(row.get("label") or "").strip()
        ]
        if not labels:
            base = f"{len(refs)} item(s)"
        elif len(labels) == 1:
            base = labels[0]
        elif len(labels) == 2:
            base = f"{labels[0]} + {labels[1]}"
        else:
            base = f"{labels[0]} (+{len(labels) - 1})"
        return f"{base} · {payload.get('action', 'summarize')}{posting}"

    def _cv_synth_diff(self, payload: dict) -> list[dict]:
        resolved = payload.get("resolved_refs") or []
        refs: list[Any]
        if resolved:
            refs = [
                {
                    "label": row.get("label"),
                    "source_key": row.get("source_key"),
                    "item_id": row.get("item_id"),
                }
                for row in resolved
            ]
        else:
            refs = [
                f"{ref.get('source_key')}:{ref.get('item_id')}"
                for ref in payload.get("refs") or []
            ]
        rows: list[dict] = [
            {"field": "refs", "label": "Items", "before": None, "after": refs[:15]},
            {
                "field": "action",
                "label": "Action",
                "before": None,
                "after": payload.get("action") or "summarize",
            },
            {
                "field": "language",
                "label": "Language",
                "before": None,
                "after": payload.get("language") or "en",
            },
        ]
        if payload.get("posting_id"):
            posting_row = str(payload["posting_id"])
            if payload.get("resolved_posting"):
                posting_row = str(payload["resolved_posting"])
                if payload.get("resolved_posting_title"):
                    posting_row = f"{posting_row} — {payload['resolved_posting_title']}"
            rows.append(
                {
                    "field": "posting_id",
                    "label": "Target posting",
                    "before": None,
                    "after": posting_row,
                }
            )
        return rows

    def _create_diff(self, spec: KindSpec, payload: dict) -> list[dict]:
        labels = dict(spec.fields)
        rows = []
        for field, value in payload.items():
            if field in {"source", "status"} and (
                value in (None, "", [], "self_report", "active")
            ):
                continue
            raw_after = value
            after = _payload_value(field, value)
            flattened = True
            if (
                field in _LIST_FIELDS
                and isinstance(raw_after, list)
                and any(isinstance(entry, dict) for entry in raw_after)
            ):
                after = _structured_entries(field, raw_after)
                flattened = False
            if after in (None, "", []):
                continue
            rows.append(
                {
                    "field": field,
                    "label": labels.get(field, field.replace("_", " ").title()),
                    "before": None,
                    "after": after
                    if isinstance(after, list) and not flattened
                    else _jsonish(after),
                }
            )
        return rows

    def _update_diff(
        self, spec: KindSpec, entity: Any, patch_fields: dict
    ) -> list[dict]:
        labels = dict(spec.fields)
        rows = []
        for field, after_raw in patch_fields.items():
            raw_before = _before_value(getattr(entity, field, None))
            structured = (
                field in _LIST_FIELDS
                and isinstance(after_raw, list)
                and bool(after_raw)
                and all(isinstance(entry, dict) for entry in after_raw)
            )
            if structured:
                before = _structured_entries(field, raw_before)
                after = _structured_entries(field, after_raw)
                equal = json.dumps(before, sort_keys=True, default=str) == json.dumps(
                    after, sort_keys=True, default=str
                )
                if equal:
                    continue
                rows.append(
                    {
                        "field": field,
                        "label": labels.get(field, field.replace("_", " ").title()),
                        "before": before,
                        "after": after,
                    }
                )
                continue
            before = _payload_value(field, raw_before)
            after = _payload_value(field, after_raw)
            if _jsonish(before) == _jsonish(after):
                continue
            rows.append(
                {
                    "field": field,
                    "label": labels.get(field, field.replace("_", " ").title()),
                    "before": before if isinstance(before, list) else _jsonish(before),
                    "after": after if isinstance(after, list) else _jsonish(after),
                }
            )
        return rows

    def _section_diff(
        self, profile: Any, section: Optional[str], value: dict
    ) -> list[dict]:
        if not section:
            return []
        label = section.replace("_", " ").title()
        return [
            {
                "field": section,
                "label": label,
                "before": _jsonish(getattr(profile, section, None)),
                "after": _jsonish(value),
            }
        ]

    def _entity_label(self, kind: str, entity: Any) -> str:
        if kind == ProposalKind.EXPERIENCE_ITEM.value:
            return str(entity.title or "")
        if kind == ProposalKind.EDUCATION_ITEM.value:
            return str(entity.institution or "")
        if kind == ProposalKind.CERTIFICATION.value:
            return str(entity.name or "")
        if kind == ProposalKind.PROFILE_ACHIEVEMENT.value:
            return str(entity.title or "")
        if kind == ProposalKind.USER_SKILL.value:
            skill = getattr(entity, "skill", None)
            return str(skill.label if skill is not None else entity.skill_id)
        if kind == ProposalKind.PROFILE_SECTION.value:
            return "profile"
        return ""
