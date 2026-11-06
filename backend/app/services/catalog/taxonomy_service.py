from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, ValidationError
from app.models.career_path_model import CareerPathStep
from app.models.enums import (
    InterestTagKind,
    SkillChangeActor,
    SkillEventKind,
    SkillParentSource,
    SkillRelationStatus,
    SkillRelationType,
)
from app.models.job_model import JobSkill, JobTag
from app.models.taxonomy_model import InterestTag, Skill, SkillRelation
from app.models.user_model import Profile, UserInterest, UserSkill
from app.services.catalog.skill_change_journal import SkillChangeJournal
from app.services.catalog.skill_change_journal import snapshot as journal_snapshot
from app.services.catalog.skill_relations import assert_acyclic
from app.services.catalog.skills_service import SkillService


class TaxonomyService:
    """Read + admin management of controlled vocabularies."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def interests(
        self,
        category: str | None = None,
        *,
        kind: str | None = None,
        include_deprecated: bool = True,
    ) -> list[InterestTag]:
        """List interest tags, optionally filtered by category or kind."""
        query = select(InterestTag).order_by(InterestTag.category, InterestTag.label)
        if category:
            query = query.where(InterestTag.category == category)
        if kind:
            query = query.where(InterestTag.kind == kind)
        if not include_deprecated:
            query = query.where(InterestTag.deprecated.is_(False))
        return list((await self.db.execute(query)).scalars().all())

    async def skills(
        self,
        category: str | None = None,
        *,
        status: str | None = None,
    ) -> list[Skill]:
        """List skills; status=None returns every lifecycle row (admin)."""
        return await SkillService(self.db).list_skills(category=category, status=status)

    async def create_interest(self, data: dict) -> InterestTag:
        return await self._create(InterestTag, data)

    async def create_skill(self, data: dict, *, actor_ref: dict | None = None) -> Skill:
        key = (data.get("key") or "").strip()
        _require_slug(key)
        existing = await self.db.execute(select(Skill).where(Skill.key == key))
        if existing.scalars().first() is not None:
            raise ValidationError(f"Key already exists: {key}")
        skill = Skill(
            key=key,
            label=(data.get("label") or "").strip() or key,
            category=(data.get("category") or "general").strip(),
            description=data.get("description") or "",
            status="active",
            origin="bank",
        )
        self.db.add(skill)
        await self.db.flush()
        SkillChangeJournal.record(
            self.db,
            skill,
            SkillEventKind.CREATED,
            SkillChangeActor.ADMIN,
            actor_ref=actor_ref,
        )
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def _create(self, model, data: dict):
        key = (data.get("key") or "").strip()
        _require_slug(key)
        existing = await self.db.execute(select(model).where(model.key == key))
        if existing.scalars().first() is not None:
            raise ValidationError(f"Key already exists: {key}")
        tag = model(
            key=key,
            label=(data.get("label") or "").strip() or key,
            category=(data.get("category") or "general").strip(),
            description=data.get("description") or "",
            kind=data.get("kind") or InterestTagKind.TOPIC.value,
        )
        self.db.add(tag)
        await self.db.commit()
        await self.db.refresh(tag)
        return tag

    async def update_interest(self, tag_id, data: dict) -> InterestTag:
        return await self._update(InterestTag, tag_id, data)

    async def update_skill(
        self,
        skill_id: UUID,
        data: dict,
        *,
        only_if_parent_empty: bool = False,
        parent_source: SkillParentSource | None = SkillParentSource.CURATED,
        actor_ref: dict | None = None,
    ) -> Skill:
        """Edit a skill (key immutable); lifecycle transitions via status.

        A ``parent_id`` key present with ``None`` clears the parent back to
        the root (the documented undo); a key ABSENT from ``data`` never
        touches it. Every explicit parent write stamps placement
        provenance (``parent_source``, plan 139): ``CURATED`` for human
        callers (the default — a deliberate clear lands empty + curated,
        so the tree catch-up never re-fills it), ``LEARNED`` for the tree
        catch-up, and ``None`` to reset the slot to untouched (the seam's
        placement heal). The fill-only guard and the machine stamp are one
        contract: ``only_if_parent_empty`` holds exactly when
        ``parent_source`` is ``LEARNED`` — a mismatch in either direction
        is a programmer error (:class:`RuntimeError`, unreachable from the
        API — ``SkillUpdateIn`` never carries the field), never a client
        validation failure.

        The re-parent shares the seam's generality walk
        (:func:`assert_acyclic`) so a parent that would close a cycle
        through an approved ``is_a`` edge is refused — clearing cannot
        create a cycle and needs no guard. ``only_if_parent_empty``
        additionally guards the tree catch-up's fill-only contract at
        write time: BOTH the parent and its provenance are re-checked
        inside this transaction, so a parent filled — or a slot a human
        deliberately cleared — after the catch-up's snapshot is never
        overwritten (the backfill skips to its next candidate).
        """
        skill = await self.db.get(Skill, skill_id)
        if skill is None:
            raise ValidationError("Skill not found")
        before = journal_snapshot(skill)
        if "key" in data and data["key"] != skill.key:
            raise ValidationError("Skill keys are immutable")
        if "status" in data and data["status"] is not None:
            skill.status = SkillService.validate_status(data["status"])
        if "parent_id" in data:
            if only_if_parent_empty != (parent_source is SkillParentSource.LEARNED):
                raise RuntimeError(
                    "A guarded fill must stamp learned provenance, "
                    "and learned provenance must guard the fill"
                )
            if data["parent_id"] is None:
                skill.parent_id = None
                skill.parent_source = parent_source
            else:
                parent = await self.db.get(Skill, data["parent_id"])
                if parent is None:
                    raise ValidationError("Parent skill not found")
                if parent.id == skill.id:
                    raise ValidationError("A skill cannot be its own parent")
                try:
                    await assert_acyclic(self.db, skill.id, parent.id, SkillRelationType.IS_A)
                except ValidationError as exc:
                    raise ValidationError("Parent chain would create a cycle") from exc
                if only_if_parent_empty:
                    current = (
                        await self.db.execute(
                            select(Skill.parent_id, Skill.parent_source).where(Skill.id == skill.id)
                        )
                    ).one()
                    if current.parent_id is not None:
                        raise ValidationError("Parent is already set")
                    if current.parent_source is not None:
                        raise ValidationError("Parent slot is already stamped")
                skill.parent_id = data["parent_id"]
                skill.parent_source = parent_source
        if "aliases" in data and data["aliases"] is not None:
            skill.aliases = [str(a).strip() for a in data["aliases"] if str(a).strip()]
        if "level_anchors" in data and data["level_anchors"] is not None:
            anchors: list[dict[str, Any]] = []
            for anchor in data["level_anchors"]:
                level = int(anchor.get("level", 0))
                if not 1 <= level <= 10:
                    raise ValidationError("Anchor levels must be 1-10")
                anchors.append(
                    {
                        "level": level,
                        "label": str(anchor.get("label") or "")[:60],
                        "description": str(anchor.get("description") or "")[:300],
                    }
                )
            anchors.sort(key=lambda a: a["level"])
            skill.level_anchors = anchors
        for field in ("label", "category", "description"):
            if field in data and data[field] is not None:
                setattr(skill, field, data[field])
        SkillChangeJournal.record_snapshot_change(
            self.db,
            skill,
            before,
            journal_snapshot(skill),
            _transition_event(before.get("status"), skill.status),
            _update_actor(parent_source),
            actor_ref=actor_ref,
        )
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def heal_learned_placement(self, skill_id: UUID) -> None:
        """Re-derive a ``learned`` tree placement from surviving support.

        The edge seam calls this after removing or rejecting an ``is_a``
        row (the evidence changed; plan 139 decision 4). A ``learned``
        placement whose parent still has an approved ``is_a`` row keeps
        it — the tri-state stamp records no row identity, so "re-stamp
        from the new winner" is a value no-op and nothing is written.
        Without support the placement clears back to untouched (empty +
        ``NULL``) through :meth:`update_skill`, so the next catch-up pass
        may re-fill it from the next-best edge. ``curated`` and
        pre-provenance (``NULL``) placements are never touched.
        """
        skill = await self.db.get(Skill, skill_id)
        if skill is None or skill.parent_id is None:
            return
        if skill.parent_source != SkillParentSource.LEARNED:
            return
        support = await self.db.execute(
            select(SkillRelation.id).where(
                SkillRelation.from_skill_id == skill.id,
                SkillRelation.to_skill_id == skill.parent_id,
                SkillRelation.relation == SkillRelationType.IS_A.value,
                SkillRelation.status == SkillRelationStatus.APPROVED.value,
            )
        )
        if support.first() is not None:
            return
        await self.update_skill(skill.id, {"parent_id": None}, parent_source=None)

    async def _update(self, model, tag_id, data: dict):
        tag = await self.db.get(model, tag_id)
        if tag is None:
            raise ValidationError("Tag not found")
        if "key" in data and data["key"] != tag.key:
            raise ValidationError("Tag keys are immutable")
        for field in ("label", "category", "description", "deprecated", "kind"):
            if field in data and data[field] is not None:
                setattr(tag, field, data[field])
        await self.db.commit()
        await self.db.refresh(tag)
        return tag

    async def delete_interest(self, tag_id) -> dict:
        """Delete an unreferenced interest tag; 409-style report otherwise."""
        tag = await self.db.get(InterestTag, tag_id)
        if tag is None:
            raise ValidationError("Tag not found")
        job_refs = (
            await self.db.execute(
                select(func.count(JobTag.id)).where(JobTag.interest_tag_id == tag.id)
            )
        ).scalar() or 0
        user_refs = (
            await self.db.execute(
                select(func.count(UserInterest.id)).where(UserInterest.interest_tag_id == tag.id)
            )
        ).scalar() or 0
        profile_refs = await self._profile_jsonb_refs(tag.key)
        total = job_refs + user_refs + profile_refs
        if total > 0:
            raise ReferenceCountError(job_refs, user_refs + profile_refs)
        await self.db.delete(tag)
        await self.db.commit()
        return {"deleted": tag.key}

    async def delete_skill(self, skill_id: UUID, *, actor_ref: dict | None = None) -> dict:
        """Delete an unreferenced skill; report counts otherwise.

        The ``deleted`` journal row lands (flushed) BEFORE the delete so
        its FK insert sees the live row — ``ON DELETE SET NULL`` then
        detaches it in the same transaction, key/label snapshots kept.
        """
        skill = await self.db.get(Skill, skill_id)
        if skill is None:
            raise ValidationError("Skill not found")
        job_refs = (
            await self.db.execute(
                select(func.count(JobSkill.id)).where(JobSkill.skill_id == skill.id)
            )
        ).scalar() or 0
        user_refs = (
            await self.db.execute(
                select(func.count(UserSkill.id)).where(UserSkill.skill_id == skill.id)
            )
        ).scalar() or 0
        child_refs = (
            await self.db.execute(select(func.count(Skill.id)).where(Skill.parent_id == skill.id))
        ).scalar() or 0
        step_refs = (
            await self.db.execute(
                select(func.count(CareerPathStep.id)).where(CareerPathStep.skill_id == skill.id)
            )
        ).scalar() or 0
        total = job_refs + user_refs + child_refs + step_refs
        if total > 0:
            raise ReferenceCountError(job_refs, user_refs + child_refs + step_refs)
        SkillChangeJournal.record(
            self.db,
            skill,
            SkillEventKind.DELETED,
            SkillChangeActor.ADMIN,
            actor_ref=actor_ref,
        )
        await self.db.flush()
        await self.db.delete(skill)
        await self.db.commit()
        return {"deleted": skill.key}

    async def _profile_jsonb_refs(self, key: str) -> int:
        """likes/dislikes/aspirations still embed tag keys as display detail."""
        refs = 0
        profiles = (await self.db.execute(select(Profile))).scalars().all()
        for profile in profiles:
            import json

            blob = json.dumps(
                {
                    "likes": profile.likes,
                    "dislikes": profile.dislikes,
                    "aspirations": profile.aspirations,
                }
            )
            if f'"{key}"' in blob:
                refs += 1
        return refs

    async def proposals(self) -> list[Skill]:
        """All proposed skills awaiting promotion (admin queue)."""
        rows = await self.db.execute(
            select(Skill).where(Skill.status == "proposed").order_by(Skill.created_at.desc())
        )
        return list(rows.scalars().all())

    async def promote(
        self,
        skill_id: UUID,
        *,
        auto: bool = False,
        detail: dict | None = None,
        actor_ref: dict | None = None,
    ) -> Skill:
        """proposed → active (admin decision; the only promotion path).

        ``auto=True`` is the plan-147 corroboration gate's ride: the same
        seam journals ``auto_promoted`` (with the corroboration counts as
        ``detail``) instead of ``promoted`` — one seam, no double rows.
        """
        skill = await self.db.get(Skill, skill_id)
        if skill is None:
            raise ValidationError("Skill not found")
        if skill.status != "proposed":
            raise ValidationError("Only proposed skills can be promoted")
        skill.status = "active"
        SkillChangeJournal.record(
            self.db,
            skill,
            SkillEventKind.AUTO_PROMOTED if auto else SkillEventKind.PROMOTED,
            SkillChangeActor.JOB if auto else SkillChangeActor.ADMIN,
            actor_ref=actor_ref,
            detail=detail,
        )
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def merge(
        self, skill_id: UUID, target_id: UUID, *, actor_ref: dict | None = None
    ) -> Skill:
        """Merge a duplicate into the surviving skill (no orphan references).

        Alias redirect: the source key/label/aliases become target aliases;
        join rows are rewritten (conflicts collapse onto the target row);
        the source row is deprecated — never deleted.
        """
        source = await self.db.get(Skill, skill_id)
        target = await self.db.get(Skill, target_id)
        if source is None or target is None:
            raise ValidationError("Skill not found")
        if source.id == target.id:
            raise ValidationError("Cannot merge a skill into itself")
        if target.status != "active":
            raise ValidationError("Merge target must be an active skill")

        for link in (
            (await self.db.execute(select(JobSkill).where(JobSkill.skill_id == source.id)))
            .scalars()
            .all()
        ):
            conflict = (
                await self.db.execute(
                    select(JobSkill.id).where(
                        JobSkill.job_id == link.job_id,
                        JobSkill.skill_id == target.id,
                    )
                )
            ).scalar_one_or_none()
            if conflict is not None:
                await self.db.delete(link)
            else:
                link.skill_id = target.id
        for row in (
            (await self.db.execute(select(UserSkill).where(UserSkill.skill_id == source.id)))
            .scalars()
            .all()
        ):
            conflict = (
                await self.db.execute(
                    select(UserSkill.id).where(
                        UserSkill.user_id == row.user_id,
                        UserSkill.skill_id == target.id,
                    )
                )
            ).scalar_one_or_none()
            if conflict is not None:
                await self.db.delete(row)
            else:
                row.skill_id = target.id
        await self.db.execute(
            update(CareerPathStep)
            .where(CareerPathStep.skill_id == source.id)
            .values(skill_id=target.id)
        )

        aliases = list(target.aliases or [])
        for candidate in (source.key, source.label, *(source.aliases or [])):
            if candidate and candidate not in aliases:
                aliases.append(str(candidate))
        target.aliases = aliases
        source.status = "deprecated"
        source.provenance = {
            **(source.provenance or {}),
            "merged_into": str(target.id),
        }
        SkillChangeJournal.record(
            self.db,
            source,
            SkillEventKind.MERGED,
            SkillChangeActor.ADMIN,
            actor_ref=actor_ref,
            detail={"merged_into": target.key, "target_id": str(target.id)},
        )
        SkillChangeJournal.record(
            self.db,
            target,
            SkillEventKind.MERGED,
            SkillChangeActor.ADMIN,
            actor_ref=actor_ref,
            detail={"absorbed": source.key},
        )
        await self.db.commit()
        await self.db.refresh(target)
        return target

    async def bulk_skills(
        self,
        ids: list[UUID],
        action: str,
        target_id: UUID | None = None,
        *,
        actor_ref: dict | None = None,
    ) -> dict:
        """One lifecycle action over many skills, per-item seams preserved.

        Each id rides the same seam as its single-row action (promote /
        update_skill / delete_skill / merge) so validation semantics never
        drift; a seam refusal (wrong status, references, unknown id) is
        collected as a failure row instead of failing the whole call.
        """
        affected: list[UUID] = []
        failed: list[dict] = []
        for skill_id in ids:
            skill = await self.db.get(Skill, skill_id)
            key = skill.key if skill is not None else ""
            before = skill.status if skill is not None else None
            try:
                if action == "promote":
                    await self.promote(skill_id, actor_ref=actor_ref)
                elif action == "deprecate":
                    await self.update_skill(skill_id, {"status": "deprecated"}, actor_ref=actor_ref)
                elif action == "restore":
                    await self.update_skill(skill_id, {"status": "active"}, actor_ref=actor_ref)
                elif action == "delete":
                    await self.delete_skill(skill_id, actor_ref=actor_ref)
                elif action == "merge":
                    if target_id is None:  # pragma: no cover - schema-enforced
                        raise ValidationError("target_id is required for merge")
                    await self.merge(skill_id, target_id, actor_ref=actor_ref)
                else:
                    raise ValidationError(f"Unknown bulk action: {action}")
            except ReferenceCountError as exc:
                failed.append(
                    {
                        "id": str(skill_id),
                        "key": key,
                        "reason": str(exc),
                        "job_refs": exc.job_refs,
                        "profile_refs": exc.profile_refs,
                    }
                )
            except DomainError as exc:
                failed.append({"id": str(skill_id), "key": key, "reason": str(exc)})
            else:
                # deprecate/restore of a row already in that state is a no-op
                # write, not a transition — count only real changes
                if action in ("deprecate", "restore") and before == cast(Skill, skill).status:
                    continue
                affected.append(skill_id)
        return {"affected": affected, "failed": failed}


def _transition_event(before_status: str | None, after_status: str | None) -> SkillEventKind:
    """The lifecycle event a status transition names; plain ``updated``
    when the status did not move (the diff rides ``detail`` either way)."""
    if before_status != after_status:
        if after_status == "deprecated":
            return SkillEventKind.DEPRECATED
        if before_status == "deprecated" and after_status == "active":
            return SkillEventKind.RESTORED
        if before_status == "proposed" and after_status == "active":
            return SkillEventKind.PROMOTED
    return SkillEventKind.UPDATED


def _update_actor(parent_source: SkillParentSource | None) -> SkillChangeActor:
    """Machine tree-maintenance writes journal as ``system`` (the
    catch-up's learned fill and the placement heal); every other
    ``update_skill`` caller is the admin surface."""
    if parent_source in (None, SkillParentSource.LEARNED):
        return SkillChangeActor.SYSTEM
    return SkillChangeActor.ADMIN


class ReferenceCountError(ValidationError):
    """Tag is still referenced; deprecate instead of deleting."""

    def __init__(self, job_refs: int, profile_refs: int):
        self.job_refs = job_refs
        self.profile_refs = profile_refs
        super().__init__(
            f"Tag is referenced by {job_refs} job(s) and {profile_refs} profile "
            "entries — deprecate it instead of deleting"
        )


def _require_slug(key: str) -> None:
    import re

    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", key):
        raise ValidationError("Key must be a lowercase slug (letters, digits, hyphens)")
    if len(key) > 80:
        raise ValidationError("Key too long (max 80)")
