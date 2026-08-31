from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import score_match
from app.models.enums import DemandOutlook, MatchStatus
from app.models.job_model import Job
from app.models.matching_model import MatchInsight
from app.models.user_model import Profile
from app.services.fit.dimensions import FIT_VERSION, compute_fit
from app.services.fit.service import FitService
from app.services.job_service import JOB_LOAD_OPTIONS, JobService
from app.services.profile_service import ProfileService

DEMAND_NUMERIC = {
    DemandOutlook.DECLINING: 2.0,
    DemandOutlook.STABLE: 5.0,
    DemandOutlook.GROWING: 8.0,
    DemandOutlook.HOT: 10.0,
}


class MatchingService:
    """Fit-layer feeds, AI rationale layer, user rating, rankings."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _is_gated(self, insight: MatchInsight | None) -> bool:
        return bool(insight and (insight.fit_breakdown or {}).get("gates"))

    async def generate_candidates(
        self,
        profile: Profile,
        *,
        limit: int = 12,
        family_key: str | None = None,
    ) -> list[dict]:
        """Top unscored, feed-eligible jobs by deterministic fit."""
        insights = await self.backfilled_insights(profile)
        job_service = JobService(self.db)
        jobs, _ = await job_service.list_jobs(family_key=family_key, page_size=500)
        items = []
        for job in jobs:
            insight = insights.get(job.id)
            if insight is None or insight.fit_score is None:
                continue
            if self._is_gated(insight):
                continue
            if insight.ai_score is not None:
                continue
            items.append(
                {
                    "job": job,
                    "fit_score": float(insight.fit_score),
                    "insight": insight,
                }
            )
        items.sort(key=lambda item: (-item["fit_score"], item["job"].title))
        return items[:limit]

    async def backfilled_insights(self, profile: Profile) -> dict[UUID, MatchInsight]:
        """Insight map guaranteed to cover every published job.

        Missing (or stale-version) rows are computed on the fly with one
        shared user context and persisted — deterministic, no AI.
        """
        insights = await self._insights_map(profile.user_id)
        job_service = JobService(self.db)
        jobs, _ = await job_service.list_jobs(status="published", page_size=1000)
        missing = [
            job
            for job in jobs
            if insights.get(job.id) is None
            or insights[job.id].fit_score is None
            or insights[job.id].fit_version != FIT_VERSION
        ]
        if missing:
            fit_service = FitService(self.db)
            user_ctx = await fit_service.user_context(profile)
            weights = await fit_service.scoring_weights(profile)
            for job in missing:
                result = compute_fit(
                    job=await fit_service.job_context(job),
                    user=user_ctx,
                    weights=weights,
                )
                insights[job.id] = await fit_service.upsert_fit(
                    profile.user_id, job, result, commit=False
                )
            await self.db.commit()
        return insights

    @staticmethod
    def _constraint_feasible(job: Job, conditions: list) -> bool:
        """Physical-requirement gates (soft; only hard conflicts removed)."""
        from app.services.fit.dimensions import evaluate_gates

        physical = (job.attributes or {}).get("physical", {}) or {}
        gates = evaluate_gates(
            job_physical_requirements=physical.get("requirements") or [],
            job_education_level=None,
            user_physical_conditions=conditions or [],
            user_max_education_years=None,
        )
        return not gates

    async def score_jobs(
        self,
        user_id: UUID,
        profile: Profile,
        *,
        job_ids: list[UUID] | None = None,
        limit: int = 10,
        force: bool = False,
    ) -> list[MatchInsight]:
        """AI-score jobs (rationale layer) and upsert match insights."""
        targets = await self.resolve_targets(profile, job_ids=job_ids, limit=limit)
        insights: list[MatchInsight] = []
        for job in targets:
            insight = await self.score_one(user_id, profile, job, force=force)
            if insight is not None:
                insights.append(insight)
        await self.db.commit()
        return insights

    async def profile_for(self, user_id: UUID) -> Profile:
        """The caller's profile, created when missing."""
        from app.services.deps import get_profile_for_user

        return await get_profile_for_user(self.db, user_id)

    async def resolve_targets(
        self,
        profile: Profile,
        *,
        job_ids: list[UUID] | None = None,
        limit: int = 10,
    ) -> list[Job]:
        """Explicit jobs when ids are given, else top-N by fit (no AI yet)."""
        if job_ids:
            rows = await self.db.execute(
                select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id.in_(job_ids))
            )
            return list(rows.scalars().unique().all())
        await self.backfilled_insights(profile)
        insights = await self._insights_map(profile.user_id)
        job_service = JobService(self.db)
        jobs, _ = await job_service.list_jobs(status="published", page_size=500)
        pending = []
        for job in jobs:
            insight = insights.get(job.id)
            fit_score = (
                float(insight.fit_score)
                if insight and insight.fit_score is not None
                else 0.0
            )
            if self._is_gated(insight):
                continue
            pending.append((fit_score, job))
        pending.sort(key=lambda pair: (-pair[0], pair[1].title))
        return [job for _fit, job in pending[:limit]]

    async def score_one(
        self,
        user_id: UUID,
        profile: Profile,
        job: Job,
        *,
        force: bool = False,
    ) -> MatchInsight | None:
        """Score a single job (skipped when already scored and not forced)."""
        existing = await self._get_insight(user_id, job.id)
        if existing and existing.ai_score is not None and not force:
            return existing
        profile_snapshot = await ProfileService(self.db).snapshot(profile)
        result = await score_match(
            self.db,
            user_id,
            profile_snapshot,
            JobService.job_snapshot(job),
        )
        return await self._upsert_insight(user_id, job, result)

    async def _get_insight(self, user_id: UUID, job_id: UUID) -> MatchInsight | None:
        rows = await self.db.execute(
            select(MatchInsight).where(
                MatchInsight.user_id == user_id, MatchInsight.job_id == job_id
            )
        )
        return rows.scalars().first()

    async def _insights_map(self, user_id: UUID) -> dict[UUID, MatchInsight]:
        rows = await self.db.execute(
            select(MatchInsight).where(MatchInsight.user_id == user_id)
        )
        return {row.job_id: row for row in rows.scalars().all()}

    async def _upsert_insight(self, user_id: UUID, job: Job, result) -> MatchInsight:
        """Insert or refresh AI fields on the insight row."""
        insight = await self._get_insight(user_id, job.id)
        if insight is None:
            insight = MatchInsight(user_id=user_id, job_id=job.id)
            self.db.add(insight)
        insight.ai_score = float(result.score)
        insight.ai_confidence = float(result.confidence)
        insight.ai_summary = result.summary
        insight.ai_positives = [p.model_dump(mode="json") for p in result.positives]
        insight.ai_negatives = [n.model_dump(mode="json") for n in result.negatives]
        insight.prerequisites = [
            p.model_dump(mode="json") for p in result.prerequisites
        ]
        insight.ai_model = "current"
        insight.ai_generated_at = datetime.now(timezone.utc)
        if insight.fit_score is None:
            fit = await FitService(self.db).fit_for(
                await self._profile_for(user_id), job
            )
            insight.fit_score = fit.score
            insight.fit_breakdown = {
                "dimensions": fit.breakdown,
                "gates": fit.gates,
                "specialist_dimension": fit.specialist_dimension,
            }
            insight.fit_version = FIT_VERSION
        await self.db.flush()
        return insight

    async def _profile_for(self, user_id: UUID) -> Profile:
        from app.services.deps import get_profile_for_user

        return await get_profile_for_user(self.db, user_id)

    async def rate(
        self,
        user_id: UUID,
        job_id: UUID,
        *,
        user_score: Optional[int] = None,
        status: Optional[MatchStatus] = None,
        notes: Optional[str] = None,
    ) -> MatchInsight:
        """Store the user's own score/status for a job."""
        job = await JobService(self.db).require_job(job_id)
        insight = await self._get_insight(user_id, job.id)
        if insight is None:
            insight = MatchInsight(user_id=user_id, job_id=job.id)
            self.db.add(insight)
            await self.db.flush()
        if user_score is not None:
            insight.user_score = user_score
        if status is not None:
            insight.status = status.value
        if notes is not None:
            insight.user_notes = notes
        await self.db.commit()
        await self.db.refresh(insight)
        return insight

    async def my_insights(
        self, user_id: UUID, *, status: Optional[MatchStatus] = None
    ) -> list[MatchInsight]:
        """All insights for a user, optionally filtered by status."""
        query = select(MatchInsight).where(MatchInsight.user_id == user_id)
        if status:
            query = query.where(MatchInsight.status == status.value)
        rows = await self.db.execute(query.order_by(MatchInsight.updated_at.desc()))
        return list(rows.scalars().all())

    async def rankings(
        self,
        profile: Profile,
        *,
        family_key: str | None = None,
        interest_keys: list[str] | None = None,
        demand: str | None = None,
        education_level: str | None = None,
        environment: str | None = None,
        min_salary: int | None = None,
        ai_score_min: float | None = None,
        status: Optional[MatchStatus] = None,
        q: str | None = None,
        sort: str = "fit",
        stretch: bool = False,
        page: int = 1,
        page_size: int = 25,
    ) -> dict:
        """Filtered + sorted rankings on the deterministic fit layer.

        Default sort is `0.6·fit + 0.4·ai` (ai falls back to fit when
        missing). `stretch=True` returns only hard-gated jobs with their
        gate reasons — they leave the default feed but are never deleted.
        """
        insights = await self.backfilled_insights(profile)
        job_service = JobService(self.db)
        jobs, _ = await job_service.list_jobs(
            q=q,
            family_key=family_key,
            interest_keys=interest_keys,
            demand=demand,
            education_level=education_level,
            environment=environment,
            min_salary=min_salary,
            status="published",
            page_size=500,
        )
        items = []
        for job in jobs:
            insight = insights.get(job.id)
            if insight is None or insight.fit_score is None:
                continue
            breakdown = insight.fit_breakdown or {}
            gates = breakdown.get("gates") or []
            if stretch and not gates:
                continue
            if not stretch and gates:
                continue
            if status and (insight is None or insight.status != status.value):
                continue
            ai_score = (
                float(insight.ai_score)
                if insight and insight.ai_score is not None
                else None
            )
            if ai_score_min is not None and (
                ai_score is None or ai_score < ai_score_min
            ):
                continue
            fit_score = float(insight.fit_score)
            ai_effective = ai_score if ai_score is not None else fit_score
            score = round(0.6 * fit_score + 0.4 * ai_effective, 2)
            items.append(
                {
                    "job": job,
                    "score": score,
                    "fit_score": fit_score,
                    "insight": insight,
                }
            )
        items.sort(key=self._sort_key(sort), reverse=(sort != "title"))
        total = len(items)
        start = (page - 1) * page_size
        return {"items": items[start : start + page_size], "total": total}

    @staticmethod
    def _sort_key(sort: str):
        """Key function for the requested sort order (fit is the default)."""
        if sort == "fit":
            return lambda item: item["score"]
        if sort == "ai_score":
            return (
                lambda item: float(item["insight"].ai_score or 0)
                if item["insight"]
                else 0
            )
        if sort == "user_score":
            return (
                lambda item: item["insight"].user_score or 0 if item["insight"] else 0
            )
        if sort == "demand":
            # Opt-in plain sort on the demand outlook — never a multiplier.
            return lambda item: DEMAND_NUMERIC.get(
                DemandOutlook(
                    ((item["job"].attributes or {}).get("demand", {}) or {}).get(
                        "outlook", "stable"
                    )
                ),
                5.0,
            )
        if sort == "title":
            return lambda item: item["job"].title
        return lambda item: item["score"]
