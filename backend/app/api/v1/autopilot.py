"""Career Autopilot endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user_model import User
from app.schemas.autopilot import (
    AutopilotFeedbackIn,
    AutopilotGoalCreate,
    AutopilotGoalUpdate,
    ProfileContextPreviewIn,
)
from app.services.deps import get_current_user
from app.services.growth.autopilot_service import AutopilotService, profile_context_preview

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


@router.post("/goals", status_code=201)
async def create_goal(
    data: AutopilotGoalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a goal (optionally with a cadence schedule)."""
    goal = await AutopilotService(db).create_goal(user.id, data)
    return {"id": str(goal.id), "status": goal.status}


@router.get("/goals")
async def list_goals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """The caller's goals with last-run outcome + open findings."""
    return await AutopilotService(db).list_goals(user.id)


@router.get("/findings")
async def list_findings(
    goal_id: UUID | None = None,
    run_id: UUID | None = None,
    state: Literal["open", "dismissed", "all"] = "open",
    latest_per_posting: bool = True,
    sort: Literal["newest", "score"] = "newest",
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=10),
    coverage_min: int | None = Query(default=None, ge=0, le=20),
    org: str | None = None,
    source: str | None = None,
    seniority: str | None = None,
    remote: bool = False,
    posted_within: str | None = None,
    hide_applied: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The flat findings feed: filters, dedupe, facets, keyset pagination."""
    return await AutopilotService(db).findings_feed(
        user.id,
        goal_id=goal_id,
        run_id=run_id,
        state=state,
        latest_per_posting=latest_per_posting,
        sort=sort,
        limit=limit,
        cursor=cursor,
        min_score=min_score,
        coverage_min=coverage_min,
        org=org,
        source=source,
        seniority=seniority,
        remote=remote,
        posted_within=posted_within,
        hide_applied=hide_applied,
    )


@router.get("/runs")
async def list_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """The runs rail, cross-goal: status, tokens, live findings, examined."""
    return await AutopilotService(db).runs_rail(user.id)


@router.post("/profile-context")
async def profile_context(
    data: ProfileContextPreviewIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The caller's effective profile snapshot for a draft usage block +
    seniority — the goal form's live summary; never touches a goal row."""
    return await profile_context_preview(db, user.id, data.profile, data.seniority)


@router.get("/goals/{goal_id}")
async def goal_detail(
    goal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Goal detail incl. runs + the searches-executed transparency timeline."""
    return await AutopilotService(db).get_goal_detail(user.id, goal_id)


@router.patch("/goals/{goal_id}")
async def patch_goal(
    goal_id: UUID,
    data: AutopilotGoalUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pause/resume, edit text/constraints/budget, re-wire the cadence."""
    goal = await AutopilotService(db).update_goal(user.id, goal_id, data)
    return {"id": str(goal.id), "status": goal.status}


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await AutopilotService(db).delete_goal(user.id, goal_id)


@router.post("/goals/{goal_id}/run")
async def run_goal(
    goal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """On-demand run (long executions are better queued — the scheduler
    and job queue use the same service path)."""
    result = await AutopilotService(db).run_goal(goal_id, user.id)
    if "skipped" in result:
        raise HTTPException(status_code=409, detail=result["skipped"])
    return result


@router.get("/goals/{goal_id}/runs")
async def goal_runs(
    goal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Run history with findings — the goal's audit trail."""
    return await AutopilotService(db).runs(user.id, goal_id)


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One run's inspectable detail: node trace, AI calls and findings —
    a foreign and a missing run answer the same 404."""
    return await AutopilotService(db).run_detail(user.id, run_id)


@router.post("/findings/{finding_id}/feedback")
async def finding_feedback(
    finding_id: UUID,
    data: AutopilotFeedbackIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """More-like-this / hide-like-this — learns goal constraints."""
    return await AutopilotService(db).feedback(user.id, finding_id, data.feedback)
