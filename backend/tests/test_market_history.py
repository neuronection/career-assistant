""": demand history — capture, idempotency, trend, endpoint."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.enums import BackgroundJobType, ScheduleKind
from app.models.job_model import Job
from app.models.market_model import MarketSnapshot
from app.models.posting_model import JobPosting, JobSource
from app.services import market_history_service as mhs
from app.services.job_worker import JobWorker


async def _add_posting(db, job: Job, index: int = 0) -> None:
    source = await db.execute(select(JobSource).limit(1))
    row = source.scalars().first()
    if row is None:
        row = JobSource(key=f"src-{uuid4().hex[:8]}", connector_key="rss")
        db.add(row)
        await db.flush()
    db.add(
        JobPosting(
            source_id=row.id,
            external_id=f"ext-{job.id}-{index}",
            title=f"Role {index}",
            status="mapped",
            catalog_job_id=job.id,
            salary_min=Decimal(40000 + index * 1000),
            salary_currency="EUR",
            posted_at=datetime(2026, 8, 1 + index % 20, tzinfo=timezone.utc),
            content_hash=f"h-{job.id}-{index}",
        )
    )
    await db.flush()


async def _seeded_job(db) -> Job:
    return (
        (await db.execute(select(Job).where(Job.code == "software-developer")))
        .scalars()
        .first()
    )


async def test_capture_scope_is_same_day_idempotent(db, seeded_catalog):
    job = await _seeded_job(db)
    await _add_posting(db, job)

    first = await mhs.capture_scope(db, job_id=job.id)
    second = await mhs.capture_scope(db, job_id=job.id)
    assert first.id == second.id
    rows = (await db.execute(select(MarketSnapshot))).scalars().all()
    assert len(rows) == 1
    assert rows[0].scope_kind == "job"
    assert rows[0].sample_size >= 1
    assert rows[0].thin_sample is False or rows[0].thin_sample is True


async def test_capture_scope_rejects_both_and_neither(db, seeded_catalog):
    job = await _seeded_job(db)
    with pytest.raises(ValueError):
        await mhs.capture_scope(db, family_key="tech", job_id=job.id)
    with pytest.raises(ValueError):
        await mhs.capture_scope(db)


async def test_capture_all_covers_families_and_jobs(db, seeded_catalog):
    job = await _seeded_job(db)
    await _add_posting(db, job, index=0)
    await _add_posting(db, job, index=1)

    captured = await mhs.capture_all(db)
    assert captured >= 2  # the family scope + the job scope
    kinds = {
        r.scope_kind for r in (await db.execute(select(MarketSnapshot))).scalars().all()
    }
    assert kinds == {"family", "job"}


async def test_trend_returns_ordered_history(db, seeded_catalog):
    job = await _seeded_job(db)
    await _add_posting(db, job)
    await mhs.capture_scope(db, job_id=job.id)
    history = await mhs.trend(db, job_id=job.id)
    assert len(history) == 1
    assert history[0]["sample_size"] >= 1
    assert await mhs.trend(db, family_key="no-such-family-xyz") == []


async def test_worker_handler_captures(db, seeded_catalog):
    job = await _seeded_job(db)
    await _add_posting(db, job)
    from app.models.enums import BackgroundJobStatus
    from app.services.job_worker import enqueue

    enqueued = await enqueue(
        db, BackgroundJobType.MARKET_HISTORY_CAPTURE.value, {}, user_id=None
    )
    worker = JobWorker(db)
    assert await worker.run_once()
    await db.refresh(enqueued)
    assert enqueued.status == BackgroundJobStatus.SUCCEEDED.value
    rows = (await db.execute(select(MarketSnapshot))).scalars().all()
    assert rows, "capture job produced no snapshots"


async def test_system_schedule_slot_provisioned(db):
    from app.services.scheduler.runner import SchedulerService

    await SchedulerService(db).ensure_system_schedules()
    from app.models.schedule_model import Schedule

    rows = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == ScheduleKind.SYSTEM_MARKET_HISTORY.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_trend_endpoint_validates_and_serves(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    job = await _seeded_job(db)
    await _add_posting(db, job)
    await mhs.capture_scope(db, job_id=job.id)

    both = await client.get(
        f"/api/v1/market/trend?family_key=tech&job_id={job.id}", headers=auth_headers
    )
    assert both.status_code == 422

    ok = await client.get(f"/api/v1/market/trend?job_id={job.id}", headers=auth_headers)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert len(body) == 1
    assert body[0]["capture_date"]
