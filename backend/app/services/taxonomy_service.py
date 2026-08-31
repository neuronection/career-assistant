from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.career_path_model import CareerPathStep
from app.models.enums import InterestTagKind
from app.models.job_model import JobSkill, JobTag
from app.models.taxonomy_model import InterestTag, Skill
from app.models.user_model import Profile, UserInterest, UserSkill
from app.services.skills_service import SkillService


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

    async def create_skill(self, data: dict) -> Skill:
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

    async def update_skill(self, skill_id: UUID, data: dict) -> Skill:
        """Edit a skill (key immutable); lifecycle transitions via status."""
        skill = await self.db.get(Skill, skill_id)
        if skill is None:
            raise ValidationError("Skill not found")
        if "key" in data and data["key"] != skill.key:
            raise ValidationError("Skill keys are immutable")
        if "status" in data and data["status"] is not None:
            skill.status = SkillService.validate_status(data["status"])
        if "parent_id" in data and data["parent_id"] is not None:
            parent = await self.db.get(Skill, data["parent_id"])
            if parent is None:
                raise ValidationError("Parent skill not found")
            if parent.id == skill.id:
                raise ValidationError("A skill cannot be its own parent")
            ancestor = parent
            while ancestor.parent_id is not None:
                if ancestor.parent_id == skill.id:
                    raise ValidationError("Parent chain would create a cycle")
                ancestor = await self.db.get(Skill, ancestor.parent_id)
                if ancestor is None:
                    break
            skill.parent_id = data["parent_id"]
        if "aliases" in data and data["aliases"] is not None:
            skill.aliases = [str(a).strip() for a in data["aliases"] if str(a).strip()]
        if "level_anchors" in data and data["level_anchors"] is not None:
            anchors = []
            for anchor in data["level_anchors"]:
                level = int(anchor.get("level", 0))
                if not 1 <= level <= 10:
                    raise ValidationError("Anchor levels must be 1–10")
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
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

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
                select(func.count(UserInterest.id)).where(
                    UserInterest.interest_tag_id == tag.id
                )
            )
        ).scalar() or 0
        profile_refs = await self._profile_jsonb_refs(tag.key)
        total = job_refs + user_refs + profile_refs
        if total > 0:
            raise ReferenceCountError(job_refs, user_refs + profile_refs)
        await self.db.delete(tag)
        await self.db.commit()
        return {"deleted": tag.key}

    async def delete_skill(self, skill_id: UUID) -> dict:
        """Delete an unreferenced skill; report counts otherwise."""
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
            await self.db.execute(
                select(func.count(Skill.id)).where(Skill.parent_id == skill.id)
            )
        ).scalar() or 0
        step_refs = (
            await self.db.execute(
                select(func.count(CareerPathStep.id)).where(
                    CareerPathStep.skill_id == skill.id
                )
            )
        ).scalar() or 0
        total = job_refs + user_refs + child_refs + step_refs
        if total > 0:
            raise ReferenceCountError(job_refs, user_refs + child_refs + step_refs)
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
            select(Skill)
            .where(Skill.status == "proposed")
            .order_by(Skill.created_at.desc())
        )
        return list(rows.scalars().all())

    async def promote(self, skill_id: UUID) -> Skill:
        """proposed → active (admin decision; the only promotion path)."""
        skill = await self.db.get(Skill, skill_id)
        if skill is None:
            raise ValidationError("Skill not found")
        if skill.status != "proposed":
            raise ValidationError("Only proposed skills can be promoted")
        skill.status = "active"
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def merge(self, skill_id: UUID, target_id: UUID) -> Skill:
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
            (
                await self.db.execute(
                    select(JobSkill).where(JobSkill.skill_id == source.id)
                )
            )
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
            (
                await self.db.execute(
                    select(UserSkill).where(UserSkill.skill_id == source.id)
                )
            )
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
        await self.db.commit()
        await self.db.refresh(target)
        return target


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
