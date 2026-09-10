"""Phase 29 modular scheduler: triggers, misfire, overlap, backoff,
claim semantics, digests, saved-search runs, check-in integration."""

import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import decode_access_token
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, ScheduleKind
from app.models.matching_model import MatchInsight
from app.models.posting_model import JobPosting
from app.models.schedule_model import Schedule
from app.services.fit.dimensions import FIT_VERSION, FitResult
from app.services.fit.service import FitService
from app.services.scheduler import triggers as trigger_registry
from app.services.scheduler.runner import SchedulerService
from app.services.job_worker import JobWorker


def _uid(auth_headers) -> uuid_mod.UUID:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return decode_access_token(token)[0]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
async def kinds(db):
    from app.seeds.run import seed_notification_kinds

    return await seed_notification_kinds(db)


# ------------------------------------------------------------- triggers


def test_interval_jitter_bounds():
    now = _now()
    bounded = trigger_registry.next_after(
        {"type": "interval", "params": {"every_minutes": 60, "jitter_minutes": 10}},
        now,
        rnd=lambda a, b: b,
    )
    no_jitter = trigger_registry.next_after(
        {"type": "interval", "params": {"every_minutes": 60}}, now
    )
    assert timedelta(minutes=60) <= bounded - now <= timedelta(minutes=70)
    assert no_jitter - now == timedelta(minutes=60)


def test_daily_at_timezone_and_dst_edge():
    now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    athens = trigger_registry.next_after(
        {"type": "daily_at", "params": {"time": "08:00", "timezone": "Europe/Athens"}},
        now,
    )
    assert athens.hour == 5
    # US DST start (2026-03-08, 02:30 does not exist) — must not crash and
    # must still land on a sane 02:30-local instant.
    before = datetime(2026, 3, 7, 20, 0, tzinfo=timezone.utc)
    dst = trigger_registry.next_after(
        {
            "type": "daily_at",
            "params": {"time": "02:30", "timezone": "America/New_York"},
        },
        before,
    )
    assert dst.minute == 30
    assert dst > before


def test_weekly_next_occurrence():
    now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)  # a Monday
    nxt = trigger_registry.next_after(
        {
            "type": "weekly",
            "params": {"weekday": 0, "time": "08:00", "timezone": "UTC"},
        },
        now,
    )
    assert nxt.weekday() == 0
    assert nxt > now
    assert (nxt - now).days == 6


def test_cron_parser_valid_and_malformed():
    now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)  # Monday 10:00
    nxt = trigger_registry.next_after(
        {"type": "cron", "params": {"expr": "30 8 * * 1-5"}}, now
    )
    assert (nxt.hour, nxt.minute) == (8, 30)
    assert nxt.weekday() == 1  # Tuesday (next workday)
    list_expr = trigger_registry.next_after(
        {"type": "cron", "params": {"expr": "0 9 1,15 * *"}}, now
    )
    assert list_expr.day in (1, 15)
    for bad in ["99 * * * *", "not a cron", "60 25 32 13 7"]:
        with pytest.raises(Exception):
            trigger_registry.next_after({"type": "cron", "params": {"expr": bad}}, now)


def test_plugin_trigger_registration():
    from pydantic import BaseModel

    class SyntheticTrigger:
        key = "synthetic_trigger"

        class Params(BaseModel):
            every: int

        @classmethod
        def validate(cls, params):
            return cls.Params.model_validate(params)

        @classmethod
        def next_after(cls, now, params, *, rnd=None):
            from datetime import timedelta

            return now + timedelta(minutes=params["every"])

    trigger_registry.register_trigger(SyntheticTrigger)
    try:
        nxt = trigger_registry.next_after(
            {"type": "synthetic_trigger", "params": {"every": 5}}, _now()
        )
        assert abs((nxt - _now()).total_seconds() - 300) < 5
    finally:
        trigger_registry.reset_registry()
    with pytest.raises(Exception):
        trigger_registry.resolve_trigger({"type": "synthetic_trigger", "params": {}})


# ------------------------------------------------- provisioning + ticks


async def test_system_schedules_provisioned_once(client, auth_headers, db):
    service = SchedulerService(db)
    await service.ensure_system_schedules()
    await service.ensure_system_schedules()
    rows = (
        (await db.execute(select(Schedule).where(Schedule.owner_user_id.is_(None))))
        .scalars()
        .all()
    )
    kinds = [r.kind for r in rows]
    assert kinds.count("system_source_sync") == 1
    assert kinds.count("system_refit_sweep") == 1


