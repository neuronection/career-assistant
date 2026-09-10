"""Career Autopilot endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user_model import User
from app.schemas.autopilot import (
    AutopilotFeedbackIn,
    AutopilotGoalCreate,
    AutopilotGoalUpdate,
)
from app.services.autopilot_service import AutopilotService
from app.services.deps import get_current_user

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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Recent runs across goals with their findings (grouped by run)."""
    return await AutopilotService(db).findings_by_run(user.id)


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


@router.post("/findings/{finding_id}/feedback")
async def finding_feedback(
    finding_id: UUID,
    data: AutopilotFeedbackIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """More-like-this / hide-like-this — learns goal constraints."""
    return await AutopilotService(db).feedback(user.id, finding_id, data.feedback)
