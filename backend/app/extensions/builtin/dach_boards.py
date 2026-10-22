"""DACH board pack (plan 122 Phase 1): Personio, JOIN, StepStone/Xing RSS,
Recruitee and Teamtailor as bundled T1 connectors.

Every wire shape here is CAPTURED truth (2026-10-22 probes; fixtures in
``tests/fixtures/connectors/`` — sources recorded in ``CAPTURES.md``):
Personio's per-tenant XML feed (``<workzag-jobs>`` with nested
``jobDescriptions``), JOIN's public company API (``items[]`` with salary
amounts in minor units and ``pagination``), Recruitee's ``offers[]`` feed
(naive ``"YYYY-MM-DD HH:MM:SS UTC"`` timestamps), Teamtailor's JSON Feed 1.1
(``items[]`` carrying an embedded schema.org ``_jobposting``) and RSS 2.0 for
StepStone/Xing saved-search alerts.

Incremental sync is a posted_at watermark in ``next_state`` plus the
conditional-GET validators the runtime round-trips. Politeness (SSRF, robots,
per-host caps, retries) is the runtime's job — these connectors never sleep,
retry or open sockets.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import cast
from urllib.parse import quote

from pydantic import BaseModel, Field

from app.extensions.builtin.job_boards import (
    _apply_watermark,
    _employment_type,
    _invalid_row,
    _normalize_token,
    _not_ready,
    _parse_iso_utc,
    _protocol_error,
    _provider_error,
    _rate_limited,
    _sort_and_cap,
    _stamp_watermark,
    parse_salary_text,
)
from app.extensions.polite_http import conditional_headers, merge_cache_state
from app.extensions.sdk import (
    ConnectorCapabilities,
    ConnectorError,
    ConnectorResult,
    EmploymentType,
    LocationSpec,
    PostingConnector,
    RawPosting,
    SalarySpec,
    SeniorityLevel,
)

_PERSONIO_EMPLOYMENT = {
    "permanent": "full_time",
    "temporary": "temporary",
    "internship": "internship",
    "intern": "internship",
    "freelance": "contract",
    "working_student": "part_time",
    "working student": "part_time",
}
_PERSONIO_SENIORITY = {
    "entry-level": "junior",
    "entry level": "junior",
    "experienced": "mid",
    "manager": "lead",
    "executive": "lead",
    "student": "intern",
    "intern": "intern",
}
_PERSONIO_SCHEDULE = {
    "full-time": "full_time",
    "full time": "full_time",
    "part-time": "part_time",
    "part time": "part_time",
}
_JOIN_FREQUENCY = {
    "PER_YEAR": "year",
    "PER_MONTH": "month",
    "PER_WEEK": "week",
    "PER_DAY": "day",
    "PER_HOUR": "hour",
}
_JOIN_EMPLOYMENT = {
    "employee": "full_time",
    "worker": "full_time",
    "working student": "part_time",
    "intern": "internship",
    "internship": "internship",
    "freelancer": "contract",
    "freelance": "contract",
    "temporary": "temporary",
}
_RECRUITEE_PERIODS = {
    "year": "year",
    "yearly": "year",
    "month": "month",
    "monthly": "month",
    "week": "week",
    "weekly": "week",
    "day": "day",
    "daily": "day",
    "hour": "hour",
    "hourly": "hour",
}
_JSONLD_UNIT = {
    "HOUR": "hour",
    "DAY": "day",
    "WEEK": "week",
    "MONTH": "month",
    "YEAR": "year",
}
JOIN_PAGE_SIZE_CAP = 5
JOIN_MAX_PAGES = 3


def _parse_rfc822_utc(value) -> datetime | None:
    """RSS 2.0 ``pubDate`` (RFC 822, e.g. ``Sun, 16 Jun 2024 17:30:51 +0000``)."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return _parse_iso_utc(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_space_utc(value) -> datetime | None:
    """Recruitee's ``"2026-10-15 09:31:36 UTC"`` wire format."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return _parse_iso_utc(text)
    return parsed.replace(tzinfo=UTC)


def _money(value, *, minor_units: bool = False) -> float | None:
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount / 100 if minor_units else amount


def _currency(value, default: str = "EUR") -> str:
    code = str(value or "").strip().upper()
    return code if len(code) == 3 and code.isalpha() else default


# ----------------------------------------------------------------- personio


class PersonioConfig(BaseModel):
    tenant: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
    )
    language: str = Field(default="en", max_length=8, pattern=r"^[a-z]{2}(?:-[A-Za-z]{2})?$")
    max_items: int = Field(default=100, ge=1, le=300)


PERSONIO_DOMAINS = ("*.jobs.personio.de",)


def personio_feed_url(tenant: str, language: str = "en") -> str:
    return f"https://{tenant}.jobs.personio.de/xml?language={quote(language)}"


def parse_personio_payload(
    body: str, *, tenant: str = ""
) -> tuple[list[RawPosting], list[ConnectorError]]:
    """``<workzag-jobs><position>`` rows: id, office, additionalOffices,
    recruitingCategory, name, jobDescriptions, employmentType, seniority,
    schedule, occupation, createdAt."""
    root = ET.fromstring(body)
    items: list[RawPosting] = []
    errors: list[ConnectorError] = []
    for node in root.findall("position"):
        external_id = (node.findtext("id") or "").strip()
        title = (node.findtext("name") or "").strip()
        if not external_id or not title:
            errors.append(_invalid_row(f"personio row missing id/name (id={external_id!r})"))
            continue
        office = (node.findtext("office") or "").strip()
        additional = [
            (extra.text or "").strip()
            for extra in node.findall("additionalOffices/office")
            if (extra.text or "").strip()
        ]
        description_parts = []
        for block in node.findall("jobDescriptions/jobDescription"):
            label = (block.findtext("name") or "").strip()
            value = (block.findtext("value") or "").strip()
            if value:
                description_parts.append(f"<h3>{label}</h3>{value}" if label else value)
        seniority_raw = (node.findtext("seniority") or "").strip().lower()
        schedule_raw = (node.findtext("schedule") or "").strip().lower()
        employment_raw = (node.findtext("employmentType") or "").strip().lower()
        remote = office.lower() in {"remote", "homeoffice", "home office"}
        items.append(
            RawPosting(
                external_id=external_id[:300],
                title=title[:300],
                org="",
                location=LocationSpec(
                    city=None if remote else (office or None),
                    remote=remote,
                ),
                url=(f"https://{tenant}.jobs.personio.de/job/{external_id}" if tenant else ""),
                posted_at=_parse_iso_utc(node.findtext("createdAt")),
                employment_type=cast(
                    EmploymentType | None,
                    _PERSONIO_EMPLOYMENT.get(employment_raw)
                    or _PERSONIO_SCHEDULE.get(schedule_raw),
                ),
                seniority=cast(SeniorityLevel | None, _PERSONIO_SENIORITY.get(seniority_raw)),
                skills_raw=[
                    occupation
                    for occupation in [(node.findtext("occupation") or "").strip()]
                    if occupation
                ],
                raw={
                    "description": "".join(description_parts)[:8000],
                    "office": office,
                    "additional_offices": additional[:8],
                    "recruiting_category": (node.findtext("recruitingCategory") or "").strip(),
                    "occupation": (node.findtext("occupation") or "").strip(),
                    "occupation_category": (node.findtext("occupationCategory") or "").strip(),
                    "schedule": schedule_raw,
                },
            )
        )
    return items, errors


class PersonioConnector(PostingConnector):
    """Personio's public per-tenant career-site XML feed — free, no auth."""

    key = "personio"
    title = "Personio careers feed"
    docs_url = "https://docs.career-assistant.local/connectors/personio"
    capabilities = ConnectorCapabilities(
        network_scopes=list(PERSONIO_DOMAINS),
        supports_incremental=True,
        max_requests_per_minute=10,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return PersonioConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = PersonioConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        url = personio_feed_url(cfg.tenant, cfg.language)
        resp = await transport(url, conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status == 429:
            return ConnectorResult(partial_errors=[_rate_limited("personio", resp.headers)])
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[_provider_error(f"personio fetch failed with status {resp.status}")]
            )
        try:
            items, row_errors = parse_personio_payload(resp.body, tenant=cfg.tenant)
        except (ET.ParseError, ValueError) as exc:
            return ConnectorResult(partial_errors=[_protocol_error(f"personio parse: {exc}")])
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, resp.etag, resp.last_modified),
            partial_errors=row_errors,
        )


