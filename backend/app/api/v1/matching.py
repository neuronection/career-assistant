from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.models.enums import BackgroundJobType, MatchStatus
from app.models.matching_model import MatchInsight
from app.schemas.matching import (
    CandidateOut,
    FitBreakdownOut,
    FitRefitIn,
    MatchInsightOut,
    RateIn,
    RankingsOut,
    RankedJob,
    ScoreIn,
)
from app.schemas.job import JobOut
from app.services.deps import get_current_user, get_profile_for_user
from app.services.job_service import JobService
from app.services.job_worker import enqueue
from app.services.matching_service import MatchingService
from app.services.university_service import UniversityService

router = APIRouter(tags=["matching"])


def _insight_out(insight: MatchInsight) -> MatchInsightOut:
    """Serialise an insight row."""
    return MatchInsightOut(
        id=insight.id,
        job_id=insight.job_id,
        ai_score=float(insight.ai_score) if insight.ai_score is not None else None,
        ai_confidence=insight.ai_confidence,
        ai_summary=insight.ai_summary,
        ai_positives=insight.ai_positives or [],
        ai_negatives=insight.ai_negatives or [],
        prerequisites=insight.prerequisites or [],
        ai_model=insight.ai_model,
        ai_generated_at=insight.ai_generated_at,
        fit_score=float(insight.fit_score) if insight.fit_score is not None else None,
        fit_breakdown=FitBreakdownOut.model_validate(insight.fit_breakdown or {})
        if insight.fit_breakdown
        else None,
        fit_version=insight.fit_version,
        user_score=insight.user_score,
        status=MatchStatus(insight.status) if insight.status else None,
        user_notes=insight.user_notes,
        seen_at=insight.seen_at,
        saved_at=insight.saved_at,
        hidden_at=insight.hidden_at,
    )


