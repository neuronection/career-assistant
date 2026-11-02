"""Apply plumbing: dispatch to the form services + loaders (plan 123.1)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any, overload

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import ProposalAction, ProposalKind, ProposalStatus
from app.models.experience_model import ExperienceItem, ExperienceSkill
from app.models.profile_proposal_model import ProfileProposal
from app.models.user_model import Profile, UserSkill
from app.schemas.cv import CvContextRef, CvContextSelection
from app.schemas.profile import ProfileSectionUpdate
from app.schemas.profile_entities import (
    CertificationIn,
    CertificationPatch,
    EducationItemIn,
    EducationItemPatch,
    ProfileAchievementIn,
    ProfileAchievementPatch,
)
from app.schemas.profile_proposal import (
    ProfileSectionPatchIn,
    UserSkillAddIn,
    UserSkillPatchIn,
)
from app.services.proposals.anchors import resolve_cv_set_bullets
from app.services.proposals.diff import DiffMixin, _edit_summary_rows
from app.services.proposals.kinds import (
    _REVERT_TOLERANCE,
    GROUNDED_KINDS,
    KIND_SPECS,
    SECTION_NAMES,
)


@overload
def _ts(value: datetime) -> str: ...


@overload
def _ts(value: datetime | None) -> str | None: ...


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class ApplyMixin(DiffMixin):
    """Apply plumbing + proposal/entity loaders (needs ``self.db``)."""

    db: AsyncSession

    async def revert(self, user_id: uuid.UUID, proposal_id: uuid.UUID) -> ProfileProposal:
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
            raise ValidationError(f"Only approved proposals can be reverted ({proposal.status})")
        if proposal.kind not in GROUNDED_KINDS and proposal.kind not in (
            ProposalKind.CV_SET_BULLETS.value,
        ):
            raise ValidationError(f"Revert is not available for {proposal.kind}")
        payload = dict(proposal.payload_json or {})
        if proposal.action == ProposalAction.CREATE.value and proposal.entity_id is None:
            raise NotFoundError("Created before revert existed — no target id")
        if (
            proposal.action
            in (
                ProposalAction.CREATE.value,
                ProposalAction.UPDATE.value,
            )
            and proposal.resolved_at is not None
        ):
            _entity, updated_at = await self._load_entity(
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

    # ------------------------------------------------------ apply plumbing

    async def _apply_checked(self, proposal: ProfileProposal) -> dict | None:
        """Conflict-check, then dispatch to the form services."""
        kind = proposal.kind
        payload = dict(proposal.payload_json or {})
        user_id = proposal.user_id

        if proposal.base_updated_at is not None:
            entity, updated_at = await self._load_entity(kind, user_id, proposal.entity_id)
            if _ts(updated_at) != _ts(proposal.base_updated_at):
                if kind == ProposalKind.CV_SET_BULLETS.value:
                    # The CV's timestamp moves on ANY bullets activity
                    # (each approval rewrites cv.context pins), so a
                    # plain timestamp check false-conflicts siblings on
                    # the same CV. The honest sentinel is granular: the
                    # card's own item bullets (fresh override?? snapshot
                    # snapshot list) and its pin state must still match.
                    resolved = await resolve_cv_set_bullets(self.db, user_id, payload)
                    fresh_before = [
                        str(entry.get("text") or "")
                        for entry in resolved["before"]
                        if isinstance(entry, dict)
                    ]
                    stored_before = [
                        str(entry.get("text") or "") if isinstance(entry, dict) else str(entry)
                        for entry in payload.get("before") or []
                    ]
                    pin_moved = (resolved["prior_variant_id"] or "") != (
                        str(payload.get("prior_variant_id") or "")
                    )
                    if fresh_before == stored_before and not pin_moved:
                        return await self._apply(
                            kind,
                            proposal.action,
                            proposal.entity_id,
                            payload,
                            user_id,
                        )
                    proposal.diff_json = await self._cv_bullets_conflict_diff(entity, payload)
                elif kind == ProposalKind.PROFILE_SECTION.value:
                    proposal.diff_json = self._section_diff(
                        entity, payload.get("section"), payload.get("value") or {}
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
                proposal.resolved_at = datetime.now(UTC)
                await self.db.commit()
                raise ConflictError("Changed since it was proposed — review the updated diff")
        if kind == ProposalKind.TOOL_EXECUTION.value:
            # The confirmed destructive call: re-validated + executed with
            # an audit row inside the confirm funnel (the card is already
            # terminal — terminal-first in approve()).
            from app.ai.tools.confirm import apply_tool_execution

            return await apply_tool_execution(self.db, proposal)
        return await self._apply(kind, proposal.action, proposal.entity_id, payload, user_id)

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
        from app.services.cv.cv_synth_service import SYNC_LIMIT, CvSynthService

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
                row = await service.update(row.id, user_id, CvSynthItemUpdate(status="active"))
            activated.append(row)
        applied = {
            "queued": False,
            "kind": "cv_synth",
            "items": [{"id": str(row.id), "variant_key": row.variant_key} for row in activated],
        }
        cv_id = payload.get("cv_id")
        if activated and cv_id:
            # Plan-104 follow-up, one gesture: accept → activate AND star
            # the variants on the proposing session's CV so the Studio's
            # live preview renders them with no extra hand trip.
            try:
                cv_id_parsed = uuid.UUID(str(cv_id))
            except ValueError:
                cv_id_parsed = None
            if cv_id_parsed is not None:
                pinned_now = await service.pin_variants_on_cv(user_id, cv_id_parsed, activated)
                if pinned_now:
                    applied["pinned_cv_id"] = str(cv_id_parsed)
        return applied

    async def _apply(
        self,
        kind: str,
        action: str,
        entity_id: uuid.UUID | None,
        payload: dict,
        user_id: uuid.UUID,
    ) -> dict | None:
        """One dispatch table: the same calls the REST routers make."""
        from app.services.catalog.skills_service import SkillService
        from app.services.profile.experience_service import ExperienceService
        from app.services.profile.profile_entities_service import ProfileEntitiesService
        from app.services.profile.profile_service import ProfileService

        entity: Any = None
        if kind == ProposalKind.CV_SYNTH.value:
            return await self._apply_cv_synth(user_id, payload)
        if kind == ProposalKind.CV_SET_BULLETS.value:
            return await self._apply_cv_set_bullets(payload, user_id)
        if kind == ProposalKind.EXPERIENCE_ITEM.value:
            experience_service = ExperienceService(self.db)
            if action == ProposalAction.CREATE.value:
                entity = await experience_service.create_item(user_id, dict(payload))
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                entity = await experience_service.update_item(user_id, entity_id, dict(payload))
            else:
                assert entity_id is not None
                await experience_service.delete_item(user_id, entity_id)
        elif kind == ProposalKind.EDUCATION_ITEM.value:
            entities_service = ProfileEntitiesService(self.db)
            if action == ProposalAction.CREATE.value:
                entity = await entities_service.create_education(
                    user_id, EducationItemIn.model_validate(payload)
                )
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                entity = await entities_service.update_education(
                    entity_id, user_id, EducationItemPatch.model_validate(payload)
                )
            else:
                assert entity_id is not None
                await entities_service.delete_education(entity_id, user_id)
        elif kind == ProposalKind.CERTIFICATION.value:
            entities_service = ProfileEntitiesService(self.db)
            if action == ProposalAction.CREATE.value:
                entity = await entities_service.create_certification(
                    user_id, CertificationIn.model_validate(payload)
                )
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                entity = await entities_service.update_certification(
                    entity_id, user_id, CertificationPatch.model_validate(payload)
                )
            else:
                assert entity_id is not None
                await entities_service.delete_certification(entity_id, user_id)
        elif kind == ProposalKind.PROFILE_ACHIEVEMENT.value:
            entities_service = ProfileEntitiesService(self.db)
            if action == ProposalAction.CREATE.value:
                entity = await entities_service.create_achievement(
                    user_id, ProfileAchievementIn.model_validate(payload)
                )
            elif action == ProposalAction.UPDATE.value:
                assert entity_id is not None
                entity = await entities_service.update_achievement(
                    entity_id, user_id, ProfileAchievementPatch.model_validate(payload)
                )
            else:
                assert entity_id is not None
                await entities_service.delete_achievement(entity_id, user_id)
        elif kind == ProposalKind.USER_SKILL.value:
            skill_service = SkillService(self.db)
            if action == ProposalAction.CREATE.value:
                add = UserSkillAddIn.model_validate(payload)
                row = await skill_service.upsert_user_skill(
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
                await skill_service.delete_user_skill(user_id, row.skill_id)
        elif kind == ProposalKind.PROFILE_SECTION.value:
            section_patch = ProfileSectionPatchIn.model_validate(payload)
            profile_service = ProfileService(self.db)
            section_kwargs: dict[str, Any] = {section_patch.section: section_patch.value}
            entity = await profile_service.update(user_id, ProfileSectionUpdate(**section_kwargs))
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
        from app.services.cv.cv_service import CvService
        from app.services.cv.cv_synth_service import CvSynthService

        cv = await CvService(self.db).get_owned(uuid.UUID(str(payload["cv_id"])), user_id)
        source_key = payload["source_key"]
        item_id = payload["item_id"]
        pin_key = f"{source_key}:{item_id}"
        selection = CvContextSelection.model_validate(cv.context or {})
        service = CvSynthService(self.db)
        if payload.get("restore"):
            selection.synth_pins = {
                key: value for key, value in (selection.synth_pins or {}).items() if key != pin_key
            }
        else:
            bullets_payload = CvSynthPayload(
                achievements=[
                    CvSynthBullet(text=str(bullet)) for bullet in payload.get("bullets") or []
                ]
            )
            pinned_id = (selection.synth_pins or {}).get(pin_key)
            if pinned_id:
                # Plan 110: the pinned row keeps its other fields
                # (description/summary) — achievements are a field patch,
                # never a whole-payload clobber.
                merged = dict(
                    (await service.get_owned(uuid.UUID(str(pinned_id)), user_id)).payload or {}
                )
                merged["achievements"] = list(bullets_payload.achievements)
                await service.update(
                    uuid.UUID(str(pinned_id)),
                    user_id,
                    CvSynthItemUpdate(payload=CvSynthPayload.model_validate(merged)),
                )
            else:
                row = await service.create_manual(
                    user_id,
                    CvSynthItemCreate(
                        refs=[CvContextRef(source_key=source_key, item_id=item_id)],
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
        from app.services.cv.cv_synth_service import CvSynthService

        selection = CvContextSelection.model_validate(cv.context or {})
        pinned_id = (selection.synth_pins or {}).get(
            f"{payload.get('source_key')}:{payload.get('item_id')}"
        )
        entries = None
        if pinned_id:
            variant = await CvSynthService(self.db).get_owned(uuid.UUID(str(pinned_id)), cv.user_id)
            entries = (variant.payload or {}).get("achievements")
        before = [
            str(entry.get("text") or "") for entry in entries or [] if isinstance(entry, dict)
        ]
        after = [str(b) for b in payload.get("bullets") or []]
        # The card's diff contract is field/label/before/after rows with
        # structured [{text}] values (the HITL renderer draws chips).
        return [
            {
                "field": "bullets",
                "label": "Bullets",
                "before": [
                    {
                        "text": str(entry.get("text") or "")
                        if isinstance(entry, dict)
                        else str(entry)
                    }
                    for entry in before
                ],
                "after": [{"text": b} for b in after],
            }
        ]

    def _cv_bullets_label(self, payload: dict) -> str:
        return (
            f"Bullets of {payload.get('item_label') or 'item'} on {payload.get('cv_title') or 'CV'}"
        )

    def _cv_bullets_diff(self, payload: dict) -> list[dict]:
        before = [
            str(b.get("text") or "") if isinstance(b, dict) else str(b)
            for b in payload.get("before") or []
        ]
        after = [str(b) for b in payload.get("bullets") or []]
        # The card's diff contract: one structured row (chips both sides).
        return [
            {
                "field": "bullets",
                "label": "Bullets",
                "before": [{"text": b} for b in before],
                "after": [{"text": b} for b in after],
            }
        ]

    async def _load_entity(
        self,
        kind: str,
        user_id: uuid.UUID,
        entity_id: uuid.UUID | None,
    ) -> tuple[Any, datetime]:
        if kind == ProposalKind.USER_SKILL.value:
            if entity_id is None:
                raise NotFoundError("Target skill row not found")
            row = await self._owned_user_skill(user_id, entity_id)
            return row, row.updated_at
        if kind == ProposalKind.PROFILE_SECTION.value:
            profile = await self._load_profile(user_id)
            return profile, profile.updated_at
        if kind == ProposalKind.CV_SET_BULLETS.value:
            from app.services.cv.cv_service import CvService

            assert entity_id is not None
            cv = await CvService(self.db).get_owned(entity_id, user_id)
            return cv, cv.updated_at
        model: Any = KIND_SPECS[kind].model
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

    async def _owned_user_skill(self, user_id: uuid.UUID, row_id: uuid.UUID) -> UserSkill:
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
        from app.services.profile.profile_service import ProfileService

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
            "updated_at": (profile.updated_at.isoformat() if profile.updated_at else None),
            "content": getattr(profile, section, None),
            "note": "Exact current content — full-section replacement needs it.",
        }