# --------------------------------------------------------------------- join


class JoinComConfig(BaseModel):
    company_id: int = Field(ge=1)
    company_slug: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
    )
    page_size: int = Field(default=JOIN_PAGE_SIZE_CAP, ge=1, le=JOIN_PAGE_SIZE_CAP)
    max_items: int = Field(default=50, ge=1, le=200)


JOIN_DOMAINS = ("join.com",)


def join_jobs_url(company_id: int, page: int = 1, page_size: int = JOIN_PAGE_SIZE_CAP) -> str:
    return (
        f"https://join.com/api/public/companies/{company_id}/jobs?pageSize={page_size}&page={page}"
    )


def parse_join_payload(
    body: str, *, company_slug: str = ""
) -> tuple[list[RawPosting], list[ConnectorError], dict]:
    """``{items: [{id, idParam, title, createdAt, salaryFrequency,
    salaryAmountFrom/To {amount (minor units), currency}, employmentType
    {name}, workplaceType, country {iso3166}, city {cityName}}],
    pagination {rowCount, pageCount, page, pageSize}}``."""
    data = json.loads(body)
    rows = data.get("items")
    if not isinstance(rows, list):
        raise ValueError("payload 'items' is not a list")
    items: list[RawPosting] = []
    errors: list[ConnectorError] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append(_invalid_row("join.com row is not an object"))
            continue
        external_id = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not external_id or not title:
            errors.append(_invalid_row(f"join.com row missing id/title (id={external_id!r})"))
            continue
        salary_from = row.get("salaryAmountFrom")
        salary_from = salary_from if isinstance(salary_from, dict) else {}
        salary_to = row.get("salaryAmountTo")
        salary_to = salary_to if isinstance(salary_to, dict) else {}
        currency = _currency(salary_from.get("currency"))
        minimum = _money(salary_from.get("amount"), minor_units=True)
        maximum = _money(salary_to.get("amount"), minor_units=True)
        period = _JOIN_FREQUENCY.get(str(row.get("salaryFrequency") or "").upper(), "year")
        salary = (
            SalarySpec(currency=currency, min=minimum, max=maximum, period=period)  # type: ignore[arg-type]
            if minimum is not None or maximum is not None
            else None
        )
        workplace = str(row.get("workplaceType") or "").upper()
        raw_city = row.get("city")
        city = raw_city if isinstance(raw_city, dict) else {}
        raw_country = row.get("country")
        country = raw_country if isinstance(raw_country, dict) else {}
        raw_employment = row.get("employmentType")
        employment = raw_employment if isinstance(raw_employment, dict) else {}
        raw_category = row.get("category")
        category = raw_category if isinstance(raw_category, dict) else {}
        raw_office = row.get("office")
        office = raw_office if isinstance(raw_office, dict) else {}
        id_param = str(row.get("idParam") or external_id)
        items.append(
            RawPosting(
                external_id=external_id[:300],
                title=title[:300],
                org="",
                location=LocationSpec(
                    city=str(city.get("cityName") or "").strip() or None,
                    country=str(country.get("iso3166") or "").strip() or None,
                    remote=workplace == "REMOTE",
                ),
                url=(
                    f"https://join.com/companies/{company_slug}/{id_param}" if company_slug else ""
                ),
                posted_at=_parse_iso_utc(row.get("createdAt")),
                salary=salary,
                onsite_policy=(
                    "remote"
                    if workplace == "REMOTE"
                    else "hybrid"
                    if workplace == "HYBRID"
                    else "onsite"
                    if workplace == "ONSITE"
                    else None
                ),
                employment_type=cast(
                    EmploymentType | None,
                    _JOIN_EMPLOYMENT.get(_normalize_token(str(employment.get("name") or ""))),
                ),
                raw={
                    "category": str(category.get("name") or ""),
                    "employment_type": str(employment.get("name") or ""),
                    "workplace_type": workplace,
                    "office_id": str(office.get("id") or ""),
                },
            )
        )
    pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
    return items, errors, pagination