@router.get("/match/candidates", response_model=list[CandidateOut])
async def candidates(
    limit: int = Query(default=12, ge=1, le=50),
    family: str | None = Query(default=None, alias="family_key"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CandidateOut]:
    """Top unscored jobs by deterministic fit (not yet AI-explained)."""
    profile = await get_profile_for_user(db, user.id)
    items = await MatchingService(db).generate_candidates(
        profile, limit=limit, family_key=family
    )
    return [
        CandidateOut(
            job=JobOut.from_model(c["job"]),
            fit_score=c["fit_score"],
            breakdown=FitBreakdownOut.model_validate((c["insight"].fit_breakdown or {}))
            if c["insight"].fit_breakdown
            else None,
        )
        for c in items
    ]


@router.post("/match/fit")
async def refit_fit(
    body: FitRefitIn = Body(default=FitRefitIn()),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deterministic refit: one job synchronously, `all` queued (no AI cost)."""
    from app.core.errors import DomainError
    from app.services.fit.service import FitService
    from app.services.job_service import JobService

    fit_service = FitService(db)
    if body.all:
        job = await enqueue(db, BackgroundJobType.FIT_REFIT.value, {}, user_id=user.id)
        return {"job_id": str(job.id), "status": job.status}
    if not body.job_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "job_id or all=true is required"
        )
    profile = await get_profile_for_user(db, user.id)
    try:
        job_row = await JobService(db).require_job(body.job_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    result = await fit_service.fit_for(profile, job_row)
    insight = await fit_service.upsert_fit(user.id, job_row, result)
    return {
        "job_id": str(job_row.id),
        "fit_score": float(insight.fit_score),
        "breakdown": insight.fit_breakdown,
    }


@router.post("/match/score")
async def score_jobs(
    body: ScoreIn = Body(default=ScoreIn()),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MatchInsightOut] | dict:
    """AI-score jobs for the caller.

    Single job (`job_id`) scores synchronously and returns the insights.
    Batch scoring runs as a background job — 202 with the job id; poll
    /background-jobs/{job_id} for progress.
    """
    if not body.job_id:
        job = await enqueue(
            db,
            BackgroundJobType.MATCH_SCORE.value,
            {"limit": body.limit, "force": body.force},
            user_id=user.id,
        )
        return JSONResponse(
            status_code=202,
            content={"job_id": str(job.id), "status": job.status},
        )
    profile = await get_profile_for_user(db, user.id)
    try:
        insights = await MatchingService(db).score_jobs(
            user.id,
            profile,
            job_ids=[body.job_id],
            force=body.force,
        )
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return [_insight_out(i) for i in insights]


@router.get("/match/insights", response_model=list[MatchInsightOut])
async def my_insights(
    status_filter: MatchStatus | None = Query(default=None, alias="status"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MatchInsightOut]:
    """The caller's stored AI evaluations."""
    rows = await MatchingService(db).my_insights(user.id, status=status_filter)
    return [_insight_out(r) for r in rows]


@router.put("/match/rate", response_model=MatchInsightOut)
async def rate_job(
    data: RateIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> MatchInsightOut:
    """Store the user's own score/status/notes for a job."""
    insight = await MatchingService(db).rate(
        user.id,
        data.job_id,
        user_score=data.user_score,
        status=data.status,
        notes=data.notes,
    )
    return _insight_out(insight)


@router.get("/rankings", response_model=RankingsOut)
async def rankings(
    family: str | None = Query(default=None, alias="family_key"),
    interests: str | None = Query(default=None, description="comma-separated keys"),
    demand: str | None = Query(default=None),
    education_level: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    min_salary: int | None = Query(default=None),
    ai_score_min: float | None = Query(default=None, ge=0, le=10),
    status_filter: MatchStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    sort: str = Query(default="fit"),
    stretch: bool = Query(
        default=False,
        description="true = only hard-gated jobs, with gate reasons",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RankingsOut:
    """Fit-first rankings with rich filters; gated jobs live in the stretch tab."""
    profile = await get_profile_for_user(db, user.id)
    result = await MatchingService(db).rankings(
        profile,
        family_key=family,
        interest_keys=[k.strip() for k in interests.split(",")] if interests else None,
        demand=demand,
        education_level=education_level,
        environment=environment,
        min_salary=min_salary,
        ai_score_min=ai_score_min,
        status=status_filter,
        q=q,
        sort=sort,
        stretch=stretch,
        page=page,
        page_size=page_size,
    )
    return RankingsOut(
        total=result["total"],
        items=[
            RankedJob(
                job=JobOut.from_model(item["job"]),
                score=item["score"],
                fit_score=item["fit_score"],
                ai_score=float(item["insight"].ai_score)
                if item["insight"] and item["insight"].ai_score is not None
                else None,
                user_score=item["insight"].user_score if item["insight"] else None,
                status=MatchStatus(item["insight"].status)
                if item["insight"] and item["insight"].status
                else None,
                breakdown=FitBreakdownOut.model_validate(
                    item["insight"].fit_breakdown or {}
                )
                if item["insight"] and item["insight"].fit_breakdown
                else None,
                specialist_dimension=(
                    (item["insight"].fit_breakdown or {}).get("specialist_dimension")
                    if item["insight"]
                    else None
                ),
                gated=bool((item["insight"].fit_breakdown or {}).get("gates"))
                if item["insight"]
                else False,
                gate_reasons=(item["insight"].fit_breakdown or {}).get("gates") or [],
                insight=_insight_out(item["insight"]) if item["insight"] else None,
            )
            for item in result["items"]
        ],
    )


@router.get("/jobs/{ref}/match")
async def job_match_detail(
    ref: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Everything about a job for this user: insight + university pathways."""
    job_service = JobService(db)
    job = await job_service.require_job(ref)
    rows = await db.execute(
        select(MatchInsight).where(
            MatchInsight.user_id == user.id, MatchInsight.job_id == job.id
        )
    )
    insight = rows.scalars().first()
    links = await UniversityService(db).job_links(job.id)
    pathways = []
    for link in links:
        department = link.department
        pathways.append(
            {
                "department": {
                    "id": department.id,
                    "name": department.name,
                    "degree": department.degree,
                    "duration_years": department.duration_years,
                    "application_deadline": department.application_deadline.isoformat()
                    if department.application_deadline
                    else None,
                    "university": {
                        "id": department.university.id,
                        "name": department.university.name,
                        "country": department.university.country,
                        "city": department.university.city,
                    },
                },
                "relevance": link.relevance,
                "rationale": link.rationale,
                "required_subjects": link.required_subjects,
                "typical_position": link.typical_position,
                "employment_rate_pct": link.employment_rate_pct,
                "admissions": [
                    {
                        "year": a.year,
                        "baseline_score": float(a.baseline_score)
                        if a.baseline_score is not None
                        else None,
                        "units": a.units,
                    }
                    for a in department.admissions
                ],
            }
        )
    return {
        "job": JobOut.from_model(job),
        "insight": _insight_out(insight) if insight else None,
        "university_pathways": pathways,
    }
