"""CV-data profile entity service: CRUD + readiness.

The readiness meter is a deterministic, section-coverage score over the
CV-relevant profile surface — no AI, no gamification: each section has a
weight and a completeness rule, and the report lists exactly what's
missing so the builder (47) and progressive nudges (36) can act on it.
"""

import uuid

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import EducationLevelOrder
from app.models.experience_model import ExperienceItem
from app.models.profile_entities_model import (
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.university_model import Department, University
from app.models.user_model import Profile, UserInterest, UserSkill
from app.schemas.profile_entities import (
    CertificationIn,
    CertificationPatch,
    CvReadiness,
    EducationItemIn,
    EducationItemPatch,
    ProfileAchievementIn,
    ProfileAchievementPatch,
    ReadinessSection,
)

_LEVEL_RANK = {level.value: rank for level, rank in EducationLevelOrder.ORDER.items()}

_EDUCATION_CLEARABLE = frozenset(
    {"university_id", "department_id", "grade_band", "start", "end"}
)

_CERTIFICATION_CLEARABLE = frozenset({"issued", "expires", "language_code"})


async def effective_education_level(
    db: AsyncSession,
    user_id: uuid.UUID,
    basics_level: str | None = None,
) -> str:
    """Highest education signal: basics select vs active education items.

    Order-based max over both sources; legacy/unknown item levels are
    ignored. Falls back to ``high_school`` when nothing is known — the
    same default the fit engine used before derivation existed.
    """
    rows = await db.execute(
        select(EducationItem.level).where(
            EducationItem.user_id == user_id,
            EducationItem.status == "active",
        )
    )
    candidates = [basics_level, *[level for (level,) in rows.all()]]
    known = [c for c in candidates if c in _LEVEL_RANK]
    if not known:
        return "high_school"
    return max(known, key=_LEVEL_RANK.__getitem__)


def _apply_patch(
    obj, patch: BaseModel, clearable: frozenset[str] = frozenset()
) -> None:
    """Apply a patch; explicit ``null`` clears only the given fields."""
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is None and field not in clearable:
            continue
        setattr(obj, field, value)


class ProfileEntitiesService:
    """CRUD for the CV-data entities + the readiness report."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------- education

    async def list_education(self, user_id: uuid.UUID) -> list[EducationItem]:
        rows = await self.db.execute(
            select(EducationItem)
            .where(EducationItem.user_id == user_id)
            .order_by(EducationItem.start.desc().nulls_last())
        )
        return list(rows.scalars().all())

    async def _validate_catalog_refs(
        self,
        university_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        """Catalog FKs must exist and agree; a department implies its
        university. Returns the resolved university id."""
        if department_id is not None:
            department = await self.db.get(Department, department_id)
            if department is None:
                raise NotFoundError("Department not found")
            if university_id is None:
                university_id = department.university_id
            elif department.university_id != university_id:
                raise ValidationError(
                    "Department does not belong to the selected university"
                )
        if university_id is not None:
            if await self.db.get(University, university_id) is None:
                raise NotFoundError("University not found")
        return university_id

    async def create_education(
        self, user_id: uuid.UUID, payload: EducationItemIn
    ) -> EducationItem:
        university_id = await self._validate_catalog_refs(
            payload.university_id, payload.department_id
        )
        item = EducationItem(user_id=user_id, **payload.model_dump())
        item.university_id = university_id
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def _owned(self, model, item_id: uuid.UUID, user_id: uuid.UUID):
        rows = await self.db.execute(
            select(model).where(model.id == item_id, model.user_id == user_id)
        )
        item = rows.scalars().first()
        if item is None:
            raise NotFoundError("Item not found")
        return item

    async def update_education(
        self, item_id: uuid.UUID, user_id: uuid.UUID, patch: EducationItemPatch
    ) -> EducationItem:
        item = await self._owned(EducationItem, item_id, user_id)
        data = patch.model_dump(exclude_unset=True)
        university_id = await self._validate_catalog_refs(
            data.get("university_id", item.university_id),
            data.get("department_id", item.department_id),
        )
        _apply_patch(item, patch, clearable=_EDUCATION_CLEARABLE)
        if "department_id" in data and "university_id" not in data:
            item.university_id = university_id
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete_education(self, item_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self.db.delete(await self._owned(EducationItem, item_id, user_id))
        await self.db.commit()

    # -------------------------------------------------- certifications

    async def list_certifications(self, user_id: uuid.UUID) -> list[Certification]:
        rows = await self.db.execute(
            select(Certification)
            .where(Certification.user_id == user_id)
            .order_by(Certification.issued.desc().nulls_last())
        )
        return list(rows.scalars().all())

    async def create_certification(
        self, user_id: uuid.UUID, payload: CertificationIn
    ) -> Certification:
        item = Certification(user_id=user_id, **payload.model_dump())
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update_certification(
        self, item_id: uuid.UUID, user_id: uuid.UUID, patch: CertificationPatch
    ) -> Certification:
        item = await self._owned(Certification, item_id, user_id)
        _apply_patch(item, patch, clearable=_CERTIFICATION_CLEARABLE)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete_certification(
        self, item_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        await self.db.delete(await self._owned(Certification, item_id, user_id))
        await self.db.commit()

    # ---------------------------------------------------- achievements

    async def list_achievements(self, user_id: uuid.UUID) -> list[ProfileAchievement]:
        rows = await self.db.execute(
            select(ProfileAchievement)
            .where(ProfileAchievement.user_id == user_id)
            .order_by(ProfileAchievement.date.desc().nulls_last())
        )
        return list(rows.scalars().all())

    async def create_achievement(
        self, user_id: uuid.UUID, payload: ProfileAchievementIn
    ) -> ProfileAchievement:
        item = ProfileAchievement(user_id=user_id, **payload.model_dump())
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update_achievement(
        self, item_id: uuid.UUID, user_id: uuid.UUID, patch: ProfileAchievementPatch
    ) -> ProfileAchievement:
        item = await self._owned(ProfileAchievement, item_id, user_id)
        _apply_patch(item, patch)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete_achievement(self, item_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self.db.delete(await self._owned(ProfileAchievement, item_id, user_id))
        await self.db.commit()

    # ------------------------------------------------------- readiness

    async def readiness(self, user_id: uuid.UUID) -> CvReadiness:
        """Deterministic section-coverage score."""
        rows = await self.db.execute(select(Profile).where(Profile.user_id == user_id))
        basics = rows.scalars().first()
        basics_data = (basics.basics if basics else None) or {}
        contact_missing = [
            label
            for label, key in (
                ("email", "email"),
                ("phone", "phone"),
                ("location", "city"),
            )
            if not basics_data.get(key)
        ]
        if not (basics_data.get("links") or []):
            contact_missing.append("a profile link (portfolio/github/linkedin)")
        if not basics_data.get("headline"):
            contact_missing.append("a professional headline")

        sections: list[ReadinessSection] = []
        sections.append(
            self._coverage_section(
                "contact",
                "Contact & headline",
                15,
                contact_missing,
            )
        )

        education_count = await self._count(EducationItem, user_id)
        sections.append(
            ReadinessSection(
                key="education",
                label="Education",
                weight=15,
                score=15 if education_count else 0,
                complete=bool(education_count),
                missing=[] if education_count else ["at least one education entry"],
            )
        )

        experience_count = (
            await self.db.execute(
                select(func.count())
                .select_from(ExperienceItem)
                .where(
                    ExperienceItem.user_id == user_id,
                    ExperienceItem.status == "active",
                )
            )
        ).scalar_one()
        sections.append(
            ReadinessSection(
                key="experience",
                label="Experience",
                weight=25,
                score=25 if experience_count else 0,
                complete=bool(experience_count),
                missing=[] if experience_count else ["at least one experience item"],
            )
        )

        user_skills_count = (
            await self.db.execute(
                select(func.count())
                .select_from(UserSkill)
                .where(UserSkill.user_id == user_id)
            )
        ).scalar_one()
        skills_missing = (
            [] if user_skills_count >= 3 else [f"{3 - user_skills_count} more skill(s)"]
        )
        sections.append(
            ReadinessSection(
                key="skills",
                label="Skills",
                weight=20,
                score=min(20, user_skills_count * 7),
                complete=user_skills_count >= 3,
                missing=skills_missing,
            )
        )

        languages_count = len(
            ((basics.academics if basics else None) or {}).get("languages") or []
        )
        sections.append(
            ReadinessSection(
                key="languages",
                label="Languages",
                weight=5,
                score=5 if languages_count else 0,
                complete=bool(languages_count),
                missing=[] if languages_count else ["at least one language"],
            )
        )

        interests_count = (
            await self.db.execute(
                select(func.count())
                .select_from(UserInterest)
                .where(UserInterest.user_id == user_id)
            )
        ).scalar_one()
        sections.append(
            ReadinessSection(
                key="interests",
                label="Interests",
                weight=5,
                score=5 if interests_count >= 3 else (2 if interests_count else 0),
                complete=interests_count >= 3,
                missing=[] if interests_count >= 3 else ["at least 3 interests"],
            )
        )

        certifications_count = await self._count(Certification, user_id)
        sections.append(
            ReadinessSection(
                key="certifications",
                label="Certifications",
                weight=5,
                score=5 if certifications_count else 0,
                complete=bool(certifications_count),
                missing=[] if certifications_count else ["at least one certification"],
            )
        )

        achievements_count = await self._count(ProfileAchievement, user_id)
        sections.append(
            ReadinessSection(
                key="achievements",
                label="Achievements",
                weight=5,
                score=5 if achievements_count else 0,
                complete=bool(achievements_count),
                missing=[]
                if achievements_count
                else ["at least one award or publication"],
            )
        )

        has_objective = bool((basics.aspirations if basics else None) or [])

        sections.append(
            ReadinessSection(
                key="objective",
                label="Objective",
                weight=5,
                score=5 if has_objective else 0,
                complete=has_objective,
                missing=[] if has_objective else ["a short objective or aspiration"],
            )
        )

        overall = sum(s.score for s in sections)
        return CvReadiness(overall=min(100, overall), sections=sections)

    async def _count(self, model, user_id: uuid.UUID) -> int:
        return (
            await self.db.execute(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )
        ).scalar_one()

    @staticmethod
    def _coverage_section(
        key: str, label: str, weight: int, missing: list[str]
    ) -> ReadinessSection:
        """Partial credit: full weight when complete, weight-3 per gap."""
        score = weight if not missing else max(0, weight - 3 * len(missing))
        return ReadinessSection(
            key=key,
            label=label,
            weight=weight,
            score=min(weight, score),
            complete=not missing,
            missing=missing,
        )