class JoinComConnector(PostingConnector):
    """JOIN.com public company job API — free, no auth. ``pageSize`` is
    capped at 5 by the API (captured); pagination walks up to three pages
    per sync under the runtime's per-host cap."""

    key = "join_com"
    title = "JOIN.com careers feed"
    docs_url = "https://docs.career-assistant.local/connectors/join-com"
    capabilities = ConnectorCapabilities(
        network_scopes=list(JOIN_DOMAINS),
        supports_incremental=True,
        max_requests_per_minute=10,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return JoinComConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = JoinComConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        items: list[RawPosting] = []
        errors: list[ConnectorError] = []
        etag: str | None = None
        last_modified: str | None = None
        page = 1
        for _ in range(JOIN_MAX_PAGES):
            headers = conditional_headers(state or {}) if page == 1 else {}
            resp = await transport(join_jobs_url(cfg.company_id, page, cfg.page_size), headers)
            etag = resp.etag or etag
            last_modified = resp.last_modified or last_modified
            if resp.status == 304:
                return ConnectorResult(
                    next_state=merge_cache_state(state, resp.etag, resp.last_modified)
                )
            if resp.status == 429:
                errors.append(_rate_limited("join.com", resp.headers))
                break
            if resp.status != 200:
                errors.append(_provider_error(f"join.com fetch failed with status {resp.status}"))
                break
            try:
                page_items, row_errors, pagination = parse_join_payload(
                    resp.body, company_slug=cfg.company_slug
                )
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(_protocol_error(f"join.com parse: {exc}"))
                break
            items.extend(page_items)
            errors.extend(row_errors)
            page_count = int(pagination.get("pageCount") or 1)
            if len(items) >= cfg.max_items or page >= page_count:
                break
            page += 1
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, etag, last_modified),
            partial_errors=errors,
        )


