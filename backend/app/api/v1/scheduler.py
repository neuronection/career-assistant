"""Scheduler endpoints (Phase 29): user saved-search schedules."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import ScheduleKind
from app.models.schedule_model import Schedule
from app.services.deps import get_current_user
from app.services.scheduler.runner import SchedulerService

router = APIRouter(tags=["scheduler"])


class SavedSearchScheduleIn(BaseModel):
    # {"type": "interval"|"daily_at"|"weekly"|"cron", "params": {...}} or null.
    trigger: dict | None = None


def _schedule_out(schedule: Schedule) -> dict:
    return {
        "id": str(schedule.id),
        "kind": schedule.kind,
        "task": schedule.task,
        "trigger": schedule.trigger,
        "payload": schedule.payload,
        "enabled": schedule.enabled,
        "next_run_at": schedule.next_run_at.isoformat()
        if schedule.next_run_at
        else None,
        "last_run_at": schedule.last_run_at.isoformat()
        if schedule.last_run_at
        else None,
        "last_status": schedule.last_status,
        "consecutive_failures": schedule.consecutive_failures,
        "misfire_policy": schedule.misfire_policy,
        "error": schedule.error,
    }


@router.get("/me/schedules")
async def my_schedules(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """The caller's schedules (check-in, digest, saved searches)."""
    service = SchedulerService(db)
    await service.ensure_user_schedules(user.id)
    rows = await service.list_schedules(user.id)
    return [_schedule_out(s) for s in rows]


@router.put("/me/searches/{search_id}/schedule")
async def schedule_saved_search(
    search_id: UUID,
    data: SavedSearchScheduleIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Attach (or remove, trigger=null) a schedule to a saved search."""
    service = SchedulerService(db)
    schedule = await service.set_saved_search_schedule(user.id, search_id, data.trigger)
    return _schedule_out(schedule) if schedule else {"removed": True}


@router.get("/me/searches/{search_id}/schedule")
async def get_saved_search_schedule(
    search_id: UUID, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    rows = await db.execute(
        select(Schedule).where(
            Schedule.owner_user_id == user.id,
            Schedule.kind == ScheduleKind.USER_SAVED_SEARCH.value,
        )
    )
    for schedule in rows.scalars().all():
        if schedule.payload.get("search_id") == str(search_id):
            return _schedule_out(schedule)
    return {"enabled": False}
