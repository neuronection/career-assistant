"""Proposal TTL sweep (plan 77.5): the scheduler enqueues the
proposal_sweep job and the worker expires stale pending cards."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.security import decode_access_token
from app.models.enums import ScheduleKind
from app.models.profile_proposal_model import ProfileProposal
from app.models.schedule_model import Schedule
from app.models.user_model import User
from app.services.experience_service import ExperienceService
from app.services.job_worker import JobWorker
from app.services.profile_proposal_service import ProfileProposalService
from app.services.scheduler.runner import SchedulerService


def _uid(auth_headers) -> str:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return decode_access_token(token)[0]


async def _user(db) -> User:
    rows = await db.execute(
        select(User).where(User.email == settings.DEFAULT_USER_EMAIL)
    )
    return rows.scalars().one()


async def _pending_proposal(db, user, *, stale: bool) -> ProfileProposal:
    item = await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Sweep target",
            "kind": "project",
            "open_ended": True,
        },
    )
    proposal = await ProfileProposalService(db).create(
        user.id,
        kind="experience_item",
        action="update",
        payload={"hours_per_week": 8},
        entity_id=item.id,
    )
    if stale:
        proposal.created_at = datetime.now(timezone.utc) - timedelta(days=20)
        db.add(proposal)
        await db.commit()
    return proposal


async def test_sweep_schedule_provisioned_and_expires_stale(client, auth_headers, db):
    user = await _user(db)
    stale = await _pending_proposal(db, user, stale=True)
    fresh = await _pending_proposal(db, user, stale=False)

    service = SchedulerService(db)
    await service.ensure_system_schedules()
    schedule = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == ScheduleKind.SYSTEM_PROPOSAL_SWEEP.value,
                    Schedule.owner_user_id.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None
    schedule.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    assert await service.tick() == 1
    assert schedule.last_job_id is not None

    worker = JobWorker(db)
    while await worker.run_once():
        pass

    await db.refresh(stale)
    await db.refresh(fresh)
    assert stale.status == "expired"
    assert stale.resolve_error == "Expired"
    assert fresh.status == "pending"

    listing = await client.get(
        "/api/v1/me/profile-proposals?status=pending", headers=auth_headers
    )
    ids = [p["id"] for p in listing.json()["proposals"]]
    assert str(fresh.id) in ids
    assert str(stale.id) not in ids
