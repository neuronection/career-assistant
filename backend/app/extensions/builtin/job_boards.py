"""Real-content job-board connectors (the first bundled T1 sources over
live public JSON job APIs): Arbeitnow, Remotive, Jobicy.

All three are free, no-auth, public JSON APIs — the manifests declare no
secret slots by absence. Wire shapes here are the CAPTURED truth
(2026-10-17 probes; fixtures in ``tests/fixtures/connectors/``):
Arbeitnow's documented ``/api/job-board`` now 302s to the homepage — the
live endpoint is ``/api/job-board-api`` (300 rows/page, unix
``created_at``); Remotive returns ``{jobs, job-count, …}`` with naive-ISO
``publication_date`` and free-text ``salary``; Jobicy v2 returns
``{jobs, nextCursor, hasMore, …}`` with structured salary fields and
tz-aware ``pubDate``.

Incremental sync is a posted_at watermark in ``next_state`` (plus the
conditional-GET validators the runtime round-trips): items at or below
the watermark are dropped connector-side, changed content still dedups
downstream by ``content_hash``. Politeness (SSRF, robots, per-host caps,
retries) is the runtime's job — these connectors never sleep, retry or
open sockets.
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from urllib.parse import quote

from pydantic import BaseModel, Field

from app.extensions.polite_http import conditional_headers, merge_cache_state
from app.extensions.sdk import (
    ConnectorCapabilities,
    ConnectorError,
    ConnectorResult,
    LocationSpec,
    PostingConnector,
    RawPosting,
    SalarySpec,
)

WATERMARK_KEY = "watermark"


def _not_ready() -> ConnectorResult:
    return ConnectorResult(
        partial_errors=[
            ConnectorError(
                code="not-ready", detail="no transport injected", retryable="after-config-change"
            )
        ]
    )


def _provider_error(detail: str) -> ConnectorError:
    return ConnectorError(code="provider", detail=detail[:500], retryable="yes")


def _protocol_error(detail: str) -> ConnectorError:
    return ConnectorError(code="protocol", detail=detail[:500], retryable="after-config-change")


def _invalid_row(detail: str) -> ConnectorError:
    return ConnectorError(code="invalid", detail=detail[:500], retryable="no")


def _retry_after_ms(headers: dict[str, str]) -> int | None:
    raw = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
    try:
        seconds = int(str(raw))
    except (TypeError, ValueError):
        return None
    return seconds * 1000 if seconds >= 0 else None


def _rate_limited(host: str, headers: dict[str, str]) -> ConnectorError:
    return ConnectorError(
        code="rate-limited",
        detail=f"{host} rate limited the fetch (status 429)",
        retryable="after-delay",
        retry_after_ms=_retry_after_ms(headers),
    )


# Employment-type normalization over free-text vocabularies (the three
# boards ship German/English labels); only unambiguous wins map.
_EMPLOYMENT_TOKENS: dict[str, str] = {
    "full time": "full_time",
    "fulltime": "full_time",
    "vollzeit": "full_time",
    "part time": "part_time",
    "parttime": "part_time",
    "teilzeit": "part_time",
    "werkstudent": "part_time",
    "contract": "contract",
    "freelance": "contract",
    "self employed": "contract",
    "internship": "internship",
    "intern": "internship",
    "praktikum": "internship",
    "temporary": "temporary",
}


def _normalize_token(value: str) -> str:
    return re.sub(r"[\s\-_]+", " ", str(value or "").strip().lower()).strip()


def _employment_type(entries) -> str | None:
    for entry in entries or []:
        token = _normalize_token(entry)
        if token in _EMPLOYMENT_TOKENS:
            return _EMPLOYMENT_TOKENS[token]
    return None


_SENIORITY_TOKENS: dict[str, str] = {
    "internship": "intern",
    "junior": "junior",
    "midweight": "mid",
    "middle": "mid",
    "senior": "senior",
    "director": "lead",
    "executive": "lead",
}


def _seniority(value) -> str | None:
    token = _normalize_token(value)
    if token in {"any", ""}:
        return None
    return _SENIORITY_TOKENS.get(token)


_SALARY_PERIODS: dict[str, str] = {
    "yearly": "year",
    "annual": "year",
    "monthly": "month",
    "weekly": "week",
    "daily": "day",
    "hourly": "hour",
}


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _parse_iso_utc(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _apply_watermark(items: list[RawPosting], state: dict) -> list[RawPosting]:
    """Drop items at or below the posted_at watermark; items without a
    parseable date always pass (content-hash dedup catches repeats)."""
    mark = _parse_iso_utc((state or {}).get(WATERMARK_KEY))
    if mark is None:
        return items
    kept: list[RawPosting] = []
    for item in items:
        if item.posted_at is None or item.posted_at.replace(tzinfo=UTC) > mark:
            kept.append(item)
    return kept


def _stamp_watermark(
    state: dict, items: list[RawPosting], etag: str | None, last_modified: str | None
) -> dict:
    """The watermark is the OLDEST returned posting's date: anything older
    has either been returned already or scrolled off the capped feed, and
    strictly-newer items re-arrive next sync only when genuinely new."""
    next_state = merge_cache_state(state, etag, last_modified)
    dated = [item.posted_at.replace(tzinfo=UTC) for item in items if item.posted_at]
    if dated:
        boundary = min(dated)
        previous = _parse_iso_utc(next_state.get(WATERMARK_KEY))
        if previous is None or boundary > previous:
            next_state[WATERMARK_KEY] = boundary.isoformat()
    return next_state


def _sort_and_cap(items: list[RawPosting], cap: int) -> list[RawPosting]:
    items.sort(key=lambda item: item.posted_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return items[:cap]


_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
_SALARY_NUMBER = re.compile(r"(\d[\d.,]*)\s*(k?)(?![\d])", re.IGNORECASE)
_SALARY_UNIT_PERIODS = (
    ("/hour", "hour"),
    ("/hr", "hour"),
    ("per hour", "hour"),
    ("hourly", "hour"),
    ("/day", "day"),
    ("per day", "day"),
    ("/week", "week"),
    ("/month", "month"),
    ("monthly", "month"),
)


def parse_salary_text(text: str) -> SalarySpec | None:
    """Best-effort structured salary from free-text board strings
    (``"$170k - $200k"``, ``"$35,3k- $52k"``, ``"$50-$75 /hour"``).
    A ``k`` suffix makes commas decimals (``35,3k`` → 35 300); without
    one, commas are thousands separators. Unparseable text → None."""
    if not text or not str(text).strip():
        return None
    lowered = str(text).lower()
    period = "year"
    for unit, mapped in _SALARY_UNIT_PERIODS:
        if unit in lowered:
            period = mapped
            break
    currency = next((code for symbol, code in _CURRENCY_SYMBOLS.items() if symbol in text), None)
    numbers: list[float] = []
    for match in _SALARY_NUMBER.finditer(str(text)):
        raw, kilo = match.group(1).strip(",."), match.group(2).lower() == "k"
        if not raw:
            continue
        try:
            value = float(raw.replace(",", ".") if kilo else raw.replace(",", ""))
        except ValueError:
            continue
        numbers.append(value * 1000 if kilo else value)
    if not numbers:
        return None
    return SalarySpec(
        currency=currency or "USD",
        min=min(numbers),
        max=max(numbers) if len(numbers) > 1 else None,
        period=period,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- arbeitnow


class ArbeitnowConfig(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=16)
    max_items: int = Field(default=100, ge=1, le=300)


ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
ARBEITNOW_DOMAINS = ("www.arbeitnow.com",)


def parse_arbeitnow_payload(body: str) -> tuple[list[RawPosting], list[ConnectorError]]:
    """``{data: [{slug, company_name, title, description (HTML-escaped),
    remote, url, tags, job_types, location, created_at (unix)}], meta}``."""
    data = json.loads(body)
    rows = data.get("data")
    if not isinstance(rows, list):
        raise ValueError("payload 'data' is not a list")
    items: list[RawPosting] = []
    errors: list[ConnectorError] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append(_invalid_row("arbeitnow row is not an object"))
            continue
        external_id = str(row.get("slug") or "").strip()
        title = str(row.get("title") or "").strip()
        if not external_id or not title:
            errors.append(_invalid_row(f"arbeitnow row missing slug/title (slug={external_id!r})"))
            continue
        location = str(row.get("location") or "").strip()
        posted_at = None
        try:
            posted_at = datetime.fromtimestamp(int(row["created_at"]), tz=UTC)
        except (KeyError, TypeError, ValueError, OSError):
            posted_at = None
        items.append(
            RawPosting(
                external_id=external_id[:300],
                title=title[:300],
                org=str(row.get("company_name") or "")[:200],
                location=LocationSpec(
                    city=location or None,
                    remote=_coerce_bool(row.get("remote")) or "remote" in location.lower(),
                ),
                url=str(row.get("url") or "")[:1000],
                posted_at=posted_at,
                employment_type=_employment_type(row.get("job_types")),  # type: ignore[arg-type]
                skills_raw=[str(tag) for tag in (row.get("tags") or [])][:60],
                raw={
                    "description": html.unescape(str(row.get("description") or ""))[:8000],
                    "job_types": [str(t) for t in (row.get("job_types") or [])][:16],
                    "location": location,
                },
            )
        )
    return items, errors


class ArbeitnowConnector(PostingConnector):
    """Arbeitnow public job-board API — free, no auth. The endpoint drift
    (`/api/job-board` now redirects home) is captured: this is the live
    `/api/job-board-api` shape. Meta terms ask for reasonable use and a link
    back — the per-host caps and the source attribution row cover both."""

    key = "arbeitnow"
    title = "Arbeitnow job board"
    docs_url = "https://docs.career-assistant.local/connectors/arbeitnow"
    capabilities = ConnectorCapabilities(
        network_scopes=list(ARBEITNOW_DOMAINS),
        supports_incremental=True,
        max_requests_per_minute=10,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return ArbeitnowConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = ArbeitnowConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        resp = await transport(ARBEITNOW_URL, conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status == 429:
            return ConnectorResult(partial_errors=[_rate_limited("arbeitnow", resp.headers)])
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[
                    _provider_error(f"arbeitnow fetch failed with status {resp.status}")
                ]
            )
        try:
            items, row_errors = parse_arbeitnow_payload(resp.body)
        except (json.JSONDecodeError, ValueError) as exc:
            return ConnectorResult(partial_errors=[_protocol_error(f"arbeitnow parse: {exc}")])
        if cfg.tags:
            wanted = {_normalize_token(tag) for tag in cfg.tags}
            items = [
                item
                for item in items
                if any(_normalize_token(tag) in wanted for tag in item.skills_raw)
            ]
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, resp.etag, resp.last_modified),
            partial_errors=row_errors,
        )


# ------------------------------------------------------------------ remotive


class RemotiveConfig(BaseModel):
    category: str | None = Field(default=None, max_length=60)
    max_items: int = Field(default=100, ge=1, le=500)


REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
REMOTIVE_DOMAINS = ("remotive.com",)


def parse_remotive_payload(body: str) -> tuple[list[RawPosting], list[ConnectorError]]:
    """``{jobs: [{id, url, title, company_name, category, tags, job_type,
    publication_date (naive ISO, read as UTC), candidate_required_location,
    salary (free text), description (HTML)}]}``."""
    data = json.loads(body)
    rows = data.get("jobs")
    if not isinstance(rows, list):
        raise ValueError("payload 'jobs' is not a list")
    items: list[RawPosting] = []
    errors: list[ConnectorError] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append(_invalid_row("remotive row is not an object"))
            continue
        external_id = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not external_id or not title:
            errors.append(_invalid_row(f"remotive row missing id/title (id={external_id!r})"))
            continue
        location_note = str(row.get("candidate_required_location") or "").strip()
        items.append(
            RawPosting(
                external_id=external_id[:300],
                title=title[:300],
                org=str(row.get("company_name") or "")[:200],
                location=LocationSpec(remote=True),
                url=str(row.get("url") or "")[:1000],
                posted_at=_parse_iso_utc(row.get("publication_date")),
                salary=parse_salary_text(str(row.get("salary") or "")),
                employment_type=_employment_type([row.get("job_type")]),  # type: ignore[arg-type]
                skills_raw=[str(tag) for tag in (row.get("tags") or [])][:60],
                raw={
                    "description": str(row.get("description") or "")[:8000],
                    "category": str(row.get("category") or ""),
                    "location_note": location_note,
                },
            )
        )
    return items, errors


class RemotiveConnector(PostingConnector):
    """Remotive public remote-jobs API — free, no auth. Remote-jobs board:
    every row is remote, the geo restriction rides ``raw.location_note``.
    Their legal notice asks for attribution and a link back — the posting
    URL IS the remotive.com URL, so attribution rides the data."""

    key = "remotive"
    title = "Remotive remote jobs"
    docs_url = "https://docs.career-assistant.local/connectors/remotive"
    capabilities = ConnectorCapabilities(
        network_scopes=list(REMOTIVE_DOMAINS),
        supports_incremental=True,
        max_requests_per_minute=10,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return RemotiveConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = RemotiveConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        url = REMOTIVE_URL
        if cfg.category:
            url = f"{url}?category={quote(cfg.category)}"
        resp = await transport(url, conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status == 429:
            return ConnectorResult(partial_errors=[_rate_limited("remotive", resp.headers)])
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[_provider_error(f"remotive fetch failed with status {resp.status}")]
            )
        try:
            items, row_errors = parse_remotive_payload(resp.body)
        except (json.JSONDecodeError, ValueError) as exc:
            return ConnectorResult(partial_errors=[_protocol_error(f"remotive parse: {exc}")])
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, resp.etag, resp.last_modified),
            partial_errors=row_errors,
        )


# ------------------------------------------------------------------- jobicy


class JobicyConfig(BaseModel):
    tag: str | None = Field(default=None, max_length=60)
    max_items: int = Field(default=50, ge=1, le=200)


JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
JOBICY_DOMAINS = ("jobicy.com",)
JOBICY_COUNT_CAP = 100
JOBICY_MAX_PAGES = 3


def parse_jobicy_salary(row: dict) -> SalarySpec | None:
    minimum, maximum = row.get("salaryMin"), row.get("salaryMax")
    if minimum is None and maximum is None:
        return None
    currency = str(row.get("salaryCurrency") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        currency = "USD"
    period = _SALARY_PERIODS.get(str(row.get("salaryPeriod") or "").strip().lower(), "year")
    return SalarySpec(
        currency=currency,
        min=float(minimum) if minimum is not None else None,
        max=float(maximum) if maximum is not None else None,
        period=period,  # type: ignore[arg-type]
    )


def parse_jobicy_payload(body: str) -> tuple[list[RawPosting], list[ConnectorError]]:
    """``{jobs: [{id, url, jobSlug, jobTitle, companyName, jobIndustry,
    jobType, jobGeo, jobLevel, jobExcerpt, jobDescription (HTML), pubDate
    (tz-aware ISO), salaryMin/Max/Currency/Period}], nextCursor, hasMore}``."""
    data = json.loads(body)
    rows = data.get("jobs")
    if not isinstance(rows, list):
        raise ValueError("payload 'jobs' is not a list")
    items: list[RawPosting] = []
    errors: list[ConnectorError] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append(_invalid_row("jobicy row is not an object"))
            continue
        external_id = str(row.get("id") or "").strip()
        title = str(row.get("jobTitle") or "").strip()
        if not external_id or not title:
            errors.append(_invalid_row(f"jobicy row missing id/jobTitle (id={external_id!r})"))
            continue
        geo = str(row.get("jobGeo") or "").strip()
        items.append(
            RawPosting(
                external_id=external_id[:300],
                title=title[:300],
                org=str(row.get("companyName") or "")[:200],
                location=LocationSpec(
                    country=geo or None,
                    remote=True,
                ),
                url=str(row.get("url") or "")[:1000],
                posted_at=_parse_iso_utc(row.get("pubDate")),
                salary=parse_jobicy_salary(row),
                seniority=_seniority(row.get("jobLevel")),  # type: ignore[arg-type]
                employment_type=_employment_type(row.get("jobType")),  # type: ignore[arg-type]
                raw={
                    "description": str(row.get("jobDescription") or "")[:8000],
                    "excerpt": str(row.get("jobExcerpt") or "")[:1000],
                    "industries": [str(i) for i in (row.get("jobIndustry") or [])][:12],
                    "level": str(row.get("jobLevel") or ""),
                    "geo": geo,
                },
            )
        )
    return items, errors


class JobicyConnector(PostingConnector):
    """Jobicy public remote-jobs API v2 — free, no auth. Remote-jobs feed:
    every row is remote, the geo restriction rides ``location.country``
    and ``raw.geo``. Cursor pagination (`nextCursor`/`hasMore`, captured
    live) walks up to three pages per sync under the runtime's per-host
    rate cap; the friendly notice asks for credit and application links
    — the posting URL is the jobicy.com URL."""

    key = "jobicy"
    title = "Jobicy remote jobs"
    docs_url = "https://docs.career-assistant.local/connectors/jobicy"
    capabilities = ConnectorCapabilities(
        network_scopes=list(JOBICY_DOMAINS),
        supports_incremental=True,
        max_requests_per_minute=12,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return JobicyConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = JobicyConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        params = f"count={min(cfg.max_items, JOBICY_COUNT_CAP)}"
        if cfg.tag:
            params = f"{params}&tag={quote(cfg.tag)}"
        url = f"{JOBICY_URL}?{params}"
        items: list[RawPosting] = []
        errors: list[ConnectorError] = []
        etag: str | None = None
        last_modified: str | None = None
        for page in range(JOBICY_MAX_PAGES):
            headers = conditional_headers(state or {}) if page == 0 else {}
            resp = await transport(url, headers)
            etag = resp.etag or etag
            last_modified = resp.last_modified or last_modified
            if resp.status == 304:
                return ConnectorResult(
                    next_state=merge_cache_state(state, resp.etag, resp.last_modified)
                )
            if resp.status == 429:
                errors.append(_rate_limited("jobicy", resp.headers))
                break
            if resp.status != 200:
                errors.append(_provider_error(f"jobicy fetch failed with status {resp.status}"))
                break
            try:
                data = json.loads(resp.body)
                page_items, row_errors = parse_jobicy_payload(resp.body)
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(_protocol_error(f"jobicy parse: {exc}"))
                break
            items.extend(page_items)
            errors.extend(row_errors)
            cursor = data.get("nextCursor") if isinstance(data, dict) else None
            has_more = bool(data.get("hasMore")) if isinstance(data, dict) else False
            if len(items) >= cfg.max_items or not has_more or not cursor:
                break
            url = f"{JOBICY_URL}?{params}&cursor={quote(str(cursor))}"
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, etag, last_modified),
            partial_errors=errors,
        )
