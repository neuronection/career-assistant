"""Grounding + anchored-edit resolution (plan 123.1).

Read-before-edit keys, cv_synth/cv_set_bullets ref resolution and the
text/collection edit families — model-emitted content resolved against
server truth, never persisted directly.
"""

import logging
import uuid
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, ValidationError
from app.models.enums import ProposalAction, ProposalKind
from app.schemas.cv import CvContextSelection
from app.schemas.profile_proposal import (
    CollectionEdit,
    CvChoiceOpPayload,
    CvSetBulletsOpPayload,
    CvSynthOpPayload,
    ProfileSectionPatchIn,
    TextEdit,
)
from app.services.proposals.kinds import (
    _HEADING_ECHO_KINDS,
    _SECTION_MODELS,
    GROUNDED_KINDS,
    KIND_SPECS,
    SECTION_NAMES,
    TEXT_FIELDS,
)

logger = logging.getLogger(__name__)


def _strip_entity_heading_echo(kind: str, entity: Any, stored_payload: dict) -> None:
    """Strip an echoed lead from proposed prose, in place.

    The renderer already prints the item's title/org as the row heading;
    a description or bullet that re-opens with them ("**Application
    Support**, **OTE Group** — production tier…") reads as a duplicate
    record. This applies the same deterministic strip the CV merge
    funnel uses: leading subject/issuer restatement on a dash is cut,
    prose without the echo passes through untouched."""
    if kind not in _HEADING_ECHO_KINDS:
        return None
    subject_attr, issuer_attr = _HEADING_ECHO_KINDS[kind]
    row = {
        "title": getattr(entity, subject_attr, None),
        "program": getattr(entity, subject_attr, None),
        "org": getattr(entity, issuer_attr, None),
    }

    def _strip(text: str) -> str:
        from app.services.cv.cv_context_service import _strip_subject_echo

        return _strip_subject_echo(row, text)

    if isinstance(stored_payload.get("description"), str):
        stored_payload["description"] = _strip(stored_payload["description"])
    for entry in stored_payload.get("achievements") or []:
        if isinstance(entry, dict) and isinstance(entry.get("text"), str):
            entry["text"] = _strip(entry["text"])
    return None


def read_key_for_op(op: dict, entity_id: uuid.UUID | None) -> str | None:
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


async def resolve_cv_synth_payload(db: AsyncSession, user_id: uuid.UUID, payload: dict) -> dict:
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
        from app.services.cv.cv_context_service import CV_CONTEXT_SOURCES

        for source_key, item_ids in by_key.items():
            definition = CV_CONTEXT_SOURCES.get(source_key)
            resolved: dict[str, str] = {}
            if definition is not None:
                try:
                    rows = await definition.resolver(db, user_id)
                except Exception as exc:
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


