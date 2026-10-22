"""Demand import wall (plan 122 Phase 3): the dormant
`SYSTEM_DEMAND_IMPORT` slot becomes real — market sources feed salary and
outlook observations into `market_snapshots` and `jobs.demand` with
field-level provenance. Fixtures are the documented BLS v2 / Adzuna history
wire shapes; the transport is injected, so no test opens a socket.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType, ScheduleKind
from app.models.job_model import Job
from app.models.market_model import MarketSnapshot
from app.models.posting_model import JobSource
from app.models.schedule_model import Schedule
from app.services.demand_import_service import (
    MarketSourceConfig,
    dataset_request,
    ensure_demand_source,
    parse_adzuna_payload,
    parse_bls_payload,
    run_demand_import,
)
from app.services.job_worker import JobWorker, enqueue
from app.services.postings_service import run_sync_job
from app.services.scheduler.runner import KIND_TASKS, SchedulerService

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demand"
BLS_BODY = (FIXTURES / "bls_series.json").read_text(encoding="utf-8")
ADZUNA_BODY = (FIXTURES / "adzuna_history.json").read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, body: str, status: int = 200):
        self.status = status
        self.body = body
        self.headers = {"content-type": "application/json"}
        self.url = ""
        self.truncated = False


def fake_transport(body: str, *, status: int = 200):
    calls: list[tuple[str, str, dict, dict | None]] = []

    async def transport(method: str, url: str, headers: dict, payload: dict | None = None):
        calls.append((method, url, dict(headers), payload))
        return FakeResponse(body, status)

    return transport, calls


def bls_config(**extra) -> MarketSourceConfig:
    return MarketSourceConfig(
        dataset="bls",
        series={
            "LNS14000000": {"job_code": "software-developer", "metric": "employment"},
            "CES0500000003": {"job_code": "software-developer", "metric": "salary_median"},
        },
        **extra,
    )


def test_bls_parse_metrics_and_outlook():
    observations, errors = parse_bls_payload(BLS_BODY, bls_config())
    assert errors == []
    assert len(observations) == 2
    employment = next(item for item in observations if item.metric == "employment")
    salary = next(item for item in observations if item.metric == "salary_median")
    assert employment.job_code == "software-developer"
    assert employment.value == 4.3
    assert employment.outlook == "growing"
    assert employment.observed_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert employment.source == "BLS"
    assert salary.value == 36.5
    assert salary.outlook is None


def test_adzuna_parse_history_trend():
    observations, errors = parse_adzuna_payload(
        ADZUNA_BODY,
        MarketSourceConfig(dataset="adzuna", country="de", what="software"),
        job_code="software-developer",
    )
    assert errors == []
    assert len(observations) == 1
    observation = observations[0]
    assert observation.metric == "employment"
    assert observation.value == 1500
    assert observation.outlook == "hot"
    assert observation.observed_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert observation.source == "Adzuna"


def test_dataset_requests_carry_secret_slots():
    method, url, _headers, body = dataset_request(
        bls_config(start_year=2024, end_year=2026), {"bls_key": "bls-secret"}
    )
    assert method == "POST"
    assert url == "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    assert body is not None
    assert body["seriesid"] == ["LNS14000000", "CES0500000003"]
    assert body["registrationkey"] == "bls-secret"
    assert body["startyear"] == "2024"

    method, url, _headers, body = dataset_request(
        MarketSourceConfig(dataset="adzuna", country="de", what="software"),
        {"adzuna_app_id": "app-id", "adzuna_app_key": "app-key"},
    )
    assert method == "GET"
    assert url.startswith("https://api.adzuna.com/v1/api/jobs/de/history?")
    assert "app_id=app-id" in url and "app_key=app-key" in url
    assert body is None


async def test_run_demand_import_writes_demand_and_snapshot(db, seeded_catalog):
    transport, calls = fake_transport(BLS_BODY)
    source = JobSource(
        key="market-demand",
        connector_key="demand_data",
        kind="market",
        config=bls_config().model_dump(mode="json"),
        enabled=True,
    )
    db.add(source)
    await db.commit()

    result = await run_demand_import(db, {}, transport=transport)
    assert result["sources"] == 1
    assert result["observations"] == 2
    assert result["jobs_updated"] == 2, "both metrics update the same job"
    assert result["errors"] == []
    assert len(calls) == 1

    job = (await db.execute(select(Job).where(Job.code == "software-developer"))).scalars().first()
    assert job is not None
    demand = job.attributes["demand"]
    assert demand["outlook"] == "growing"
    assert demand["sources"]["employment"]["source"] == "BLS"
    assert demand["sources"]["employment"]["dataset"] == "bls"
    assert demand["sources"]["salary_median"]["value"] == 36.5
    assert demand["sources"]["salary_median"]["url"].startswith("https://api.bls.gov")

    snapshot = (
        (await db.execute(select(MarketSnapshot).where(MarketSnapshot.job_id == job.id)))
        .scalars()
        .first()
    )
    assert snapshot is not None
    assert snapshot.payload["demand"]["employment"]["source"] == "BLS"
    assert snapshot.thin_sample is True
    assert snapshot.sample_size == 0

    await db.refresh(source)
    assert source.last_status == "ok"
    assert source.last_run_at is not None


async def test_run_demand_import_records_a_degraded_source(db, seeded_catalog):
    transport, _ = fake_transport("<html>busy</html>", status=503)
    source = JobSource(
        key="market-demand",
        connector_key="demand_data",
        kind="market",
        config=bls_config().model_dump(mode="json"),
        enabled=True,
    )
    db.add(source)
    await db.commit()
    result = await run_demand_import(db, {}, transport=transport)
    assert result["jobs_updated"] == 0
    assert result["errors"]
    await db.refresh(source)
    assert source.last_status == "degraded"


async def test_ensure_demand_source_is_idempotent(db):
    first = await ensure_demand_source(db)
    await db.commit()
    second = await ensure_demand_source(db)
    assert first.id == second.id
    assert first.kind == "market"
    assert first.schedule_kind == ScheduleKind.SYSTEM_DEMAND_IMPORT.value


async def test_scheduler_slot_enqueues_demand_import(db):
    assert (
        KIND_TASKS[ScheduleKind.SYSTEM_DEMAND_IMPORT.value] == BackgroundJobType.DEMAND_IMPORT.value
    )
    service = SchedulerService(db)
    await service.ensure_system_schedules()
    schedule = (
        (
            await db.execute(
                select(Schedule).where(Schedule.kind == ScheduleKind.SYSTEM_DEMAND_IMPORT.value)
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None
    assert schedule.task == BackgroundJobType.DEMAND_IMPORT.value


async def test_demand_import_worker_path(db, seeded_catalog, monkeypatch):
    async def no_fetch(source, *, transport=None):
        return [], []

    monkeypatch.setattr("app.services.demand_import_service.fetch_demand_observations", no_fetch)
    source = JobSource(
        key="market-demand",
        connector_key="demand_data",
        kind="market",
        config=bls_config().model_dump(mode="json"),
        enabled=True,
    )
    db.add(source)
    await db.commit()
    job = await enqueue(db, BackgroundJobType.DEMAND_IMPORT.value, {}, user_id=None)
    worker = JobWorker(db)
    assert await worker.run_once() is True
    fresh = await db.get(BackgroundJob, job.id)
    assert fresh is not None
    assert fresh.status == BackgroundJobStatus.SUCCEEDED.value


async def test_posting_sync_skips_market_and_paused_sources(db):
    paused = JobSource(
        key="paused-posting",
        connector_key="rss",
        kind="posting",
        config={"url": "https://example.org/feed.xml"},
        enabled=True,
        paused_at=datetime.now(UTC),
    )
    market = JobSource(
        key="market-demand",
        connector_key="demand_data",
        kind="market",
        config=MarketSourceConfig().model_dump(mode="json"),
        enabled=True,
    )
    db.add_all([paused, market])
    await db.commit()
    result = await run_sync_job(db, {})
    assert result["sources"] == 0
