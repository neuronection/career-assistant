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
    CvSynthOpPayload,
    ProfileSectionPatchIn,
    UserSkillAddIn,
    UserSkillPatchIn,
)

PROPOSAL_TTL = timedelta(days=14)
DIFF_VALUE_CAP = 200

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
            "skill_key": value.skill.key if value.skill is not None else None,
            "role_in_item": value.role_in_item,
            "level_claim": value.level_claim,
            "last_used": value.last_used.isoformat() if value.last_used else None,
        }
    if hasattr(value, "text"):
        return {"text": value.text}
    return value


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
        chat_session_id: Optional[uuid.UUID] = None,
        chat_message_id: Optional[uuid.UUID] = None,
        ai_generation_id: Optional[uuid.UUID] = None,
    ) -> ProfileProposal:
        """Validate one op against its REST schema and persist the card."""
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
            label = self._cv_synth_label(stored_payload)
            diff = self._cv_synth_diff(stored_payload)
        elif action == ProposalAction.CREATE.value:
            model = spec.create_model
            assert model is not None
            validated = model.model_validate(payload)
            stored_payload = validated.model_dump(mode="json")
            label = self._create_label(kind, stored_payload)
            diff = self._create_diff(spec, stored_payload)
        else:
            entity, base_updated_at = await self._load_entity(kind, user_id, entity_id)
            label = self._entity_label(kind, entity)
            if action == ProposalAction.DELETE.value:
                stored_payload = {"snapshot": self._snapshot(spec, entity)}
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
        """Best-effort batch creation: invalid ops drop with a reason.

        ``grounding`` is the plan-99 read-before-edit set —
        ``read:{kind}:{id-or-section}`` keys for every entity whose full
        content the model has seen this turn (or freshly cached). Ops
        editing unread targets are dropped with ``unread_target``, never
        silently applied.
        """
        created: list[ProfileProposal] = []
        dropped: list[dict] = []
        for op in ops:
            try:
                entity_id = op.get("entity_id")
                if isinstance(entity_id, str) and entity_id:
                    entity_id = uuid.UUID(entity_id)
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
                created.append(
                    await self.create(
                        user_id,
                        kind=op.get("kind", ""),
                        action=op.get("action", ""),
                        payload=payload,
                        entity_id=entity_id,
                        chat_session_id=chat_session_id,
                        chat_message_id=chat_message_id,
                        ai_generation_id=ai_generation_id,
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
                    op.get("kind"),
                    op.get("action"),
                    str(exc)[:500],
                )
                dropped.append({"op": op, "reason": str(exc)})
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
                else:
                    spec = KIND_SPECS[kind]
                    proposal.diff_json = self._update_diff(
                        spec, entity, self._patch_fields(kind, payload)
                    )
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
        refs = payload.get("refs") or []
        posting = " · posting fit" if payload.get("posting_id") else ""
        return f"{len(refs)} item(s) · {payload.get('action', 'summarize')}{posting}"

    def _cv_synth_diff(self, payload: dict) -> list[dict]:
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
            rows.append(
                {
                    "field": "posting_id",
                    "label": "Target posting",
                    "before": None,
                    "after": str(payload["posting_id"]),
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
            after = _payload_value(field, value)
            if after in (None, "", []):
                continue
            rows.append(
                {
                    "field": field,
                    "label": labels.get(field, field.replace("_", " ").title()),
                    "before": None,
                    "after": after if isinstance(after, list) else _jsonish(after),
                }
            )
        return rows

    def _update_diff(
        self, spec: KindSpec, entity: Any, patch_fields: dict
    ) -> list[dict]:
        labels = dict(spec.fields)
        rows = []
        for field, after in patch_fields.items():
            before = _payload_value(field, _before_value(getattr(entity, field, None)))
            after = _payload_value(field, after)
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

    def _snapshot(self, spec: KindSpec, entity: Any) -> dict:
        """Full entity snapshot for delete ops (revert + messaging).

        Walks the table's own columns — complete by construction, no
        per-kind field list to keep in sync.
        """
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
        snapshot: dict[str, Any] = {}
        for column in entity.__table__.columns:
            if column.name in skip:
                continue
            value = getattr(entity, column.key, None)
            snapshot[column.key] = (
                value.isoformat()
                if isinstance(value, (datetime, date))
                else _jsonish(value)
            )
        return snapshot

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