# ---------------------------------------------------------------- recruitee


class RecruiteeConfig(BaseModel):
    company: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
    )
    max_items: int = Field(default=100, ge=1, le=300)


RECRUITEE_DOMAINS = ("*.recruitee.com",)


def recruitee_feed_url(company: str) -> str:
    return f"https://{company}.recruitee.com/api/offers/"


def _recruitee_translation(row: dict, field: str) -> str:
    translations = row.get("translations")
    if isinstance(translations, dict):
        for locale in ("en", "de", "nl", "fr"):
            entry = translations.get(locale)
            if isinstance(entry, dict) and str(entry.get(field) or "").strip():
                return str(entry[field])
        for entry in translations.values():
            if isinstance(entry, dict) and str(entry.get(field) or "").strip():
                return str(entry[field])
    return str(row.get(field) or "")


def parse_recruitee_payload(body: str) -> tuple[list[RawPosting], list[ConnectorError]]:
    """``{offers: [{id, slug, title, translations {en: {title, description}},
    company_name, department, city, country_code, remote, hybrid, tags,
    published_at, close_at, careers_url, salary {min, max, currency, period},
    employment_type_code}]}``."""
    data = json.loads(body)
    rows = data.get("offers")
    if not isinstance(rows, list):
        raise ValueError("payload 'offers' is not a list")
    items: list[RawPosting] = []
    errors: list[ConnectorError] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append(_invalid_row("recruitee row is not an object"))
            continue
        external_id = str(row.get("id") or row.get("slug") or "").strip()
        title = _recruitee_translation(row, "title").strip()
        if not external_id or not title:
            errors.append(_invalid_row(f"recruitee row missing id/title (id={external_id!r})"))
            continue
        raw_salary = row.get("salary")
        salary_row = raw_salary if isinstance(raw_salary, dict) else {}
        minimum = _money(salary_row.get("min"))
        maximum = _money(salary_row.get("max"))
        salary = None
        if minimum is not None or maximum is not None:
            period = _RECRUITEE_PERIODS.get(
                str(salary_row.get("period") or "").strip().lower(), "year"
            )
            salary = SalarySpec(
                currency=_currency(salary_row.get("currency")),
                min=minimum,
                max=maximum,
                period=period,  # type: ignore[arg-type]
            )
        items.append(
            RawPosting(
                external_id=external_id[:300],
                title=title[:300],
                org=str(row.get("company_name") or "")[:200],
                location=LocationSpec(
                    city=str(row.get("city") or "").strip() or None,
                    country=str(row.get("country_code") or "").strip() or None,
                    remote=bool(row.get("remote")),
                ),
                url=str(row.get("careers_url") or "")[:1000],
                posted_at=_parse_space_utc(row.get("published_at")),
                expires_at=_parse_space_utc(row.get("close_at")),
                salary=salary,
                onsite_policy=(
                    "remote"
                    if row.get("remote")
                    else "hybrid"
                    if row.get("hybrid")
                    else "onsite"
                    if row.get("on_site")
                    else None
                ),
                employment_type=cast(
                    EmploymentType | None,
                    _employment_type([row.get("employment_type_code")]),
                ),
                skills_raw=[str(tag) for tag in (row.get("tags") or [])][:60],
                raw={
                    "description": _recruitee_translation(row, "description")[:8000],
                    "requirements": _recruitee_translation(row, "requirements")[:4000],
                    "department": str(row.get("department") or ""),
                    "category_code": str(row.get("category_code") or ""),
                    "experience_code": str(row.get("experience_code") or ""),
                },
            )
        )
    return items, errors