async def test_overlap_guard_and_claim_semantics(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    service = SchedulerService(db)
    schedule = await service.ensure_schedule(
        kind=ScheduleKind.SYSTEM_SOURCE_SYNC.value,
        owner_user_id=None,
        task="posting_sync",
        trigger={"type": "interval", "params": {"every_minutes": 60}},
        payload={},
        misfire_policy="asap",
        default_interval_minutes=60,
    )
    schedule.next_run_at = _now() - timedelta(minutes=1)
    await db.commit()

    assert await service.tick() == 1
    await db.refresh(schedule)
    assert schedule.last_run_at is not None
    assert schedule.next_run_at > _now() - timedelta(seconds=5)
    first_job_id = schedule.last_job_id

    # The enqueued job stays queued → the next tick must NOT pile up.
    await db.execute(
        Schedule.__table__.update()
        .where(Schedule.id == schedule.id)
        .values(next_run_at=_now() - timedelta(minutes=1))
    )
    await db.commit()
    assert await service.tick() == 0
    await db.refresh(schedule)
    assert schedule.last_status == "skipped_overlap"
    assert schedule.last_job_id == first_job_id


async def test_misfire_policies(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    service = SchedulerService(db)
    for policy, should_fire in (("asap", True), ("skip", False), ("next_slot", False)):
        schedule = await service.ensure_schedule(
            kind=ScheduleKind.SYSTEM_SOURCE_SYNC.value,
            owner_user_id=None,
            task="posting_sync",
            trigger={"type": "interval", "params": {"every_minutes": 30}},
            payload={"policy": policy},
            misfire_policy=policy,
            default_interval_minutes=30,
        )
        schedule.next_run_at = _now() - timedelta(days=10)  # very late
        await db.commit()

        await service.tick()
        await db.refresh(schedule)
        if should_fire:
            assert schedule.last_job_id is not None
        else:
            assert schedule.last_status == "skipped_misfire"
            assert schedule.next_run_at > _now()


async def test_failure_backoff_ladder(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    service = SchedulerService(db)
    schedule = await service.ensure_schedule(
        kind=ScheduleKind.SYSTEM_SOURCE_SYNC.value,
        owner_user_id=None,
        task="posting_sync",
        trigger={"type": "interval", "params": {"every_minutes": 60}},
        payload={"backoff": "y"},
        misfire_policy="asap",
        default_interval_minutes=60,
    )
    schedule.next_run_at = _now() - timedelta(minutes=1)
    schedule.consecutive_failures = 2
    schedule.last_run_at = _now() - timedelta(seconds=10)  # inside backoff
    await db.commit()

    assert await service.tick() == 0
    await db.refresh(schedule)
    assert schedule.last_status == "backoff"

    schedule.last_run_at = _now() - timedelta(hours=2)  # backoff window passed
    schedule.next_run_at = _now() - timedelta(minutes=1)
    await db.commit()
    assert await service.tick() == 1
    await db.refresh(schedule)
    assert schedule.last_job_id is not None

    # A successful run resets the failure counter.
    job = await db.get(BackgroundJob, schedule.last_job_id)
    job.status = BackgroundJobStatus.SUCCEEDED.value
    await db.commit()
    await db.execute(
        Schedule.__table__.update()
        .where(Schedule.id == schedule.id)
        .values(next_run_at=_now() - timedelta(minutes=1))
    )
    await db.commit()
    await service.tick()
    await db.refresh(schedule)
    assert schedule.consecutive_failures == 0


async def test_failure_alerts_admin_after_threshold(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    from app.models.user_model import User
    from app.services.notification_service import NotificationService

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()

    service = SchedulerService(db)
    schedule = await service.ensure_schedule(
        kind=ScheduleKind.SYSTEM_SOURCE_SYNC.value,
        owner_user_id=None,
        task="posting_sync",
        trigger={"type": "interval", "params": {"every_minutes": 60}},
        payload={"alerting": "y"},
        misfire_policy="asap",
        default_interval_minutes=60,
    )
    schedule.next_run_at = _now() - timedelta(minutes=1)
    await db.commit()
    await service.tick()
    job = await db.get(BackgroundJob, schedule.last_job_id)
    job.status = BackgroundJobStatus.FAILED.value
    job.error = "boom"
    schedule.consecutive_failures = 3
    await db.commit()

    # Next tick sees the failure and alerts the admin.
    await db.execute(
        Schedule.__table__.update()
        .where(Schedule.id == schedule.id)
        .values(next_run_at=_now() - timedelta(minutes=1), last_job_id=None)
    )
    await db.commit()
    schedule.consecutive_failures = 3
    await db.commit()
    await service._handle_due(schedule, _now())

    assert await NotificationService(db).unread_count(user.id) >= 1
    notifications = (
        await client.get("/api/v1/notifications", headers=auth_headers)
    ).json()
    assert any(n["kind"] == "background_failed" for n in notifications["items"])


# ------------------------------------------------- digests + saved search


async def test_digest_schedule_end_to_end(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    bootstrap = (await client.get("/api/v1/me/bootstrap", headers=auth_headers)).json()
    assert bootstrap["target_mode"] is False

    schedule = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.owner_user_id == _uid(auth_headers),
                    Schedule.kind == ScheduleKind.SYSTEM_DIGEST.value,
                )
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None
    schedule.next_run_at = _now() - timedelta(minutes=1)
    await db.commit()

    service = SchedulerService(db)
    assert await service.tick() == 1
    await db.refresh(schedule)
    assert schedule.last_job_id is not None

    worker = JobWorker(db)
    while await worker.run_once():
        pass

    notifications = (
        await client.get("/api/v1/notifications", headers=auth_headers)
    ).json()
    assert any(n["kind"] == "digest_ready" for n in notifications["items"])


async def test_saved_search_schedule_end_to_end(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    """Saved postings search → schedule → tick → worker → notification."""
    recorded = await client.post(
        "/api/v1/me/searches",
        json={
            "scope": "postings",
            "query": "qa",
            "filters": {"remote": True},
            "result_count": 1,
        },
        headers=auth_headers,
    )
    search_id = recorded.json()["id"]

    scheduled = await client.put(
        f"/api/v1/me/searches/{search_id}/schedule",
        json={"trigger": {"type": "interval", "params": {"every_minutes": 60}}},
        headers=auth_headers,
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["kind"] == "user_saved_search"

    # A mapped posting exists (direct insert) → the run notifies.
    jobs = (await client.get("/api/v1/jobs", headers=auth_headers)).json()
    from app.models.posting_model import JobSource

    source = JobSource(
        key="synth",
        connector_key="csv",
        config={"url": "https://x/f.csv"},
        enabled=True,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    posting = JobPosting(
        source_id=source.id,
        external_id="match-1",
        title="QA Automation Engineer",
        org="SynthCo",
        location={"remote": True},
        url="https://jobs.example/1",
        content_hash="hash-match-1",
        catalog_job_id=uuid_mod.UUID(jobs[0]["id"]),
        status="mapped",
        posted_at=_now(),
    )
    db.add(posting)
    await db.commit()

    schedule = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == ScheduleKind.USER_SAVED_SEARCH.value,
                    Schedule.owner_user_id == _uid(auth_headers),
                )
            )
        )
        .scalars()
        .first()
    )
    schedule.next_run_at = _now() - timedelta(minutes=1)
    await db.commit()

    service = SchedulerService(db)
    assert await service.tick() == 1
    worker = JobWorker(db)
    while await worker.run_once():
        pass

    notifications = (
        await client.get("/api/v1/notifications", headers=auth_headers)
    ).json()
    assert any(
        n["kind"] == "new_posting_match" and "found 1 new match" in n["title"]
        for n in notifications["items"]
    )

    removal = await client.put(
        f"/api/v1/me/searches/{search_id}/schedule",
        json={"trigger": None},
        headers=auth_headers,
    )
    assert removal.status_code == 200
    assert removal.json() == {"removed": True}


# -------------------------------------------------------- check-ins + sweep


async def test_checkin_uses_scheduler(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    status = (await client.get("/api/v1/me/checkin", headers=auth_headers)).json()
    assert status["due"] is False
    schedule = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.owner_user_id == _uid(auth_headers),
                    Schedule.kind == ScheduleKind.USER_CHECKIN.value,
                )
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None

    # Force due → the banner reports due; skip advances via the trigger.
    schedule.next_run_at = _now() - timedelta(minutes=1)
    await db.commit()
    status = (await client.get("/api/v1/me/checkin", headers=auth_headers)).json()
    assert status["due"] is True

    skipped = await client.post(
        "/api/v1/me/checkin", json={"skipped": True}, headers=auth_headers
    )
    assert skipped.status_code == 200
    await db.refresh(schedule)
    assert schedule.next_run_at > _now()
    assert schedule.last_status == "ok"


async def test_stale_refit_sweep(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.services.job_service import JobService

    job = await JobService(db).get_by_code_or_id("software-developer")
    await FitService(db).upsert_fit(
        _uid(auth_headers), job, FitResult(score=7.0, breakdown={}, gates=[])
    )
    # Age one insight: its fit_version is behind → the sweep must pick the user.
    insight = (
        (
            await db.execute(
                select(MatchInsight).where(MatchInsight.user_id == _uid(auth_headers))
            )
        )
        .scalars()
        .first()
    )
    insight.fit_version = FIT_VERSION - 1
    await db.commit()

    service = SchedulerService(db)
    schedule = await service.ensure_schedule(
        kind=ScheduleKind.SYSTEM_REFIT_SWEEP.value,
        owner_user_id=None,
        task="fit_refit",
        trigger={"type": "boot_stale", "params": {"older_than_minutes": 60 * 24 * 7}},
        payload={"scope": "stale"},
        misfire_policy="skip",
        default_interval_minutes=60,
    )
    schedule.next_run_at = _now() - timedelta(minutes=1)
    await db.commit()
    assert await service.tick() == 1
    worker = JobWorker(db)
    while await worker.run_once():
        pass

    await db.refresh(insight)
    assert insight.fit_version == FIT_VERSION