async def resolve_cv_set_bullets(db: AsyncSession, user_id: uuid.UUID, payload: dict) -> dict:
    """Plan 107: ground a cv_set_bullets op in server truth.

    Loads the owned CV, resolves the target row through the context
    engine (the same rows the renderer draws) and captures the CURRENT
    bullet list — the override when one exists, the profile-snapshot
    list otherwise — so the card renders an informed before/after and
    revert can restore exactly what was there.
    """
    from app.services.cv.cv_builder_service import CvBuilderService
    from app.services.cv.cv_service import CvService

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
        raise ValidationError("Target item is not on this CV's context — include it first")
    selection = CvContextSelection.model_validate(cv.context or {})
    # Plan 110 single slot: one pin key per item; when the pinned row
    # carries achievements, those ARE the current bullets.
    pinned_id = (selection.synth_pins or {}).get(f"{source_key}:{item_id}")
    variant_entries: list[dict] | None = None
    if pinned_id:
        from app.services.cv.cv_synth_service import CvSynthService

        variant = await CvSynthService(db).get_owned(uuid.UUID(str(pinned_id)), user_id)
        entries = (variant.payload or {}).get("achievements") or []
        if not entries:
            # A text-only pin leaves the profile's bullets rendering — the
            # card's "before" is the profile list, not an empty variant list.
            pinned_id = None
        else:
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
        "entity_row": {
            "title": str(row.get("title") or ""),
            "org": str(row.get("org_name") or row.get("org") or ""),
        },
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
            label if label == f"Unknown item ({source_key})" else f"{label} ({source_key})"
        )
    if labels:
        return labels
    return [
        f"{ref.get('source_key')}:{ref.get('item_id')}"
        for ref in (op.get("payload") or {}).get("refs") or []
    ]


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
    urls are conflicting edits); removes match by the child's own id
    from the read snapshot ({skill_key} for skills, exact text for
    achievements, exact url for links as fallback) — an unknown anchor
    is an anchor mismatch, never a partial rewrite.
    """
    skills: list[dict] = [
        {
            "id": str(link.id),
            "skill_key": link.skill.key if link.skill else str(link.skill_id),
            "role_in_item": link.role_in_item,
            "level_claim": link.level_claim,
        }
        for link in entity.skills or []
    ]
    achievements: list[dict] = [
        {"id": str(row.id), "text": row.text, "metric": row.metric}
        for row in entity.achievements or []
    ]
    links: list[dict] = [dict(_as_link_entry(link)) for link in entity.links or [] if link]

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
                        f"conflicting_edit: skill {key!r} is already linked to this item"
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
                achievements.append({"text": entry["text"], "metric": entry.get("metric")})
            else:
                entry = _as_link_entry(value)
                url = entry.get("url")
                if not url:
                    raise ValidationError("anchor_mismatch: link add needs a url")
                if any(row.get("url") == url for row in links):
                    raise ValidationError(f"conflicting_edit: link {url!r} already exists")
                links.append(entry)
        else:
            match = edit.match or {}
            if edit.collection == "skills":
                index = next(
                    (
                        i
                        for i, row in enumerate(skills)
                        if row.get("id") == match.get("id")
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
                        if row.get("id") == match.get("id") or row.get("text") == match.get("text")
                    ),
                    -1,
                )
                _drop(achievements, index, "achievement")
            else:
                index = next(
                    (i for i, row in enumerate(links) if row.get("url") == match.get("url")),
                    -1,
                )
                _drop(links, index, "link")

    resolved: dict = {}
    if "skills" in touched:
        resolved["skills"] = skills
    if "achievements" in touched:
        resolved["achievements"] = achievements
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
            raise ValidationError(f"text_edits apply to {sorted(TEXT_FIELDS)} — not {kind!r}")
        payload = _resolve_text_edits(kind, entity, payload, text_edits)
        edit_ops["text_edits"] = [
            TextEdit.model_validate(raw).model_dump(mode="json") for raw in text_edits
        ]
    if collection_edits:
        if kind != ProposalKind.EXPERIENCE_ITEM.value:
            raise ValidationError("collection_edits apply to experience_item only")
        payload.update(_resolve_collection_edits(entity, payload, collection_edits))
        edit_ops["collection_edits"] = [
            CollectionEdit.model_validate(raw).model_dump(mode="json") for raw in collection_edits
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
        payload["achievements"] = [_as_achievement_entry(a) for a in payload["achievements"]]
    if isinstance(payload.get("links"), list):
        payload["links"] = [_as_link_entry(link) for link in payload["links"]]
    return payload


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
    from app.services.proposals.service import ProfileProposalService

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
            # cv_synth / cv_set_bullets identify via payload fields
            # (cv_id / source_key / item_id); models echo an entity_id
            # anyway — tolerate it instead of dropping the card.
            if kind in (
                ProposalKind.CV_SYNTH.value,
                ProposalKind.CV_SET_BULLETS.value,
            ):
                entity_id = None
            target_key: tuple[str, str] | None = None
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
                and any(field in payload for field in ("skills", "achievements", "links"))
            ):
                raise ValidationError(
                    "conflicting_edit: full-replacement of skills, "
                    "achievements or links in an update payload is "
                    "retired — use collection_edits"
                )
            text_edits = list(op.get("text_edits") or [])
            collection_edits = list(op.get("collection_edits") or [])
            edit_ops: dict | None = op.get("edit_ops")
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
            elif kind == ProposalKind.CV_CHOICE.value:
                CvChoiceOpPayload.model_validate(payload)
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
