"""Plan 134 — the source run ledger: one row per ingestion attempt,
visible through the runs endpoint (the management page's history)."""

import uuid
from typing import ClassVar

import pytest
from sqlalchemy import select

from app.extensions.sdk import ConnectorCapabilities, ConnectorError, ConnectorResult
from app.models.posting_model import JobSource, SourceRun
from app.services.postings.postings_service import run_sync_job, sync_source
from tests.conftest import SyntheticConnector, register_connector, reset_registry


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


def test_run_status_errors_outrank_the_radar_note():
    """A radar run always carries a rotation note — provider partials on
    top of it are degraded, never 'skipped' (plan 174 follow-up: the
    2026-11-01 12:53 indeed run burned 42s on two dead SERPs and was
    labelled skipped, hiding the failure)."""
    from app.services.postings.postings_service import _run_status

    assert _run_status({"error": "boom"}) == "failed"
    assert (
        _run_status(
            {
                "synced": 0,
                "note": "searching radar group(s) 1-2/4: x @ Athens",
                "errors": [{"code": "provider", "detail": "search page rendered no job cards"}],
            }
        )
        == "degraded"
    )
    assert (
        _run_status({"synced": 0, "note": "radar has no keywords yet — nothing to search"})
        == "skipped"
    )
    assert _run_status({"synced": 3}) == "ok"


# ------------------------------------------------- operator-action pause


class TypedErrorConnector(SyntheticConnector):
    """Returns one typed partial error — the shape a blocked provider has."""

    key = "typed-error"
    capabilities = ConnectorCapabilities(supports_incremental=True)
    error: ClassVar[ConnectorError] = ConnectorError(
        code="provider", detail="Indeed blocked this browser (block page)", retryable="no"
    )

    async def fetch(self, config, state, *, transport=None, **_kw):
        return ConnectorResult(next_state={}, partial_errors=[TypedErrorConnector.error])


@pytest.fixture
def typed_error_connector():
    register_connector(TypedErrorConnector())
    yield TypedErrorConnector
    reset_registry()


async def _admin(db):
    from app.models.user_model import User

    user = User(email=f"pause-admin-{uuid.uuid4().hex[:8]}@example.com", is_admin=True)
    db.add(user)
    await db.commit()
    return user


async def test_blocked_provider_pauses_the_source_and_alerts_admins(
    db, client, kinds, typed_error_connector
):
    """A non-retryable block must stop the scheduler from retrying hourly —
    the source pauses with the reason, admins get one notification, and a
    second failing run does not re-notify."""
    from app.models.engagement_model import Notification

    admin = await _admin(db)
    src = await _source(db, "pause-blocked", "typed-error")

    report = await sync_source(db, src)
    assert report["errors"][0]["code"] == "provider"
    await db.refresh(src)
    assert src.paused_at is not None
    assert "paused" in src.error

    notes = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.dedup_key == f"source-paused:{src.id}:{admin.id}",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notes) == 1
    assert notes[0].kind_id is not None
    assert "paused" in notes[0].title.lower()

    await sync_source(db, src)
    again = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.dedup_key == f"source-paused:{src.id}:{admin.id}",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(again) == 1, "an already-paused source never re-notifies"


async def test_retryable_provider_error_does_not_pause(db, typed_error_connector):
    """'No job cards' is retryable — the next run must still be attempted."""
    typed_error_connector.error = ConnectorError(
        code="provider",
        detail="search page rendered no job cards — no results for this search",
        retryable="yes",
    )
    src = await _source(db, "pause-retryable", "typed-error")
    try:
        await sync_source(db, src)
        await db.refresh(src)
        assert src.paused_at is None
    finally:
        typed_error_connector.error = ConnectorError(
            code="provider", detail="Indeed blocked this browser (block page)", retryable="no"
        )


async def test_paused_source_is_skipped_by_the_sync_job(db, typed_error_connector):
    """After the pause, the hourly job leaves the source alone — no new
    run rows, no browser launches."""
    src = await _source(db, "pause-skipped", "typed-error")
    await sync_source(db, src)
    await db.refresh(src)
    assert src.paused_at is not None
    before = (
        (await db.execute(select(SourceRun).where(SourceRun.source_id == src.id))).scalars().all()
    )

    await run_sync_job(db, {})
    after = (
        (await db.execute(select(SourceRun).where(SourceRun.source_id == src.id))).scalars().all()
    )
    assert len(after) == len(before)


