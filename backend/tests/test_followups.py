"""Application follow-ups (plan 116.3): cadence-driven nudges and
milestone check-ins from `followup_rules`, the scheduler projection
(`applications.next_followup_at`), notification deep links, and the
settings surface."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.models.application_model import Application
from app.models.background_job_model import BackgroundJob
from app.models.engagement_model import Notification, NotificationKind
from app.models.enums import BackgroundJobType, ScheduleKind
from app.models.followup_model import FollowupRule
from app.models.posting_model import JobPosting, PostingInteraction
from app.models.schedule_model import Schedule
from app.services.job_worker import JobWorker
from app.services.postings.applications_service import normalize_cadence
from app.services.postings.followups_service import sweep
from app.services.scheduler.runner import SchedulerService
from tests.conftest import _make_posting, _uid


async def _applied(db, headers, source, *, days_ago=8, stage=None) -> Application:
    posting: JobPosting = await _make_posting(
        db, source, external_id=f"fu-{days_ago}-{stage or 'applied'}"
    )
    user_id = UUID(_uid(headers))
    applied_at = datetime.now(UTC) - timedelta(days=days_ago)
    db.add(
        PostingInteraction(
            user_id=user_id,
            posting_id=posting.id,
            seen_at=applied_at,
        )
    )
    application = Application(
        user_id=user_id,
        posting_id=posting.id,
        applied_at=applied_at,
        stage=stage or "applied",
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return application


async def _notes(db, kind_key="followup_due") -> list[Notification]:
    kind = await db.execute(select(NotificationKind).where(NotificationKind.key == kind_key))
    kind_row = kind.scalars().first()
    if kind_row is None:
        return []
    rows = await db.execute(select(Notification).where(Notification.kind_id == kind_row.id))
    return list(rows.scalars().all())


async def test_sweep_nudges_once_per_cadence_step(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=8)
    assert await sweep(db) == 1
    notes = await _notes(db)
    assert len(notes) == 1
    assert notes[0].dedup_key.endswith(":cadence:7")

    assert await sweep(db) == 0, "re-running must not double-send"
    await db.execute(
        Application.__table__.update().values(applied_at=datetime.now(UTC) - timedelta(days=15))
    )
    await db.commit()
    assert await sweep(db) == 1
    assert (await _notes(db))[-1].dedup_key.endswith(":cadence:14")
    assert await sweep(db) == 0


async def test_cadence_is_configurable(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=8)
    patched = await client.patch(
        "/api/v1/me/followups",
        json={"cadence_days": [10, 20]},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["cadence_days"] == [10, 20]
    assert await sweep(db) == 0, "8d < the configured 10d cadence"
    await db.execute(
        Application.__table__.update().values(applied_at=datetime.now(UTC) - timedelta(days=11))
    )
    await db.commit()
    assert await sweep(db) == 1
    assert (await _notes(db))[-1].dedup_key.endswith(":cadence:10")


async def test_disabled_rules_stop_the_sweep(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=8)
    response = await client.patch(
        "/api/v1/me/followups", json={"enabled": False}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert await sweep(db) == 0
    application = (await db.execute(select(Application))).scalars().one()
    assert application.next_followup_at is None


async def test_stage_milestones_get_checkins(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=20, stage="interview")
    assert await sweep(db) == 1
    notes = await _notes(db)
    assert "interview" in notes[0].title.lower()
    assert "stage:interview" in notes[0].dedup_key
    assert notes[0].payload["link"] == (
        f"/applications?application={notes[0].payload['application_id']}"
    )
    assert await sweep(db) == 0


async def test_milestone_toggle_falls_back_to_the_regular_cadence(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    response = await client.patch(
        "/api/v1/me/followups",
        json={"milestone_checkins": False},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    await _applied(db, auth_headers, source, days_ago=20, stage="offer")
    assert await sweep(db) == 2, "both configured cadence steps are due"
    notes = await _notes(db)
    assert any(note.dedup_key.endswith(":cadence:7") for note in notes)
    assert any(note.dedup_key.endswith(":cadence:14") for note in notes)
    assert all("offer" not in note.dedup_key for note in notes)


async def test_closed_applications_are_skipped(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    application = await _applied(db, auth_headers, source, days_ago=8)
    application.closed_at = datetime.now(UTC)
    application.outcome = "withdrawn"
    await db.commit()
    assert await sweep(db) == 0


async def test_sweep_maintains_next_followup_at(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    await _applied(db, auth_headers, source, days_ago=8)
    await sweep(db)
    application = (await db.execute(select(Application))).scalars().one()
    assert application.next_followup_at is not None
    expected = application.applied_at + timedelta(days=14)
    assert abs(application.next_followup_at - expected) < timedelta(seconds=2)

    await db.execute(
        Application.__table__.update().values(applied_at=datetime.now(UTC) - timedelta(days=30))
    )
    await db.refresh(application)
    await sweep(db)
    await sweep(db)
    await db.refresh(application)
    assert application.next_followup_at is None


async def test_followups_surface_reads_rules_and_state(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, source
):
    application = await _applied(db, auth_headers, source, days_ago=8)
    await sweep(db)
    response = await client.get("/api/v1/me/followups", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rules"] == {
        "enabled": True,
        "cadence_days": [7, 14],
        "milestone_checkins": True,
        "channels": {},
    }
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["application_id"] == str(application.id)
    assert item["sent_steps"] == ["cadence:7"]
    assert item["next_step"] == "follow-up"


async def test_rule_patch_validates_cadence_and_channels(client, auth_headers, profile_ready, db):
    empty = await client.patch(
        "/api/v1/me/followups", json={"cadence_days": []}, headers=auth_headers
    )
    assert empty.status_code == 400
    negative = await client.patch(
        "/api/v1/me/followups", json={"cadence_days": [0, 5]}, headers=auth_headers
    )
    assert negative.status_code == 400
    unknown = await client.patch(
        "/api/v1/me/followups",
        json={"channels": {"sms": ["in_app"]}},
        headers=auth_headers,
    )
    assert unknown.status_code == 400
    ok = await client.patch(
        "/api/v1/me/followups",
        json={"channels": {"followup_due": ["in_app"]}},
        headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["channels"] == {"followup_due": ["in_app"]}
    rule = (await db.execute(select(FollowupRule))).scalars().one()
    assert rule.channels == {"followup_due": ["in_app"]}


async def test_scheduler_provisions_and_enqueues_the_sweep(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from datetime import timedelta as td

    service = SchedulerService(db)
    await service.ensure_system_schedules()
    rows = (
        (
            await db.execute(
                select(Schedule).where(Schedule.kind == ScheduleKind.SYSTEM_FOLLOWUPS.value)
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
        .values(next_run_at=datetime.now(UTC) - td(minutes=1))
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


def test_cadence_normalization():
    assert normalize_cadence(None) == [7, 14]
    assert normalize_cadence([14, 7, 7]) == [7, 14]
    assert normalize_cadence([0, -3, 30, 999]) == [30, 120]
