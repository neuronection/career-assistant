from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.agents import analyze_profile
from app.core.errors import ValidationError
from app.models.taxonomy_model import InterestTag, Skill
from app.models.user_model import Profile, UserInterest
from app.schemas.profile import ProfileSectionUpdate


class ProfileService:
    """Structured profile CRUD (interests live in `user_interests`) + AI hook."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: UUID) -> Profile:
        """Get or create the profile for a user."""
        from app.services.deps import get_profile_for_user

        return await get_profile_for_user(self.db, user_id)

    async def interest_rows(self, user_id: UUID) -> list[UserInterest]:
        """The user's interest links, strongest first, tags loaded."""
        rows = await self.db.execute(
            select(UserInterest)
            .options(selectinload(UserInterest.tag))
            .where(UserInterest.user_id == user_id)
            .order_by(UserInterest.weight.desc(), UserInterest.created_at)
        )
        return list(rows.scalars().all())

    async def update(self, user_id: UUID, data: ProfileSectionUpdate) -> Profile:
        """Merge validated sections into the profile (+ interest links).

        Fit-relevant section changes trigger a deterministic refit (plan 22).
        """
        profile = await self.get(user_id)
        payload = data.model_dump(exclude_none=True, exclude_defaults=False)
        interests = payload.pop("interests", None)
        if interests is not None:
            await self._write_interests(user_id, interests)
        fit_relevant = False
        for section in (
            "basics",
            "academics",
            "hobbies",
            "likes",
            "dislikes",
            "aspirations",
            "work_preferences",
            "experience",
            "preferences",
            "constraints",
        ):
            if section in payload and payload[section] is not None:
                setattr(profile, section, payload[section])
                if section != "hobbies":
                    fit_relevant = True
        self._strip_student_fields(profile)
        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        if interests is not None or fit_relevant:
            from app.services.fit.service import FitService

            await FitService(self.db).refit_user(user_id, profile)
        return profile

    @staticmethod
    def _strip_student_fields(profile: Profile) -> None:
        """grade/gpa are student-only — non-student stages never carry them."""
        from app.models.enums import CareerStage
        from app.services.stages_service import effective_stage

        stage, _source = effective_stage(profile.basics or {}, profile.experience or [])
        if stage == CareerStage.STUDENT:
            return
        if (profile.basics or {}).get("grade") is not None:
            profile.basics = {**profile.basics, "grade": None}
        if (profile.academics or {}).get("gpa_band") is not None:
            profile.academics = {**profile.academics, "gpa_band": None}

    async def _write_interests(self, user_id: UUID, items: list[dict]) -> None:
        """Replace the user's interest links (taxonomy keys, weights 1–5)."""
        if not items:
            await self.db.execute(
                delete(UserInterest).where(UserInterest.user_id == user_id)
            )
            return
        tags = {
            t.key: t
            for t in (
                await self.db.execute(
                    select(InterestTag).where(
                        InterestTag.key.in_([i["tag_key"] for i in items])
                    )
                )
            )
            .scalars()
            .all()
        }
        missing = [i["tag_key"] for i in items if i["tag_key"] not in tags]
        if missing:
            raise ValidationError(
                f"Unknown interest keys: {', '.join(sorted(set(missing)))}"
            )
        await self.db.execute(
            delete(UserInterest).where(UserInterest.user_id == user_id)
        )
        seen: set[str] = set()
        for item in items:
            key = item["tag_key"]
            if key in seen:
                continue
            seen.add(key)
            self.db.add(
                UserInterest(
                    user_id=user_id,
                    interest_tag_id=tags[key].id,
                    weight=int(item.get("weight") or 3),
                    source=str(item.get("source") or "self"),
                )
            )
        await self.db.flush()

    @staticmethod
    def interests_out(rows: list[UserInterest]) -> list[dict]:
        """API shape for the interests section (same as the old JSONB)."""
        return [
            {"tag_key": row.tag.key, "weight": row.weight, "source": row.source}
            for row in rows
        ]

    async def snapshot(self, profile: Profile) -> dict:
        """Serialise the profile for prompts/candidates."""
        rows = await self.interest_rows(profile.user_id)
        experience = [
            {
                "title": item.get("title"),
                "kind": item.get("kind"),
                "years": max(
                    0,
                    int(item.get("end_year") or 2026)
                    - int(item.get("start_year") or 0),
                ),
                "skills": item.get("skill_keys") or [],
            }
            for item in (profile.experience or [])
        ]
        return {
            "user_id": str(profile.user_id),
            "basics": profile.basics or {},
            "academics": profile.academics or {},
            "interests": self.interests_out(rows),
            "hobbies": profile.hobbies or [],
            "likes": profile.likes or [],
            "dislikes": profile.dislikes or [],
            "aspirations": profile.aspirations or [],
            "work_preferences": profile.work_preferences or {},
            "experience": experience,
            "constraints": profile.constraints or {},
        }

    async def profile_summary(self, profile: Profile) -> str:
        """Compact human-readable summary for chat personalization."""
        rows = await self.interest_rows(profile.user_id)
        interests = ", ".join(row.tag.key for row in rows[:8])
        basics = profile.basics or {}
        return (
            f"{basics.get('education_level', 'student')} student"
            + (f" in {basics.get('city')}" if basics.get("city") else "")
            + f"; interests: {interests or 'unknown'}"
        )

    @staticmethod
    def interest_weights(
        profile: Profile, interest_rows: list[UserInterest]
    ) -> dict[str, int]:
        """Map of interest tag key → weight (max weight wins)."""
        weights: dict[str, int] = {}
        for row in interest_rows:
            weights[row.tag.key] = max(weights.get(row.tag.key, 0), int(row.weight))
        subjects = (profile.academics or {}).get("favorite_subjects") or []
        for subject in subjects:
            key = subject.get("key")
            if key:
                weights.setdefault(f"subject:{key}", int(subject.get("weight", 3)))
        return weights

    async def ai_analyze(self, user_id: UUID, profile: Profile) -> Profile:
        """Run the profile analyst agent and store the structured summary."""
        insight = await analyze_profile(self.db, user_id, profile)
        known = set((await self.db.execute(select(InterestTag.key))).scalars().all())
        skill_map = await _skill_alias_map(self.db)
        suggested_skills = []
        for key in insight.suggested_skill_keys:
            canonical = skill_map.get(key.strip().lower())
            if canonical and canonical not in suggested_skills:
                suggested_skills.append(canonical)
        profile.ai_summary = {
            **insight.model_dump(mode="json"),
            "suggested_interest_keys": [
                k for k in insight.suggested_interest_keys if k in known
            ],
            "suggested_skill_keys": suggested_skills,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    def completeness(self, profile: Profile, interests_count: int = 0) -> dict:
        """Percentage of profile sections filled (drives onboarding UI)."""
        checks = {
            "basics": bool(
                (profile.basics or {}).get("country")
                or (profile.basics or {}).get("birth_year")
            ),
            "academics": bool((profile.academics or {}).get("favorite_subjects")),
            "interests": interests_count > 0,
            "hobbies": bool(profile.hobbies),
            "likes": bool(profile.likes) or bool(profile.dislikes),
            "aspirations": bool(profile.aspirations),
            "work_preferences": bool(
                (profile.work_preferences or {}).get("focus_areas")
            ),
            "constraints": bool(
                (profile.constraints or {}).get("physical_conditions")
                or (profile.constraints or {}).get("max_education_years")
                or (profile.constraints or {}).get("hours_available_per_week")
            ),
        }
        done = sum(1 for v in checks.values() if v)
        return {"percent": round(done / len(checks) * 100), "sections": checks}


async def _skill_alias_map(db: AsyncSession) -> dict[str, str]:
    """normalized key/alias → canonical key for every active skill."""
    rows = (
        (await db.execute(select(Skill).where(Skill.status == "active")))
        .scalars()
        .all()
    )
    mapping: dict[str, str] = {}
    for skill in rows:
        mapping[skill.key.strip().lower()] = skill.key
        mapping[skill.label.strip().lower()] = skill.key
        for alias in skill.aliases or []:
            mapping[str(alias).strip().lower()] = skill.key
    return mapping