async def test_new_posting_linking_an_existing_org_ingests(db, synthetic_connector):
    """Regression (plan 176 follow-up): a NEW posting whose org resolved to
    an EXISTING org crashed the whole sync — the change journal received
    posting.id before the first flush ('badly formed hexadecimal UUID').
    The preset ATS tenants exposed it: their postings match orgs that
    other sources already created."""
    from app.models.experience_model import Organization
    from app.models.posting_model import JobPosting
    from app.services.catalog.company_names import name_key

    db.add(
        Organization(
            key="synthco",
            name="SynthCo",
            name_key=name_key("SynthCo"),
            initials_key="SC",
        )
    )
    await db.commit()

    src = await _source(db, "org-link-sync", "synthetic")
    report = await sync_source(db, src, trigger="manual")
    assert report.get("error") is None, report
    assert report["synced"] == 1

    await db.refresh(src)
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.source_id == src.id))).scalars().one()
    )
    assert posting.org_id is not None, "the exact-name org link still ran"
    row = (await db.execute(select(SourceRun).where(SourceRun.source_id == src.id))).scalars().one()
    assert row.status == "ok"


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


async def test_finish_run_bounds_errors_count_when_summary_present(db, synthetic_connector):
    """Plan 003 amendment 5: with a run_summary on the report the errors
    list is count-bounded first — the summary survives, errors truncate."""
    from datetime import UTC, datetime

    from app.services.postings.postings_service import (
        RUN_ERRORS_WITH_SUMMARY,
        _begin_run,
        _finish_run,
    )

    src = await _source(db, "runs-summary", "synthetic")
    started = datetime.now(UTC)
    row = await _begin_run(db, src, trigger="manual", started=started, stage="fetching")
    summary = {"schema": 1, "mode": "guest", "rows": {"kept": 3, "capped": 0}}
    errors = [{"code": "provider", "detail": f"problem {i}"} for i in range(30)]
    await _finish_run(
        db,
        row.id,
        started=started,
        report={"synced": 3, "errors": errors, "run_summary": summary},
    )
    await db.refresh(row)
    assert row.report["run_summary"] == summary
    assert len(row.report["errors"]) == RUN_ERRORS_WITH_SUMMARY
    assert row.report["errors_truncated"] is True


async def test_finish_run_pops_errors_when_report_still_oversize(db, synthetic_connector):
    """The whole-report 8 KB bound still wins: a summary plus a fat report
    pops the errors entirely — the summary never pays for the bound."""
    from datetime import UTC, datetime

    from app.services.postings.postings_service import _begin_run, _finish_run

    src = await _source(db, "runs-fat", "synthetic")
    started = datetime.now(UTC)
    row = await _begin_run(db, src, trigger="manual", started=started, stage="fetching")
    summary = {"schema": 1, "mode": "guest"}
    await _finish_run(
        db,
        row.id,
        started=started,
        report={
            "synced": 1,
            "note": "x" * 7_700,
            "errors": [{"code": "provider", "detail": "d" * 400}],
            "run_summary": summary,
        },
    )
    await db.refresh(row)
    assert row.report["run_summary"] == summary
    assert "errors" not in row.report
    assert row.report["errors_truncated"] is True


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


async def test_runs_endpoint_closes_a_ghost_running_row_on_read(
    db, synthetic_connector, client, auth_headers
):
    """A crashed run must not make the page claim "Running now" until the
    next sync — reading the ledger closes the ghost (same cutoff the next
    run uses)."""
    from datetime import UTC, datetime, timedelta

    from app.models.posting_model import SourceRun
    from app.services.postings.postings_service import STALE_RUN_MINUTES

    created = await client.post(
        "/api/v1/admin/postings/sources",
        json={"key": "runs-ghost", "connector_key": "synthetic", "config": {}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]
    src = (await db.execute(select(JobSource).where(JobSource.key == "runs-ghost"))).scalars().one()

    ghost = SourceRun(
        source_id=src.id,
        trigger="scheduled",
        status="running",
        started_at=datetime.now(UTC) - timedelta(minutes=STALE_RUN_MINUTES + 10),
        report={"stage": "ingesting"},
    )
    db.add(ghost)
    await db.commit()

    rows = (
        await client.get(f"/api/v1/admin/postings/sources/{source_id}/runs", headers=auth_headers)
    ).json()
    assert rows[0]["status"] == "failed"
    assert "interrupted" in rows[0]["error"]
    assert rows[0]["finished_at"] is not None

    fresh = SourceRun(
        source_id=src.id,
        trigger="scheduled",
        status="running",
        started_at=datetime.now(UTC),
        report={"stage": "fetching"},
    )
    db.add(fresh)
    await db.commit()
    rows = (
        await client.get(f"/api/v1/admin/postings/sources/{source_id}/runs", headers=auth_headers)
    ).json()
    assert rows[0]["status"] == "running", "a live run is never healed away"
