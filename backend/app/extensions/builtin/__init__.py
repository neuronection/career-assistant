"""First-party built-in connectors (Phase 26): ATS APIs, JSON-LD, RSS, CSV,
manual URL — plus the real-content job boards (Arbeitnow, Remotive,
Jobicy — live public JSON APIs, bundled T1). All legal-and-free sources;
anything else ships as a plugin over the same SDK. Parsers are pure
functions of fixture payloads; the injected transport keeps politeness
(conditional GET, robots, caps) in the runtime, not in connector code.
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel, Field

from app.extensions.builtin.job_boards import (
    ArbeitnowConnector as ArbeitnowConnector,
)
from app.extensions.builtin.job_boards import (
    JobicyConnector as JobicyConnector,
)
from app.extensions.builtin.job_boards import (
    RemotiveConnector as RemotiveConnector,
)
from app.extensions.polite_http import conditional_headers, merge_cache_state
from app.extensions.sdk import (
    ConnectorCapabilities,
    ConnectorError,
    ConnectorResult,
    EmploymentType,
    LocationSpec,
    OnsitePolicy,
    PostingConnector,
    RawPosting,
    SalarySpec,
    SeniorityLevel,
)


def _not_ready() -> ConnectorResult:
    """No transport injected: the runtime (or a test) always provides one —
    never a silent empty fetch (fail closed)."""
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


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class CsvConfig(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    delimiter: str = Field(default=",", max_length=1)


def parse_csv_payload(body: str) -> list[RawPosting]:
    """CSV columns: external_id,title,org,city,country,remote,url,posted_at,
    expires_at,salary_min,salary_max,salary_currency,seniority,employment_type,
    skills (pipe-separated). Unknown columns land in `raw`."""
    known = {
        "external_id",
        "title",
        "org",
        "city",
        "country",
        "remote",
        "url",
        "posted_at",
        "expires_at",
        "salary_min",
        "salary_max",
        "salary_currency",
        "seniority",
        "employment_type",
        "skills",
        "onsite_policy",
    }
    postings: list[RawPosting] = []
    for row in csv.DictReader(io.StringIO(body)):
        if not (row.get("external_id") and row.get("title")):
            continue
        raw = {k: v for k, v in row.items() if v and k not in known}
        skills = [s.strip() for s in (row.get("skills") or "").split("|") if s.strip()]
        salary = None
        if row.get("salary_min") or row.get("salary_max"):
            salary = SalarySpec(
                currency=(row.get("salary_currency") or "USD")[:3],
                min=float(row["salary_min"]) if row.get("salary_min") else None,
                max=float(row["salary_max"]) if row.get("salary_max") else None,
            )
        postings.append(
            RawPosting(
                external_id=row["external_id"][:300],
                title=row["title"][:300],
                org=row.get("org") or "",
                location=LocationSpec(
                    city=row.get("city") or None,
                    country=row.get("country") or None,
                    remote=(row.get("remote") or "").lower() in {"1", "true", "yes"},
                ),
                url=row.get("url") or "",
                posted_at=_parse_dt(row.get("posted_at")),
                expires_at=_parse_dt(row.get("expires_at")),
                salary=salary,
                seniority=cast(SeniorityLevel, row.get("seniority") or None),
                employment_type=cast(EmploymentType, row.get("employment_type") or None),
                onsite_policy=cast(OnsitePolicy, row.get("onsite_policy") or None),
                skills_raw=skills,
                raw=raw,
            )
        )
    return postings


class CsvConnector(PostingConnector):
    key = "csv"
    title = "CSV file"
    docs_url = "https://docs.career-assistant.local/connectors/csv"
    capabilities = ConnectorCapabilities(supports_incremental=True, max_requests_per_minute=10)
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return CsvConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = CsvConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        errors: list[ConnectorError] = []
        items: list[RawPosting] = []
        resp = await transport(str(cfg.url), conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[_provider_error(f"csv fetch failed with status {resp.status}")]
            )
        try:
            items = parse_csv_payload(resp.body)
        except (csv.Error, ValueError) as exc:
            errors.append(_protocol_error(f"csv parse error: {exc}"))
        return ConnectorResult(
            items=items,
            next_state=merge_cache_state(state, resp.etag, resp.last_modified),
            partial_errors=errors,
        )


JSONLD_SCRIPT = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)


def job_postings_from_jsonld(data) -> list[dict]:
    """Extract schema.org JobPosting dicts from parsed JSON-LD (@graph aware)."""
    found: list[dict] = []
    if isinstance(data, dict):
        if data.get("@type") in ("JobPosting", ["JobPosting"]):
            found.append(data)
        for value in data.values():
            if isinstance(value, (dict, list)):
                found.extend(job_postings_from_jsonld(value))
    elif isinstance(data, list):
        for item in data:
            found.extend(job_postings_from_jsonld(item))
    return found


def _text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def parse_jsonld_payload(body: str) -> list[RawPosting]:
    postings: list[RawPosting] = []
    for match in JSONLD_SCRIPT.finditer(body or ""):
        try:
            data = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        for node in job_postings_from_jsonld(data):
            external_id = str(node.get("identifier") or node.get("url") or node.get("title") or "")
            if not external_id:
                continue
            org = _text(node.get("hiringOrganization"))
            location = node.get("jobLocation") or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            address = (location or {}).get("address") or {}
            if isinstance(address, list):
                address = address[0] if address else {}
            salary_node = node.get("baseSalary") or {}
            value_node = (salary_node or {}).get("value") or {}
            skills_blob = node.get("skills") or node.get("qualifications") or ""
            if isinstance(skills_blob, list):
                skills = [_text(s) for s in skills_blob]
            else:
                skills = [s.strip() for s in re.split(r"[,;]", str(skills_blob)) if s.strip()]
            salary = None
            if value_node:
                salary = SalarySpec(
                    currency=str(value_node.get("currency") or "USD")[:3],
                    min=float(value_node["minValue"]) if value_node.get("minValue") else None,
                    max=float(value_node["maxValue"]) if value_node.get("maxValue") else None,
                )
            employment_type = node.get("employmentType")
            postings.append(
                RawPosting(
                    external_id=external_id[:300],
                    title=_text(node.get("title") or node.get("name")) or "Untitled posting",
                    org=org,
                    url=str(node.get("url") or ""),
                    posted_at=_parse_dt(node.get("datePosted")),
                    expires_at=_parse_dt(node.get("validThrough")),
                    employment_type=(
                        cast(
                            EmploymentType,
                            str(employment_type).split(".")[-1].lower()
                            if employment_type
                            else None,
                        )
                    ),
                    education_level=_text(node.get("educationRequirements")) or None,
                    skills_raw=skills[:60],
                    raw={"description": str(node.get("description") or "")[:8000]},
                    location=LocationSpec(
                        city=_text(address.get("addressLocality")) or None,
                        country=_text(address.get("addressCountry")) or None,
                        remote="remote" in str(node.get("jobLocationType", "")).lower(),
                    ),
                    salary=salary,
                )
            )
    return postings


class JsonLdConfig(BaseModel):
    url: str = Field(min_length=1, max_length=1000)


class JsonLdConnector(PostingConnector):
    key = "jsonld"
    title = "schema.org JobPosting page"
    docs_url = "https://docs.career-assistant.local/connectors/jsonld"
    capabilities = ConnectorCapabilities(supports_incremental=True)
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return JsonLdConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = JsonLdConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        resp = await transport(str(cfg.url), conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[_provider_error(f"jsonld fetch failed with status {resp.status}")]
            )
        items = parse_jsonld_payload(resp.body)
        return ConnectorResult(
            items=items, next_state=merge_cache_state(state, resp.etag, resp.last_modified)
        )


def parse_rss_payload(body: str) -> list[RawPosting]:
    """RSS 2.0 or Atom; guid/atom:id = external id, description rides along."""
    postings: list[RawPosting] = []
    root = ET.fromstring(body)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        guid = (item.findtext("guid") or item.findtext("link") or title).strip()
        if not title or not guid:
            continue
        postings.append(
            RawPosting(
                external_id=guid[:300],
                title=title[:300],
                org=(item.findtext("source") or "").strip(),
                url=(item.findtext("link") or "").strip(),
                posted_at=_parse_dt(item.findtext("pubDate")),
                raw={"description": (item.findtext("description") or "")[:8000]},
            )
        )
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
        guid = (entry.findtext("atom:id", namespaces=ns) or "").strip()
        link_node = entry.find("atom:link", ns)
        link = link_node.get("href", "") if link_node is not None else ""
        if not title or not guid:
            continue
        summary = (entry.findtext("atom:summary", namespaces=ns) or "")[:8000]
        updated = _parse_dt(entry.findtext("atom:updated", namespaces=ns))
        postings.append(
            RawPosting(
                external_id=guid[:300],
                title=title[:300],
                url=link,
                posted_at=updated,
                raw={"description": summary},
            )
        )
    return postings


class RssConfig(BaseModel):
    url: str = Field(min_length=1, max_length=1000)


class RssConnector(PostingConnector):
    key = "rss"
    title = "RSS / Atom feed"
    docs_url = "https://docs.career-assistant.local/connectors/rss"
    capabilities = ConnectorCapabilities(supports_incremental=True)

    def config_model(self) -> type[BaseModel]:
        return RssConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = RssConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        resp = await transport(str(cfg.url), conditional_headers(state or {}))
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[_provider_error(f"rss fetch failed with status {resp.status}")]
            )
        try:
            items = parse_rss_payload(resp.body)
        except ET.ParseError as exc:
            return ConnectorResult(partial_errors=[_protocol_error(f"rss parse error: {exc}")])
        return ConnectorResult(
            items=items, next_state=merge_cache_state(state, resp.etag, resp.last_modified)
        )


class AtsApiConfig(BaseModel):
    provider: str = Field(pattern="^(greenhouse|lever|ashby)$")
    org: str = Field(min_length=1, max_length=120)


GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{org}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"


def parse_greenhouse_payload(body: str) -> list[RawPosting]:
    data = json.loads(body)
    postings = []
    for job in data.get("jobs") or []:
        content = job.get("content") or ""
        try:
            description = json.loads(f'"{content}"') if content else ""
        except json.JSONDecodeError:
            description = content
        postings.append(
            RawPosting(
                external_id=str(job.get("id") or "")[:300],
                title=(job.get("title") or "Untitled")[:300],
                org=str(data.get("metadata", {}).get("title") or job.get("absolute_url") or ""),
                url=str(job.get("absolute_url") or ""),
                posted_at=_parse_dt(job.get("updated_at") or job.get("first_published")),
                location=LocationSpec(
                    city=(job.get("location") or {}).get("name") or None,
                    remote="remote" in str((job.get("location") or {}).get("name", "")).lower(),
                ),
                raw={"description": str(description)[:8000]},
            )
        )
    return postings


def parse_lever_payload(body: str) -> list[RawPosting]:
    data = json.loads(body)
    postings = []
    for job in data:
        categories = job.get("categories") or {}
        postings.append(
            RawPosting(
                external_id=str(job.get("id") or "")[:300],
                title=(job.get("text") or "Untitled")[:300],
                url=str(job.get("hostedUrl") or ""),
                posted_at=_parse_dt(
                    datetime.fromtimestamp(job["createdAt"] / 1000, tz=UTC).isoformat()
                )
                if job.get("createdAt")
                else None,
                location=LocationSpec(
                    city=categories.get("location") or None,
                    remote="remote" in str(categories.get("location") or "").lower(),
                ),
                employment_type=(categories.get("commitment") or None),
                skills_raw=list(job.get("skills") or [])[:60],
                raw={"description": str(job.get("description") or "")[:8000]},
            )
        )
    return postings


def parse_ashby_payload(body: str) -> list[RawPosting]:
    data = json.loads(body)
    postings = []
    for job in data.get("jobs") or []:
        loc = job.get("location")
        postings.append(
            RawPosting(
                external_id=str(job.get("id") or "")[:300],
                title=(job.get("title") or "Untitled")[:300],
                org=str(job.get("organization") or ""),
                url=str(job.get("jobUrl") or ""),
                posted_at=_parse_dt(job.get("publishedAt") or job.get("updatedAt")),
                location=LocationSpec(
                    city=loc.get("city") if isinstance(loc, dict) else None,
                    remote=bool(job.get("isRemote") if "isRemote" in job else False),
                ),
                employment_type=(job.get("employmentType") or None),
                seniority=(job.get("seniority") or None),
                raw={
                    "description": str(
                        job.get("descriptionPlain") or job.get("descriptionHtml") or ""
                    )[:8000]
                },
            )
        )
    return postings


ATS_PROVIDERS = ("greenhouse", "lever", "ashby")
ATS_NETWORK_SCOPES = ("boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com")


class AtsApiConnector(PostingConnector):
    """Public ATS board APIs (Greenhouse/Lever/Ashby) — legal, free, no auth
    for public boards; token optional for partner tiers (secret slot)."""

    key = "ats_api"
    title = "ATS public API (Greenhouse / Lever / Ashby)"
    docs_url = "https://docs.career-assistant.local/connectors/ats"
    capabilities = ConnectorCapabilities(
        network_scopes=list(ATS_NETWORK_SCOPES),
        supports_incremental=True,
        max_requests_per_minute=20,
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return AtsApiConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = AtsApiConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        token = (secrets or {}).get("api_token")
        urls = {
            "greenhouse": GREENHOUSE_URL.format(org=cfg.org),
            "lever": LEVER_URL.format(org=cfg.org),
            "ashby": ASHBY_URL.format(org=cfg.org),
        }
        url = urls[cfg.provider]
        headers = conditional_headers(state or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = await transport(url, headers)
        if resp.status == 304:
            return ConnectorResult(
                next_state=merge_cache_state(state, resp.etag, resp.last_modified)
            )
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[
                    _provider_error(
                        f"ats fetch failed with status {resp.status} for {cfg.provider}/{cfg.org}"
                    )
                ]
            )
        parsers = {
            "greenhouse": parse_greenhouse_payload,
            "lever": parse_lever_payload,
            "ashby": parse_ashby_payload,
        }
        try:
            items = parsers[cfg.provider](resp.body)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return ConnectorResult(partial_errors=[_protocol_error(f"ats parse error: {exc}")])
        return ConnectorResult(
            items=items, next_state=merge_cache_state(state, resp.etag, resp.last_modified)
        )


class ManualUrlConfig(BaseModel):
    url: str = Field(min_length=1, max_length=1000)


class ManualUrlConnector(PostingConnector):
    """Paste-a-URL: fetch one page and extract JSON-LD JobPosting data."""

    key = "manual_url"
    title = "Paste a posting URL"
    docs_url = "https://docs.career-assistant.local/connectors/manual"
    capabilities = ConnectorCapabilities(supports_incremental=False, max_requests_per_minute=10)

    def config_model(self) -> type[BaseModel]:
        return ManualUrlConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        cfg = ManualUrlConfig.model_validate(config)
        if transport is None:
            return _not_ready()
        resp = await transport(str(cfg.url), conditional_headers(state or {}))
        if resp.status != 200:
            return ConnectorResult(
                partial_errors=[_provider_error(f"manual fetch failed with status {resp.status}")]
            )
        items = parse_jsonld_payload(resp.body)
        if not items:
            title_match = re.search(
                r"<title>(.*?)</title>", resp.body or "", re.DOTALL | re.IGNORECASE
            )
            if title_match:
                items.append(
                    RawPosting(
                        external_id=cfg.url[:300],
                        title=title_match.group(1).strip()[:300],
                        url=str(cfg.url),
                    )
                )
        return ConnectorResult(
            items=items, next_state=merge_cache_state(state, resp.etag, resp.last_modified)
        )
