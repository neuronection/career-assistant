"""Demand import (plan 122 Phase 3): external salary and outlook datasets
into `market_snapshots` and `jobs.demand`, with field-level provenance.

The scheduler's `SYSTEM_DEMAND_IMPORT` slot enqueues `demand_import`; the
handler walks enabled `job_sources` rows of kind `market` and applies each
observation. Datasets are a registry of small adapters over the guarded
transport (the same SSRF/egress/cap discipline as search and connectors):

- ``bls`` — the BLS Public Data API v2 (POST, no key for limited queries;
  an optional ``bls_key`` secret slot raises the quota). Each configured
  series maps to a catalog job code and a metric.
- ``adzuna`` — Adzuna's job-market history (GET; ``adzuna_app_id`` /
  ``adzuna_app_key`` secret slots), monthly posting counts per query.

Tests inject a transport and drive fixtures — no live network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ValidationError
from app.extensions.polite_http import PoliteHttpError
from app.extensions.sdk import ConnectorError
from app.models.enums import DemandOutlook, HealthStatus, ScheduleKind
from app.models.job_model import Job
from app.models.market_model import MarketSnapshot
from app.models.posting_model import JobSource

DATASETS = ("bls", "adzuna")
DATASET_DOMAINS = {
    "bls": frozenset({"api.bls.gov"}),
    "adzuna": frozenset({"api.adzuna.com"}),
}
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
ADZUNA_HISTORY_URL = "https://api.adzuna.com/v1/api/jobs/{country}/history"
DEMAND_SOURCE_KEY = "market-demand"
DEMAND_SOURCE_CONNECTOR = "demand_data"
DEFAULT_DATASET = "bls"


class SeriesMapping(BaseModel):
    job_code: str = Field(min_length=1, max_length=120)
    metric: Literal["employment", "salary_median"] = "employment"


class MarketSourceConfig(BaseModel):
    """One market source's dataset selection (stored in `job_sources.config`)."""

    dataset: str = Field(default=DEFAULT_DATASET, pattern="^(bls|adzuna)$")
    series: dict[str, SeriesMapping] = Field(default_factory=dict)
    country: str = Field(default="de", min_length=2, max_length=8)
    what: str = Field(default="", max_length=120)
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)


class DemandObservation(BaseModel):
    """One external salary/outlook fact with its provenance."""

    job_code: str = Field(min_length=1, max_length=120)
    metric: Literal["employment", "salary_median"]
    value: float | None = None
    outlook: str | None = None
    unit: str = ""
    currency: str | None = None
    period: str | None = None
    observed_at: datetime
    source: str
    dataset: str
    source_url: str = ""


def validate_market_config(config: dict) -> dict:
    """Validated JSONB for a `kind='market'` source's config."""
    try:
        return MarketSourceConfig.model_validate(config or {}).model_dump(mode="json")
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc


def _outlook(values: list[float]) -> str:
    if len(values) < 2:
        return DemandOutlook.STABLE.value
    newest, oldest = values[0], values[-1]
    if oldest <= 0:
        return DemandOutlook.STABLE.value
    change = (newest - oldest) / oldest
    if change >= 0.05:
        return DemandOutlook.HOT.value if change >= 0.15 else DemandOutlook.GROWING.value
    if change <= -0.05:
        return DemandOutlook.DECLINING.value
    return DemandOutlook.STABLE.value


def _bls_month(period: str) -> int:
    if period.startswith("M") and period[1:].isdigit():
        month = int(period[1:])
        return month if 1 <= month <= 12 else 12
    return 12


