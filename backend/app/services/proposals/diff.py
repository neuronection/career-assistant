"""Card diff builders: field rows, labels, structured chip data (plan 123.1)."""

import json
from datetime import datetime
from typing import Any

from app.models.enums import ProposalKind
from app.models.experience_model import ExperienceSkill
from app.services.proposals.anchors import (
    _as_achievement_entry,
    _as_link_entry,
    _as_skill_entry,
)
from app.services.proposals.kinds import DIFF_VALUE_CAP, KindSpec


def _jsonish(value: Any) -> Any:
    """Diff-safe scalar rendering: primitives stay native, the rest
    becomes a compact JSON string capped at ``DIFF_VALUE_CAP``."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
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


def _truncate(text: str, cap: int = 60) -> str:
    text = (text or "").strip()
    if len(text) <= cap:
        return text
    return text[: cap - 1] + "…"


def _edit_summary_rows(edit_ops: dict | None) -> list[dict]:
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


def _cv_choice_label(payload: dict) -> str:
    """Card title: question excerpt."""
    question = str(payload.get("question") or "").strip()
    return question[:200]


def _cv_choice_diff(payload: dict) -> list[dict]:
    """Choice-card diff: the option list as label rows (audit surface)."""
    return [
        {
            "field": "options",
            "label": "Options",
            "before": [],
            "after": [
                {
                    "key": option.get("key"),
                    "label": option.get("label"),
                    "description": option.get("description") or "",
                    "kind": option.get("kind"),
                    "action": option.get("action"),
                }
                for option in payload.get("options") or []
            ],
        }
    ]


class DiffMixin:
    """Label + diff builders; pure (no db access)."""

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
        ("Sample Internship (+2)"), the posting ref when posting-aimed."""
        refs = payload.get("refs") or []
        posting_id = payload.get("posting_id")
        posting = (
            f" · posting {payload.get('resolved_posting')}"
            if posting_id and payload.get("resolved_posting")
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
                f"{ref.get('source_key')}:{ref.get('item_id')}" for ref in payload.get("refs") or []
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
            if field in {"source", "status"} and (value in (None, "", [], "self_report", "active")):
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

    def _update_diff(self, spec: KindSpec, entity: Any, patch_fields: dict) -> list[dict]:
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

    def _section_diff(self, profile: Any, section: str | None, value: dict) -> list[dict]:
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