class RecruiteeConnector(PostingConnector):
    """Recruitee's public per-tenant ``/api/offers/`` feed — free, no auth."""

    key = "recruitee"
    title = "Recruitee careers feed"
    docs_url = "https://docs.career-assistant.local/connectors/recruitee"
    capabilities = ConnectorCapabilities(
        network_scopes=list(RECRUITEE_DOMAINS),
        supports_incremental=True,
        max_requests_per_minute=10,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return RecruiteeConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = RecruiteeConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        resp = await transport(recruitee_feed_url(cfg.company), conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status == 429:
            return ConnectorResult(partial_errors=[_rate_limited("recruitee", resp.headers)])
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[
                    _provider_error(f"recruitee fetch failed with status {resp.status}")
                ]
            )
        try:
            items, row_errors = parse_recruitee_payload(resp.body)
        except (json.JSONDecodeError, ValueError) as exc:
            return ConnectorResult(partial_errors=[_protocol_error(f"recruitee parse: {exc}")])
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, resp.etag, resp.last_modified),
            partial_errors=row_errors,
        )


# --------------------------------------------------------------- teamtailor


class TeamtailorConfig(BaseModel):
    company: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
    )
    max_items: int = Field(default=100, ge=1, le=300)


TEAMTAILOR_DOMAINS = ("*.teamtailor.com",)


def teamtailor_feed_url(company: str) -> str:
    return f"https://{company}.teamtailor.com/jobs.json"