def parse_bls_payload(
    body: str, config: MarketSourceConfig
) -> tuple[list[DemandObservation], list[ConnectorError]]:
    """BLS v2 ``{status, Results: {series: [{seriesID, data: [{year,
    period, value}]}]}}`` (newest data point first)."""
    data = json.loads(body)
    if str(data.get("status") or "") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS status {data.get('status')!r}")
    results = data.get("Results") if isinstance(data.get("Results"), dict) else {}
    observations: list[DemandObservation] = []
    errors: list[ConnectorError] = []
    for series in results.get("series") or []:
        if not isinstance(series, dict):
            errors.append(
                ConnectorError(code="invalid", detail="BLS series is not an object", retryable="no")
            )
            continue
        series_id = str(series.get("seriesID") or "")
        mapping = config.series.get(series_id)
        if mapping is None:
            continue
        points = [
            point
            for point in (series.get("data") or [])
            if isinstance(point, dict) and str(point.get("value") or "").strip()
        ]
        if not points:
            errors.append(
                ConnectorError(
                    code="invalid",
                    detail=f"BLS series {series_id} has no numeric points",
                    retryable="no",
                )
            )
            continue
        try:
            values = [float(point["value"]) for point in points]
        except (TypeError, ValueError):
            errors.append(
                ConnectorError(
                    code="invalid",
                    detail=f"BLS series {series_id} carries a non-numeric value",
                    retryable="no",
                )
            )
            continue
        latest = points[0]
        try:
            observed_at = datetime(
                int(latest["year"]), _bls_month(str(latest.get("period") or "")), 1, tzinfo=UTC
            )
        except (KeyError, TypeError, ValueError):
            observed_at = datetime.now(UTC)
        observations.append(
            DemandObservation(
                job_code=mapping.job_code,
                metric=mapping.metric,
                value=values[0],
                outlook=_outlook(values) if mapping.metric == "employment" else None,
                unit="index",
                observed_at=observed_at,
                source="BLS",
                dataset="bls",
                source_url=BLS_URL,
            )
        )
    return observations, errors


def parse_adzuna_payload(
    body: str, config: MarketSourceConfig, *, job_code: str
) -> tuple[list[DemandObservation], list[ConnectorError]]:
    """Adzuna history ``{month: {"YYYY-MM": count, …}}`` (or ``histogram``)."""
    data = json.loads(body)
    months = data.get("month") or data.get("histogram")
    if not isinstance(months, dict) or not months:
        raise ValueError("Adzuna history payload has no month histogram")
    ordered = sorted(
        ((str(key), float(value)) for key, value in months.items() if value is not None),
        key=lambda entry: entry[0],
    )
    if not ordered:
        raise ValueError("Adzuna history histogram is empty")
    latest_month, latest_value = ordered[-1]
    try:
        observed_at = datetime.strptime(latest_month[:7], "%Y-%m").replace(tzinfo=UTC)
    except ValueError:
        observed_at = datetime.now(UTC)
    observation = DemandObservation(
        job_code=job_code,
        metric="employment",
        value=latest_value,
        outlook=_outlook([value for _, value in reversed(ordered)]),
        unit="postings",
        observed_at=observed_at,
        source="Adzuna",
        dataset="adzuna",
        source_url=ADZUNA_HISTORY_URL.format(country=config.country),
    )
    return [observation], []


def dataset_request(
    config: MarketSourceConfig, secrets: dict[str, str]
) -> tuple[str, str, dict[str, str], dict | None]:
    """(method, url, headers, body) for one dataset fetch."""
    if config.dataset == "bls":
        year = datetime.now(UTC).year
        start = config.start_year or year - 1
        end = config.end_year or year
        body: dict = {
            "seriesid": list(config.series),
            "startyear": str(start),
            "endyear": str(end),
        }
        key = secrets.get("bls_key")
        if key:
            body["registrationkey"] = key
        return "POST", BLS_URL, {"Accept": "application/json"}, body
    from urllib.parse import urlencode

    params = {
        "app_id": secrets.get("adzuna_app_id", ""),
        "app_key": secrets.get("adzuna_app_key", ""),
    }
    if config.what:
        params["what"] = config.what
    url = f"{ADZUNA_HISTORY_URL.format(country=config.country)}?{urlencode(params)}"
    return "GET", url, {"Accept": "application/json"}, None


async def fetch_demand_observations(
    source: JobSource, *, transport=None
) -> tuple[list[DemandObservation], list[ConnectorError]]:
    """One market source's observations through the guarded transport."""
    from app.extensions.runtime.http import build_search_transport
    from app.services.postings_service import resolve_source_secrets

    config = MarketSourceConfig.model_validate(source.config or {})
    secrets = resolve_source_secrets(source)
    method, url, headers, body = dataset_request(config, secrets)
    if transport is None:
        transport = build_search_transport(domains=DATASET_DOMAINS.get(config.dataset))
    try:
        response = await transport(method, url, headers, body)
    except PoliteHttpError as exc:
        return [], [ConnectorError.from_polite(exc)]
    if response.status != 200:
        return [], [
            ConnectorError(
                code="provider",
                detail=f"{config.dataset} returned status {response.status}",
                retryable="yes",
            )
        ]
    try:
        if config.dataset == "bls":
            return parse_bls_payload(response.body, config)
        if not config.series:
            raise ValueError("adzuna sources need one series entry carrying the job code")
        job_code = next(iter(config.series.values())).job_code
        return parse_adzuna_payload(response.body, config, job_code=job_code)
    except (json.JSONDecodeError, ValueError) as exc:
        return [], [
            ConnectorError(
                code="protocol",
                detail=f"{config.dataset} parse: {exc}",
                retryable="after-config-change",
            )
        ]


