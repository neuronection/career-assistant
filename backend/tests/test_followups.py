"""— application follow-ups: sweep nudges, stage prompts,
user-adjustable prefs, scheduler wiring."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from tests.conftest import _make_posting, _uid

from app.models.background_job_model import BackgroundJob
from app.models.engagement_model import Notification, NotificationKind
from app.models.enums import BackgroundJobType, ScheduleKind
from app.models.posting_model import JobPosting, PostingInteraction
from app.models.schedule_model import Schedule
from app.services.followups_service import (
    followup_prefs,
    sweep,
)
from app.services.job_worker import JobWorker
from app.services.scheduler.runner import SchedulerService


async def _applied(
    db, headers, source, *, days_ago=8, stage=None
) -> PostingInteraction:
    posting: JobPosting = await _make_posting(db, source, external_id="fu-1")
    db.add(
        PostingInteraction(
            user_id=UUID(_uid(headers)),
            posting_id=posting.id,
            seen_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            applied_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            stage=stage,
        )
    )
    await db.commit()
    return posting


async def _notes(db, kind_key="followup_due") -> list[Notification]:
    kind = await db.execute(
        select(NotificationKind).where(NotificationKind.key == kind_key)
    )
    kind_row = kind.scalars().first()
    if kind_row is None:
        return []
    rows = await db.execute(
        select(Notification).where(Notification.kind_id == kind_row.id)
    )
    return list(rows.scalars().all())


async def test_sweep_nudges_once_per_step(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=8)
    assert await sweep(db) == 1
    notes = await _notes(db)
    assert len(notes) == 1
    assert "first" in notes[0].dedup_key

    assert await sweep(db) == 0, "re-running must not double-send"


async def test_second_nudge_waits_for_first_and_the_delay(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=3)
    assert await sweep(db) == 0, "before the first delay nothing is due"

    rows = (await db.execute(select(PostingInteraction))).scalars().all()
    rows[0].applied_at = datetime.now(timezone.utc) - timedelta(days=20)
    await db.commit()
    assert await sweep(db) == 1  # first
    assert await sweep(db) == 1  # second (20d > 14d)
    assert await sweep(db) == 0
    assert len(await _notes(db)) == 2


async def test_stage_milestones_get_checkins_not_nudges(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=20, stage="interview")
    assert await sweep(db) == 1
    notes = await _notes(db)
    assert "interview" in notes[0].title or "interview" in notes[0].body
    assert "stage:interview" in notes[0].dedup_key
    assert await sweep(db) == 0


async def test_disabled_user_and_adjusted_delays(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    from app.services.followups_service import update_prefs

    await _applied(db, auth_headers, source, days_ago=8)
    await update_prefs(db, UUID(_uid(auth_headers)), {"enabled": False})
    assert await sweep(db) == 0

    await update_prefs(
        db, UUID(_uid(auth_headers)), {"enabled": True, "first_delay_days": 30}
    )
    assert await sweep(db) == 0, "8d < 30d custom delay"
    rows = (await db.execute(select(PostingInteraction))).scalars().all()
    rows[0].applied_at = datetime.now(timezone.utc) - timedelta(days=31)
    await db.commit()
    assert await sweep(db) == 1


async def test_followups_surface_reads_state(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=8)
    await sweep(db)
    response = await client.get("/api/v1/me/followups", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["prefs"]["enabled"] is True
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["sent_steps"] == ["first"]
    assert item["next_step"] == "second"

    patched = await client.patch(
        "/api/v1/me/followups",
        json={"first_delay_days": 10, "second_delay_days": 21},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["first_delay_days"] == 10

    after = (await client.get("/api/v1/me/followups", headers=auth_headers)).json()
    assert after["prefs"]["second_delay_days"] == 21


async def test_scheduler_provisions_and_enqueues_the_sweep(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from datetime import timedelta as td

    service = SchedulerService(db)
    await service.ensure_system_schedules()
    rows = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == ScheduleKind.SYSTEM_FOLLOWUPS.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].task == BackgroundJobType.FOLLOWUP_SWEEP.value

    await db.execute(
        Schedule.__table__.update()
        .where(Schedule.id == rows[0].id)
        .values(next_run_at=datetime.now(timezone.utc) - td(minutes=1))
    )
    await db.commit()
    await service.tick()
    jobs = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == BackgroundJobType.FOLLOWUP_SWEEP.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1


async def test_job_handler_runs_the_sweep(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    from app.services.job_worker import enqueue

    await _applied(db, auth_headers, source, days_ago=8)
    await enqueue(db, "followup_sweep", {})
    await db.commit()
    worker = JobWorker(db)
    while await worker.run_once():
        pass
    assert len(await _notes(db)) == 1


def test_prefs_clamping():
    assert followup_prefs({})["first_delay_days"] == 7
    merged = followup_prefs(
        {"followups": {"first_delay_days": 0, "second_delay_days": 999}}
    )
    assert merged["first_delay_days"] == 1
    assert merged["second_delay_days"] == 120