def _jsonld_location(posting: dict) -> LocationSpec:
    raw_location = posting.get("jobLocation")
    if isinstance(raw_location, list):
        raw_location = raw_location[0] if raw_location else {}
    location = raw_location if isinstance(raw_location, dict) else {}
    raw_address = location.get("address")
    if isinstance(raw_address, list):
        raw_address = raw_address[0] if raw_address else {}
    address = raw_address if isinstance(raw_address, dict) else {}
    return LocationSpec(
        city=str(address.get("addressLocality") or "").strip() or None,
        country=str(address.get("addressCountry") or "").strip() or None,
        remote=str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE",
    )


def _jsonld_salary(posting: dict) -> SalarySpec | None:
    raw_salary = posting.get("baseSalary")
    salary_node = raw_salary if isinstance(raw_salary, dict) else {}
    raw_value = salary_node.get("value")
    if isinstance(raw_value, list):
        raw_value = raw_value[0] if raw_value else {}
    value = raw_value if isinstance(raw_value, dict) else {}
    minimum = _money(value.get("minValue"))
    maximum = _money(value.get("maxValue"))
    if minimum is None and maximum is None:
        return None
    return SalarySpec(
        currency=_currency(value.get("currency")),
        min=minimum,
        max=maximum,
        period=_JSONLD_UNIT.get(str(value.get("unitText") or "").upper(), "year"),  # type: ignore[arg-type]
    )


def parse_teamtailor_payload(body: str) -> tuple[list[RawPosting], list[ConnectorError]]:
    """JSON Feed 1.1 ``{items: [{id, title, url, date_published,
    content_html, _jobposting (schema.org JobPosting)}]}``."""
    data = json.loads(body)
    rows = data.get("items")
    if not isinstance(rows, list):
        raise ValueError("payload 'items' is not a list")
    items: list[RawPosting] = []
    errors: list[ConnectorError] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append(_invalid_row("teamtailor row is not an object"))
            continue
        external_id = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not external_id or not title:
            errors.append(_invalid_row(f"teamtailor row missing id/title (id={external_id!r})"))
            continue
        raw_posting = row.get("_jobposting")
        posting = raw_posting if isinstance(raw_posting, dict) else {}
        raw_hiring = posting.get("hiringOrganization")
        if isinstance(raw_hiring, list):
            raw_hiring = raw_hiring[0] if raw_hiring else {}
        hiring = raw_hiring if isinstance(raw_hiring, dict) else {}
        employment = posting.get("employmentType")
        items.append(
            RawPosting(
                external_id=external_id[:300],
                title=title[:300],
                org=str(hiring.get("name") or "")[:200],
                location=_jsonld_location(posting),
                url=str(row.get("url") or "")[:1000],
                posted_at=_parse_iso_utc(row.get("date_published")),
                salary=_jsonld_salary(posting),
                employment_type=cast(
                    EmploymentType | None,
                    _employment_type(employment if isinstance(employment, list) else [employment]),
                ),
                skills_raw=[
                    str(skill) for skill in (posting.get("skills") or []) if str(skill).strip()
                ][:60],
                raw={
                    "description": str(posting.get("description") or row.get("content_html") or "")[
                        :8000
                    ],
                    "industry": str(posting.get("industry") or ""),
                    "job_location_type": str(posting.get("jobLocationType") or ""),
                },
            )
        )
    return items, errors


class TeamtailorConnector(PostingConnector):
    """Teamtailor's public per-tenant JSON Feed — free, no auth. Each item
    carries an embedded schema.org JobPosting (``_jobposting``)."""

    key = "teamtailor"
    title = "Teamtailor careers feed"
    docs_url = "https://docs.career-assistant.local/connectors/teamtailor"
    capabilities = ConnectorCapabilities(
        network_scopes=list(TEAMTAILOR_DOMAINS),
        supports_incremental=True,
        max_requests_per_minute=10,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return TeamtailorConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = TeamtailorConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        resp = await transport(teamtailor_feed_url(cfg.company), conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status == 429:
            return ConnectorResult(partial_errors=[_rate_limited("teamtailor", resp.headers)])
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[
                    _provider_error(f"teamtailor fetch failed with status {resp.status}")
                ]
            )
        try:
            items, row_errors = parse_teamtailor_payload(resp.body)
        except (json.JSONDecodeError, ValueError) as exc:
            return ConnectorResult(partial_errors=[_protocol_error(f"teamtailor parse: {exc}")])
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, resp.etag, resp.last_modified),
            partial_errors=row_errors,
        )


