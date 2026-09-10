"""Skill ontology: browse, resolve, propose (lifecycle), user skills + gaps."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationError
from app.models.career_path_model import CareerPath, CareerPathStep
from app.models.enums import JobSkillImportance, SkillOrigin, SkillStatus
from app.models.job_model import Job, JobSkill
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill


def _norm(value: str) -> str:
    return (value or "").strip().lower()


class SkillService:
    """Read/browse of the ontology + the proposed→active lifecycle."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_skills(
        self,
        *,
        q: str | None = None,
        category: str | None = None,
        status: str | None = SkillStatus.ACTIVE.value,
    ) -> list[Skill]:
        """Flat listing; status=None returns every lifecycle row (admin)."""
        query = select(Skill).order_by(Skill.category, Skill.label)
        if category:
            query = query.where(Skill.category == category)
        if status:
            query = query.where(Skill.status == status)
        if q:
            pattern = f"%{q.strip()}%"
            query = query.where(
                Skill.key.ilike(pattern)
                | Skill.label.ilike(pattern)
                | Skill.description.ilike(pattern)
            )
        return list((await self.db.execute(query)).scalars().all())

    async def get_by_key(self, key: str) -> Skill | None:
        rows = await self.db.execute(select(Skill).where(Skill.key == key))
        return rows.scalars().first()

    async def require_skill(self, key: str) -> Skill:
        skill = await self.get_by_key(key)
        if skill is None:
            raise NotFoundError(f"Unknown skill key: {key}")
        return skill

    async def resolve(self, key: str) -> Skill | None:
        """Resolve a key, accepting display aliases (case-insensitive)."""
        skill = await self.get_by_key(key.strip())
        if skill is not None:
            return skill
        rows = await self.db.execute(select(Skill))
        for candidate in rows.scalars().all():
            haystack = {
                _norm(candidate.label),
                *(_norm(a) for a in candidate.aliases or []),
            }
            if _norm(key) in haystack:
                return candidate
        return None

    async def propose(
        self,
        key: str,
        *,
        label: str = "",
        origin: SkillOrigin = SkillOrigin.USER,
        provenance: dict | None = None,
        category: str = "general",
        description: str = "",
    ) -> tuple[Skill, bool]:
        """Return (skill, created). Unknown keys become `proposed` rows.

        Dedup at proposal time: an exact key match or a normalized
        label/alias match resolves to the existing row — no duplicates.
        """
        existing = await self.resolve(key)
        if existing is not None:
            return existing, False
        skill = Skill(
            key=key.strip().lower(),
            label=(label or key).strip()[:120],
            category=category,
            description=description[:500],
            status=SkillStatus.PROPOSED.value,
            origin=origin.value,
            provenance=provenance,
        )
        self.db.add(skill)
        await self.db.flush()
        return skill, True

    async def jobs_for_skill(self, skill: Skill) -> list[JobSkill]:
        """Published jobs asking for this skill (with requirement detail)."""
        rows = await self.db.execute(
            select(JobSkill)
            .join(Job, Job.id == JobSkill.job_id)
            .where(JobSkill.skill_id == skill.id, Job.status == "published")
            .order_by(JobSkill.required_level.desc())
            .limit(20)
        )
        return list(rows.scalars().all())

    async def user_skills(self, user_id: UUID) -> list[UserSkill]:
        rows = await self.db.execute(
            select(UserSkill)
            .options(selectinload(UserSkill.skill))
            .where(UserSkill.user_id == user_id)
            .order_by(UserSkill.level.desc())
        )
        return list(rows.scalars().all())

    async def put_user_skills(
        self, user_id: UUID, items: list[dict]
    ) -> list[UserSkill]:
        """Replace the caller's self_report rows; other sources untouched."""
        resolved: list[tuple[Skill, dict]] = []
        for item in items:
            skill, _created = await self.propose(
                item["skill_key"],
                origin=SkillOrigin.USER,
                provenance={"via": "self_report"},
            )
            resolved.append((skill, item))
        keys = [skill.id for skill, _ in resolved]
        await self.db.execute(
            delete(UserSkill).where(
                UserSkill.user_id == user_id,
                UserSkill.source == "self_report",
                UserSkill.skill_id.not_in(keys) if keys else True,
            )
        )
        for skill, item in resolved:
            existing = await self.db.execute(
                select(UserSkill).where(
                    UserSkill.user_id == user_id, UserSkill.skill_id == skill.id
                )
            )
            row = existing.scalars().first()
            if row is None:
                row = UserSkill(user_id=user_id, skill_id=skill.id)
                self.db.add(row)
            row.level = int(item["level"])
            row.confidence = float(item.get("confidence", 1.0))
            row.source = "self_report"
        await self.db.commit()
        return await self.user_skills(user_id)

    async def gaps(self, user_id: UUID, job: Job) -> dict:
        """Required vs current per job skill + a suggested next step."""
        hints = await self._path_hints(job.id)
        mine = {row.skill_id: row.level for row in await self.user_skills(user_id)}
        gaps = []
        for link in sorted(
            job.skill_links,
            key=lambda item: (
                JobSkillImportance(item.importance) is not JobSkillImportance.CORE,
                -item.required_level,
            ),
        ):
            user_level = mine.get(link.skill_id)
            delta = user_level - link.required_level if user_level is not None else None
            gaps.append(
                {
                    "skill_id": link.skill_id,
                    "key": link.skill.key,
                    "label": link.skill.label,
                    "required_level": link.required_level,
                    "importance": link.importance,
                    "user_level": user_level,
                    "delta": delta,
                    "suggestion": self._suggestion(link, user_level),
                    "next_step": hints.get(link.skill_id),
                }
            )
        return {
            "job_id": job.id,
            "job_code": job.code,
            "job_title": job.title,
            "gaps": gaps,
        }

    async def _path_hints(self, job_id: UUID) -> dict[UUID, str]:
        """Certification/education step labels from published paths, per skill."""
        rows = await self.db.execute(
            select(CareerPathStep)
            .join(CareerPath, CareerPath.id == CareerPathStep.path_id)
            .where(
                CareerPath.job_id == job_id,
                CareerPath.status == "published",
                CareerPathStep.kind.in_(("certification", "education")),
                CareerPathStep.skill_id.is_not(None),
            )
        )
        hints: dict[UUID, str] = {}
        for step in rows.scalars().all():
            hints.setdefault(step.skill_id, step.label or step.education_level or "")
        return hints

    @staticmethod
    def _suggestion(link: JobSkill, user_level: int | None) -> str:
        required = link.required_level
        label = link.skill.label
        if user_level is None:
            return f"Start building {label} — target level {required}/10"
        if user_level < required:
            return f"Close the gap in {label}: level {user_level} → {required}"
        return f"Meets the {label} requirement ({user_level}/10)"

    @staticmethod
    def validate_status(value: str) -> str:
        statuses = {s.value for s in SkillStatus}
        if value not in statuses:
            raise ValidationError(f"status must be one of {sorted(statuses)}")
        return value
