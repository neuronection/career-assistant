"""Skill ontology: browse, resolve, propose (lifecycle), user skills + gaps."""

from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select
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


_PROPOSAL_ACTOR: dict[str, str] = {
    "bank": "system",
    "import": "sync",
    "ai": "job",
    "cv_parse": "job",
    "user": "user",
}


def _proposal_actor(origin: SkillOrigin) -> str:
    """Who a proposal creation is attributed to, by its origin (plan 148)."""
    return _PROPOSAL_ACTOR.get(
        origin.value if isinstance(origin, SkillOrigin) else str(origin), "system"
    )


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
        """Resolve a key, accepting display aliases (case-insensitive).

        A deprecated row never shadows a live skill: when the key belongs
        to a merged-away label row, the alias scan finds the surviving
        skill whose alias now carries the label (decision 6's matcher
        contract), and only then does the deprecated exact-key hit answer.
        """
        exact = await self.get_by_key(key.strip())
        if exact is not None and exact.status != SkillStatus.DEPRECATED.value:
            return exact
        rows = await self.db.execute(select(Skill))
        for candidate in rows.scalars().all():
            if candidate.status == SkillStatus.DEPRECATED.value:
                continue
            haystack = {
                _norm(candidate.label),
                *(_norm(a) for a in candidate.aliases or []),
            }
            if _norm(key) in haystack:
                return candidate
        return exact

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
        from app.models.enums import SkillEventKind
        from app.services.catalog.skill_change_journal import SkillChangeJournal

        SkillChangeJournal.record(
            self.db,
            skill,
            SkillEventKind.CREATED,
            _proposal_actor(origin),
        )
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

    async def stats(self, skill: Skill) -> dict:
        """The skill page's aggregate block (plan 148), three bounded
        round-trips, no per-row queries.

        ``demand_*`` counts the SAME universe the positions endpoint
        lists (postings with a `posting_skills` row, hidden excluded), so
        the number always matches the list under it; ``corroboration``
        reads the plan-147 provenance (origin + distinct corroborating
        postings) for ai-origin rows only.
        """
        from app.models.posting_model import JobPosting, PostingSkill
        from app.models.user_model import UserSkill as UserSkillRow

        demand = await self.db.execute(
            select(
                func.count(JobPosting.id),
                func.avg(PostingSkill.required_level),
                func.min(func.coalesce(JobPosting.posted_at, JobPosting.created_at)),
                func.max(func.coalesce(JobPosting.posted_at, JobPosting.created_at)),
            )
            .select_from(PostingSkill)
            .join(JobPosting, JobPosting.id == PostingSkill.posting_id)
            .where(PostingSkill.skill_id == skill.id, JobPosting.status != "hidden")
        )
        demand_count, avg_level, first_seen, last_seen = demand.one()
        histogram_rows = await self.db.execute(
            select(PostingSkill.required_level, func.count(PostingSkill.posting_id))
            .join(JobPosting, JobPosting.id == PostingSkill.posting_id)
            .where(
                PostingSkill.skill_id == skill.id,
                JobPosting.status != "hidden",
                PostingSkill.required_level.is_not(None),
            )
            .group_by(PostingSkill.required_level)
            .order_by(PostingSkill.required_level)
        )
        histogram = [
            {"level": level, "n": n} for level, n in histogram_rows.all() if level is not None
        ]
        user_count = (
            await self.db.execute(
                select(func.count(UserSkillRow.id)).where(
                    UserSkillRow.skill_id == skill.id, UserSkillRow.hidden.is_(False)
                )
            )
        ).scalar_one()

        provenance = skill.provenance or {}
        corroboration = None
        if skill.origin == SkillOrigin.AI.value:
            origin = provenance.get("posting_id")
            seen = provenance.get("corroborated_postings") or []
            distinct = len({origin, *seen}) if origin else len(seen)
            if distinct:
                corroboration = {"postings": distinct}

        return {
            "demand_count": demand_count,
            "level_histogram": histogram,
            "avg_required_level": round(float(avg_level), 1) if avg_level is not None else None,
            "user_count": user_count,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "corroboration": corroboration,
        }

    async def user_skills(self, user_id: UUID) -> list[UserSkill]:
        rows = await self.db.execute(
            select(UserSkill)
            .options(selectinload(UserSkill.skill))
            .where(UserSkill.user_id == user_id, UserSkill.hidden.is_(False))
            .order_by(UserSkill.level.desc())
        )
        return list(rows.scalars().all())

    async def put_user_skills(self, user_id: UUID, items: list[dict]) -> list[UserSkill]:
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
                UserSkill.skill_id.not_in(keys) if keys else True,  # type: ignore[arg-type]
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
            row.derive_enabled = True
            row.hidden = False
        await self.db.commit()
        return await self.user_skills(user_id)

    async def upsert_user_skill(
        self,
        user_id: UUID,
        skill_key: str,
        level: int,
        confidence: float = 1.0,
    ) -> UserSkill:
        """Add or update ONE self_report row (chat/HITL path — never wipes
        the user's other skills the way ``put_user_skills`` does)."""
        skill, _created = await self.propose(
            skill_key,
            origin=SkillOrigin.USER,
            provenance={"via": "chat_proposal"},
        )
        rows = await self.db.execute(
            select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.skill_id == skill.id)
        )
        row = rows.scalars().first()
        if row is None:
            row = UserSkill(user_id=user_id, skill_id=skill.id)
            self.db.add(row)
        row.level = int(level)
        row.confidence = float(confidence)
        row.source = "self_report"
        row.derive_enabled = True
        row.hidden = False
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def set_derive_enabled(
        self, user_id: UUID, skill_id: UUID, derive_enabled: bool
    ) -> UserSkill:
        """Toggle the derivation opt-out flag on one of the user's rows."""
        rows = await self.db.execute(
            select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.skill_id == skill_id)
        )
        row = rows.scalars().first()
        if row is None:
            await self.db.rollback()
            raise NotFoundError(f"Skill {skill_id} is not on the profile")
        row.derive_enabled = derive_enabled
        await self.db.commit()
        for candidate in await self.user_skills(user_id):
            if candidate.skill_id == row.skill_id:
                return candidate
        return row

    async def delete_user_skill(self, user_id: UUID, skill_id: UUID) -> None:
        """Tombstone one row: hidden from every surface, derivation
        never re-creates it. Re-adding the skill makes a fresh row."""
        rows = await self.db.execute(
            select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.skill_id == skill_id)
        )
        row = rows.scalars().first()
        if row is None:
            await self.db.rollback()
            raise NotFoundError(f"Skill {skill_id} is not on the profile")
        row.hidden = True
        row.derive_enabled = False
        await self.db.commit()

    async def gaps(self, user_id: UUID, job: Job) -> dict:
        """Required vs current per job skill + a suggested next step."""
        hints = await self._path_hints(job.id)
        mine = {
            row.skill_id: row.level for row in await self.user_skills(user_id) if row.derive_enabled
        }
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
            hints.setdefault(cast(UUID, step.skill_id), step.label or step.education_level or "")
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