# ----------------------------------------------------------- stepstone/xing


class StepstoneXingConfig(BaseModel):
    provider: str = Field(default="stepstone", pattern="^(stepstone|xing)$")
    feed_url: str | None = Field(default=None, max_length=1000)
    max_items: int = Field(default=100, ge=1, le=300)


def parse_rss_jobs_payload(body: str) -> tuple[list[RawPosting], list[ConnectorError]]:
    """RSS 2.0 job alerts: guid/link = id, title, pubDate, source, description."""
    root = ET.fromstring(body)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("payload has no <channel>")
    items: list[RawPosting] = []
    errors: list[ConnectorError] = []
    for node in channel.findall("item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        guid = (node.findtext("guid") or link or title).strip()
        if not title or not guid:
            errors.append(_invalid_row("rss row missing title/guid"))
            continue
        description = (node.findtext("description") or "")[:8000]
        items.append(
            RawPosting(
                external_id=guid[:300],
                title=title[:300],
                org=(node.findtext("source") or "").strip()[:200],
                url=link[:1000],
                posted_at=_parse_rfc822_utc(node.findtext("pubDate")),
                salary=parse_salary_text(title),
                skills_raw=[
                    category for category in [(node.findtext("category") or "").strip()] if category
                ],
                raw={
                    "description": description,
                    "region": (node.findtext("region") or "").strip(),
                    "category": (node.findtext("category") or "").strip(),
                },
            )
        )
    return items, errors


class StepstoneXingConnector(PostingConnector):
    """StepStone/Xing saved-search job alerts over RSS 2.0.

    Neither board publishes an anonymous public job API, so this bundle
    consumes the RSS URL the board gives a signed-in job alert. The
    transport guard is the SSRF/robots/rate discipline (no static domain
    scope, like the generic ``rss`` connector)."""

    key = "stepstone_xing"
    title = "StepStone / Xing job alerts (RSS)"
    docs_url = "https://docs.career-assistant.local/connectors/stepstone-xing"
    capabilities = ConnectorCapabilities(
        supports_incremental=True,
        requires_credentials=True,
        max_requests_per_minute=10,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return StepstoneXingConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = StepstoneXingConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        feed_url = str((secrets or {}).get("feed_url") or "").strip()
        if not feed_url:
            return ConnectorResult(
                partial_errors=[
                    ConnectorError.needs_secret("the personal StepStone/Xing alert URL is not set")
                ]
            )
        if not feed_url.startswith("https://"):
            return ConnectorResult(partial_errors=[_protocol_error("the alert URL must be https")])
        resp = await transport(feed_url, conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status == 429:
            return ConnectorResult(partial_errors=[_rate_limited(cfg.provider, resp.headers)])
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[
                    _provider_error(f"{cfg.provider} rss fetch failed with status {resp.status}")
                ]
            )
        try:
            items, row_errors = parse_rss_jobs_payload(resp.body)
        except (ET.ParseError, ValueError) as exc:
            return ConnectorResult(partial_errors=[_protocol_error(f"rss parse: {exc}")])
        items = _apply_watermark(items, state or {})
        items = _sort_and_cap(items, cfg.max_items)
        return ConnectorResult(
            items=items,
            next_state=_stamp_watermark(state or {}, items, resp.etag, resp.last_modified),
            partial_errors=row_errors,
        )


__all__ = [
    "JoinComConnector",
    "PersonioConnector",
    "RecruiteeConnector",
    "StepstoneXingConnector",
    "TeamtailorConnector",
    "parse_join_payload",
    "parse_personio_payload",
    "parse_recruitee_payload",
    "parse_rss_jobs_payload",
    "parse_teamtailor_payload",
]
