"""Plan 134 — the source run ledger: one row per ingestion attempt,
visible through the runs endpoint (the management page's history)."""

import uuid

from sqlalchemy import select

from app.models.posting_model import JobSource, SourceRun
from app.services.postings.postings_service import run_sync_job, sync_source


async def _source(db, key: str, connector_key: str, **extra) -> JobSource:
    src = JobSource(key=key, connector_key=connector_key, config={}, **extra)
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


async def test_sync_records_run_rows_newest_first(db, synthetic_connector, client, auth_headers):
    created = await client.post(
        "/api/v1/admin/postings/sources",
        json={"key": "runs-1", "connector_key": "synthetic", "config": {}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]
    src = (await db.execute(select(JobSource).where(JobSource.key == "runs-1"))).scalars().one()

    first = await sync_source(db, src, trigger="manual")
    assert first["synced"] == 1
    second = await sync_source(db, src)
    assert second["synced"] in (0, 1)

    rows = (
        (
            await db.execute(
                select(SourceRun)
                .where(SourceRun.source_id == uuid.UUID(source_id))
                .order_by(SourceRun.started_at.desc())
            )
        )
        .scalars()
        .all()
    )
    assert [row.status for row in rows] == ["ok", "ok"]
    assert rows[0].trigger == "scheduled"
    assert rows[1].trigger == "manual"
    assert rows[1].items_synced == 1
    assert rows[1].duration_ms >= 0
    assert rows[1].report is not None

    listed = await client.get(
        f"/api/v1/admin/postings/sources/{source_id}/runs", headers=auth_headers
    )
    assert listed.status_code == 200
    assert [row["status"] for row in listed.json()] == ["ok", "ok"]
    assert listed.json()[1]["trigger"] == "manual"


async def test_failed_sync_is_recorded(db, synthetic_connector):
    src = await _source(db, "runs-fail", "missing-connector")
    report = await sync_source(db, src, trigger="manual")
    assert report.get("error")
    row = (await db.execute(select(SourceRun).where(SourceRun.source_id == src.id))).scalars().one()
    assert row.status == "failed"
    assert row.error
    assert row.items_synced == 0


async def test_skipped_radar_sync_is_recorded(db, dynamic_connector):
    src = await _source(db, "runs-skip", "dynamic-synthetic", query_mode="radar")
    report = await sync_source(db, src)
    assert report["synced"] == 0 and report.get("note")
    row = (await db.execute(select(SourceRun).where(SourceRun.source_id == src.id))).scalars().one()
    assert row.status == "skipped"


async def test_run_sync_job_passes_trigger(db, synthetic_connector, client, auth_headers):
    created = await client.post(
        "/api/v1/admin/postings/sources",
        json={"key": "runs-job", "connector_key": "synthetic", "config": {}},
        headers=auth_headers,
    )
    source_id = created.json()["id"]
    totals = await run_sync_job(db, {"source_id": source_id, "trigger": "manual"})
    assert totals["synced"] == 1
    row = (
        (await db.execute(select(SourceRun).where(SourceRun.source_id == uuid.UUID(source_id))))
        .scalars()
        .one()
    )
    assert row.trigger == "manual"


async def test_run_row_is_live_from_start_to_finish(db, synthetic_connector):
    """The ledger row opens at run START (status running + stage) and
    settles at the end — the management page shows live state."""
    from datetime import UTC, datetime, timedelta

    from app.services.postings.postings_service import (
        _begin_run,
        _finish_run,
        _update_run_progress,
    )

    src = await _source(db, "runs-live", "synthetic")
    started = datetime.now(UTC)
    row = await _begin_run(db, src, trigger="manual", started=started, stage="fetching")
    assert row.status == "running"
    assert row.report == {"stage": "fetching"}
    assert row.finished_at is None

    await _update_run_progress(db, row.id, stage="ingesting")
    await db.refresh(row)
    assert row.report["stage"] == "ingesting"

    await _finish_run(
        db,
        row.id,
        started=started - timedelta(seconds=2),
        report={"synced": 3, "errors": []},
    )
    await db.refresh(row)
    assert row.status == "ok"
    assert row.items_synced == 3
    assert row.finished_at is not None
    assert row.duration_ms >= 0


async def test_stale_running_rows_close_as_interrupted(db, synthetic_connector):
    """A crash never leaves a ghost: the next run closes stale running
    rows and opens its own."""
    from datetime import UTC, datetime, timedelta

    from app.models.posting_model import SourceRun
    from app.services.postings.postings_service import STALE_RUN_MINUTES, _begin_run

    src = await _source(db, "runs-stale", "synthetic")
    stale_started = datetime.now(UTC) - timedelta(minutes=STALE_RUN_MINUTES + 5)
    stale = SourceRun(
        source_id=src.id,
        trigger="scheduled",
        status="running",
        started_at=stale_started,
        report={"stage": "fetching"},
    )
    db.add(stale)
    await db.commit()

    row = await _begin_run(
        db, src, trigger="scheduled", started=datetime.now(UTC), stage="fetching"
    )
    assert row.status == "running"
    await db.refresh(stale)
    assert stale.status == "failed"
    assert "interrupted" in stale.error