async def _merge_demand(
    db: AsyncSession, job: Job, observation: DemandObservation
) -> MarketSnapshot | None:
    """Field-level provenance on `jobs.demand` plus the same-day snapshot."""
    now = datetime.now(UTC)
    attributes = dict(job.attributes or {})
    demand = dict(attributes.get("demand") or {})
    sources = dict(demand.get("sources") or {})
    provenance = {
        "source": observation.source,
        "dataset": observation.dataset,
        "observed_at": observation.observed_at.isoformat(),
        "value": observation.value,
        "unit": observation.unit,
        "url": observation.source_url,
    }
    sources[observation.metric] = provenance
    demand["sources"] = sources
    if observation.outlook:
        demand["outlook"] = observation.outlook
        demand["note"] = (
            f"{observation.source} outlook: {observation.outlook} "
            f"(observed {observation.observed_at.date().isoformat()})"
        )
    attributes["demand"] = demand
    job.attributes = attributes
    flag_modified(job, "attributes")

    row = (
        (
            await db.execute(
                select(MarketSnapshot).where(
                    MarketSnapshot.scope_kind == "job",
                    MarketSnapshot.scope_key == f"job:{job.id}",
                    MarketSnapshot.capture_date == now.date(),
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        row = MarketSnapshot(
            scope_kind="job",
            scope_key=f"job:{job.id}",
            job_id=job.id,
            capture_date=now.date(),
            captured_at=now,
            payload={"demand": {}},
            sample_size=0,
            thin_sample=True,
        )
        db.add(row)
    payload = dict(row.payload or {})
    demand_payload = dict(payload.get("demand") or {})
    demand_payload[observation.metric] = provenance
    if observation.outlook:
        demand_payload["outlook"] = observation.outlook
    payload["demand"] = demand_payload
    row.payload = payload
    flag_modified(row, "payload")
    return row


async def run_demand_import(
    db: AsyncSession, payload: dict | None = None, *, transport=None
) -> dict:
    """Apply every enabled market source's observations; never one bad row
    fails the run."""
    sources = list(
        (
            await db.execute(
                select(JobSource).where(JobSource.enabled.is_(True), JobSource.kind == "market")
            )
        )
        .scalars()
        .all()
    )
    totals = {"sources": len(sources), "observations": 0, "jobs_updated": 0, "snapshots": 0}
    errors: list[str] = []
    now = datetime.now(UTC)
    for source in sources:
        observations, row_errors = await fetch_demand_observations(source, transport=transport)
        source.last_run_at = now
        if row_errors:
            source.last_status = HealthStatus.DEGRADED.value
            source.error = "; ".join(f"{error.code}: {error.detail}" for error in row_errors)[:2000]
            errors.extend(f"{source.key}: {error.code}" for error in row_errors)
        else:
            source.last_status = HealthStatus.OK.value
            source.error = ""
        updated = 0
        for observation in observations:
            job = (
                (await db.execute(select(Job).where(Job.code == observation.job_code)))
                .scalars()
                .first()
            )
            if job is None:
                errors.append(f"{source.key}: unknown job code {observation.job_code}")
                continue
            await _merge_demand(db, job, observation)
            updated += 1
        totals["observations"] += len(observations)
        totals["jobs_updated"] += updated
        totals["snapshots"] += updated
    await db.commit()
    totals["errors"] = errors[:20]
    return totals


async def ensure_demand_source(db: AsyncSession) -> JobSource:
    """Idempotently provision the system market source (dormant until a
    dataset series is configured)."""
    row = (
        (await db.execute(select(JobSource).where(JobSource.key == DEMAND_SOURCE_KEY)))
        .scalars()
        .first()
    )
    if row is not None:
        return row
    source = JobSource(
        key=DEMAND_SOURCE_KEY,
        connector_key=DEMAND_SOURCE_CONNECTOR,
        kind="market",
        schedule_kind=ScheduleKind.SYSTEM_DEMAND_IMPORT.value,
        config=MarketSourceConfig().model_dump(mode="json"),
        enabled=True,
    )
    db.add(source)
    await db.flush()
    return source


__all__ = [
    "DATASETS",
    "DemandObservation",
    "MarketSourceConfig",
    "dataset_request",
    "ensure_demand_source",
    "fetch_demand_observations",
    "parse_adzuna_payload",
    "parse_bls_payload",
    "run_demand_import",
    "validate_market_config",
]
