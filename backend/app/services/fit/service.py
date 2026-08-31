"""Fit layer storage + orchestration: compute for user×job, store on insights."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.matching_model import MatchInsight
from app.models.user_model import Profile, UserInterest, UserSkill
from app.services.fit.dimensions import (
    FitResult,
    DEFAULT_WEIGHTS,
    FIT_VERSION,
    compute_fit,
    evidence_years_from_experience,
)
from app.services.job_service import JobService

WORK_STYLE_SLIDERS = ("teamwork", "environment", "structure", "pace", "leadership")


class FitService:
    """Computes deterministic fit and upserts `match_insights` fit fields."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def user_context(self, profile: Profile) -> dict:
        """Structured user snapshot the pure engine consumes."""
        interest_ids = (
            (
                await self.db.execute(
                    select(UserInterest.interest_tag_id).where(
                        UserInterest.user_id == profile.user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        skill_rows = (
            await self.db.execute(
                select(UserSkill.skill_id, UserSkill.level).where(
                    UserSkill.user_id == profile.user_id
                )
            )
        ).all()
        basics = profile.basics or {}
        constraints = profile.constraints or {}
        work_prefs = profile.work_preferences or {}
        years, instances = evidence_years_from_experience(profile.experience or [])
        return {
            "skill_levels": {skill_id: int(level) for skill_id, level in skill_rows},
            "education_level": basics.get("education_level") or "high_school",
            "experience_years": years,
            "experience_instances": instances,
            "city": basics.get("city") or None,
            "country": basics.get("country") or None,
            "remote_ok": bool(work_prefs.get("remote_ok", True)),
            "willing_to_relocate": bool(constraints.get("willing_to_relocate", True)),
            "physical_conditions": constraints.get("physical_conditions") or [],
            "max_education_years": constraints.get("max_education_years"),
            "interest_ids": {str(i) for i in interest_ids},
            "work_style": {k: work_prefs.get(k, 3) for k in WORK_STYLE_SLIDERS},
        }

    async def job_context(self, job) -> dict:
        """Structured job snapshot (links must be loaded — JOB_LOAD_OPTIONS)."""
        attrs = job.attributes or {}
        band = attrs.get("experience_typical_years")
        location = (
            attrs.get("location") if isinstance(attrs.get("location"), dict) else {}
        )
        return {
            "skill_links": [
                {
                    "skill_id": str(link.skill_id),
                    "required_level": link.required_level,
                    "importance": link.importance,
                }
                for link in job.skill_links
            ],
            "education_level": (attrs.get("education") or {}).get("level"),
            "experience_band": tuple(band) if band else None,
            "job_city": location.get("city"),
            "job_country": location.get("country"),
            "job_remote": "remote" in (attrs.get("environments") or []),
            "interest_ids": {str(link.interest_tag_id) for link in job.tag_links},
            "work_style": attrs.get("work_style") or {},
            "physical_requirements": (attrs.get("physical") or {}).get("requirements")
            or [],
        }

    async def scoring_weights(self, profile: Profile) -> dict[str, int]:
        """Effective dimension sliders (1–5).

        Stored user weights win; otherwise the career-stage preset applies
        as the *suggested* baseline (plan 25) — never a hidden branch, the
        presets are plain slider values the user can override.
        """
        stored = (profile.preferences or {}).get("scoring_weights")
        if stored:
            base = {
                dim: int(stored.get(dim, DEFAULT_WEIGHTS[dim]))
                for dim in DEFAULT_WEIGHTS
            }
        else:
            from app.services.stages_service import effective_stage, stage_preset

            stage, _source = effective_stage(
                profile.basics or {}, profile.experience or []
            )
            base = stage_preset(stage)
        return {dim: min(5, max(1, base[dim])) for dim in DEFAULT_WEIGHTS}

    async def fit_for(self, profile: Profile, job) -> FitResult:
        """Compute fit without persisting (listing-time fallback)."""
        return compute_fit(
            job=await self.job_context(job),
            user=await self.user_context(profile),
            weights=await self.scoring_weights(profile),
        )

    async def upsert_fit(
        self, user_id: UUID, job, result: FitResult, *, commit: bool = True
    ) -> MatchInsight:
        """Store fit fields on the user×job insight (fit-only upsert)."""
        rows = await self.db.execute(
            select(MatchInsight).where(
                MatchInsight.user_id == user_id, MatchInsight.job_id == job.id
            )
        )
        insight = rows.scalars().first()
        if insight is None:
            insight = MatchInsight(user_id=user_id, job_id=job.id)
            self.db.add(insight)
        insight.fit_score = result.score
        insight.fit_breakdown = {
            "dimensions": result.breakdown,
            "gates": result.gates,
            "specialist_dimension": result.specialist_dimension,
        }
        insight.fit_version = FIT_VERSION
        await self.db.flush()
        from app.services.engagement_service import EngagementService

        await EngagementService(self.db).on_fit_upsert(user_id, job, insight)
        if commit:
            await self.db.commit()
        return insight

    async def refit_user(
        self, user_id: UUID, profile: Profile | None = None, *, progress=None
    ) -> int:
        """(Re)compute fit for every published job for one user."""
        job_service = JobService(self.db)
        profile = profile or await self._profile(user_id)
        jobs, _ = await job_service.list_jobs(status="published", page_size=1000)
        user_ctx = await self.user_context(profile)
        weights = await self.scoring_weights(profile)
        done = 0
        for job in jobs:
            result = compute_fit(
                job=await self.job_context(job), user=user_ctx, weights=weights
            )
            await self.upsert_fit(user_id, job, result, commit=False)
            done += 1
            if progress and done % 100 == 0:
                await progress(done)
        await self.db.commit()
        return done

    async def refit_job(self, job_id: UUID) -> int:
        """(Re)compute fit for one job across every user with a profile."""
        job_service = JobService(self.db)
        job = await job_service.get_by_code_or_id(job_id)
        if job is None:
            return 0
        job_ctx = await self.job_context(job)
        user_ids = (await self.db.execute(select(Profile.user_id))).scalars().all()
        count = 0
        for user_id in user_ids:
            profile = await self._profile(user_id)
            result = compute_fit(
                job=job_ctx,
                user=await self.user_context(profile),
                weights=await self.scoring_weights(profile),
            )
            await self.upsert_fit(user_id, job, result, commit=False)
            count += 1
        if count:
            await self.db.commit()
        return count

    async def _profile(self, user_id: UUID) -> Profile:
        from app.services.deps import get_profile_for_user

        return await get_profile_for_user(self.db, user_id)
