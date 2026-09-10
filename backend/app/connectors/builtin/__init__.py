"""First-party built-in connectors (Phase 26): ATS APIs, JSON-LD, RSS, CSV,
manual URL. All legal-and-free sources; anything else ships as a plugin
over the same SDK. Parsers are pure functions of fixture payloads; the
injected transport keeps politeness (conditional GET, robots, caps) in
the runtime, not in connector code.
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.connectors.base import (
    ConnectorCapabilities,
    ConnectorResult,
    PostingConnector,
    RawPosting,
    SalarySpec,
)


def _merge_state(state: dict, etag: str | None, last_modified: str | None) -> dict:
    next_state = dict(state or {})
    if etag:
        next_state["etag"] = etag
    if last_modified:
        next_state["last_modified"] = last_modified
    return next_state


def _conditional_headers(state: dict) -> dict:
    headers = {}
    if state and state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state and state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    return headers


def _parse_dt(value: str | None) -> Optional[datetime]:
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
                location={
                    "city": row.get("city") or None,
                    "country": row.get("country") or None,
                    "remote": (row.get("remote") or "").lower() in {"1", "true", "yes"},
                },
                url=row.get("url") or "",
                posted_at=_parse_dt(row.get("posted_at")),
                expires_at=_parse_dt(row.get("expires_at")),
                salary=salary,
                seniority=row.get("seniority") or None,
                employment_type=row.get("employment_type") or None,
                onsite_policy=row.get("onsite_policy") or None,
                skills_raw=skills,
                raw=raw,
            )
        )
    return postings


class CsvConnector(PostingConnector):
    key = "csv"
    title = "CSV file"
    docs_url = "https://docs.career-assistant.local/connectors/csv"
    capabilities = ConnectorCapabilities(
        supports_incremental=True, max_requests_per_minute=10
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return CsvConfig

    async def fetch(self, config, state, *, transport=None, **_kw) -> ConnectorResult:
        cfg = self.config_model().model_validate(config)
        errors: list[str] = []
        postings: list[RawPosting] = []
        next_state = dict(state or {})
        if transport is not None:
            status, body, etag, last_modified = await transport(
                str(cfg.url), _conditional_headers(state or {})
            )
            if status == 304:
                return ConnectorResult(
                    postings=[], next_state=_merge_state(state, etag, last_modified)
                )
            if status != 200:
                return ConnectorResult(
                    partial_errors=[f"csv fetch failed with status {status}"],
                    next_state=next_state,
                )
            try:
                postings = parse_csv_payload(body)
            except (csv.Error, ValueError) as exc:
                errors.append(f"csv parse error: {exc}")
            next_state = _merge_state(state, etag, last_modified)
        return ConnectorResult(
            postings=postings, next_state=next_state, partial_errors=errors
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
            external_id = str(
                node.get("identifier") or node.get("url") or node.get("title") or ""
            )
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
                skills = [
                    s.strip() for s in re.split(r"[,;]", str(skills_blob)) if s.strip()
                ]
            salary = None
            if value_node:
                salary = SalarySpec(
                    currency=str(value_node.get("currency") or "USD")[:3],
                    min=float(value_node["minValue"])
                    if value_node.get("minValue")
                    else None,
                    max=float(value_node["maxValue"])
                    if value_node.get("maxValue")
                    else None,
                )
            employment_type = node.get("employmentType")
            postings.append(
                RawPosting(
                    external_id=external_id[:300],
                    title=_text(node.get("title") or node.get("name"))
                    or "Untitled posting",
                    org=org,
                    url=str(node.get("url") or ""),
                    posted_at=_parse_dt(node.get("datePosted")),
                    expires_at=_parse_dt(node.get("validThrough")),
                    employment_type=(
                        str(employment_type).split(".")[-1].lower()
                        if employment_type
                        else None
                    ),
                    education_level=_text(node.get("educationRequirements")) or None,
                    skills_raw=skills[:60],
                    raw={"description": str(node.get("description") or "")[:8000]},
                    location={
                        "city": _text(address.get("addressLocality")) or None,
                        "country": _text(address.get("addressCountry")) or None,
                        "remote": "remote"
                        in str(node.get("jobLocationType", "")).lower(),
                    },
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

    async def fetch(self, config, state, *, transport=None, **_kw) -> ConnectorResult:
        cfg = self.config_model().model_validate(config)
        if transport is None:
            return ConnectorResult()
        status, body, etag, last_modified = await transport(
            str(cfg.url), _conditional_headers(state or {})
        )
        if status == 304:
            return ConnectorResult(next_state=_merge_state(state, etag, last_modified))
        if status != 200:
            return ConnectorResult(
                partial_errors=[f"jsonld fetch failed with status {status}"]
            )
        postings = parse_jsonld_payload(body)
        return ConnectorResult(
            postings=postings, next_state=_merge_state(state, etag, last_modified)
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

    async def fetch(self, config, state, *, transport=None, **_kw) -> ConnectorResult:
        cfg = self.config_model().model_validate(config)
        if transport is None:
            return ConnectorResult()
        status, body, etag, last_modified = await transport(
            str(cfg.url), _conditional_headers(state or {})
        )
        if status == 304:
            return ConnectorResult(next_state=_merge_state(state, etag, last_modified))
        if status != 200:
            return ConnectorResult(
                partial_errors=[f"rss fetch failed with status {status}"]
            )
        try:
            postings = parse_rss_payload(body)
        except ET.ParseError as exc:
            return ConnectorResult(partial_errors=[f"rss parse error: {exc}"])
        return ConnectorResult(
            postings=postings, next_state=_merge_state(state, etag, last_modified)
        )


class AtsApiConfig(BaseModel):
    provider: str = Field(pattern="^(greenhouse|lever|ashby)$")
    org: str = Field(min_length=1, max_length=120)
    api_token: str = Field(default="", max_length=300)


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
                org=str(
                    data.get("metadata", {}).get("title")
                    or job.get("absolute_url")
                    or ""
                ),
                url=str(job.get("absolute_url") or ""),
                posted_at=_parse_dt(
                    job.get("updated_at") or job.get("first_published")
                ),
                location={
                    "city": (job.get("location") or {}).get("name") or None,
                    "remote": "remote"
                    in str((job.get("location") or {}).get("name", "")).lower(),
                },
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
                    datetime.fromtimestamp(
                        job["createdAt"] / 1000, tz=timezone.utc
                    ).isoformat()
                )
                if job.get("createdAt")
                else None,
                location={
                    "city": categories.get("location") or None,
                    "remote": "remote" in str(categories.get("location") or "").lower(),
                },
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
        postings.append(
            RawPosting(
                external_id=str(job.get("id") or "")[:300],
                title=(job.get("title") or "Untitled")[:300],
                org=str(job.get("organization") or ""),
                url=str(job.get("jobUrl") or ""),
                posted_at=_parse_dt(job.get("publishedAt") or job.get("updatedAt")),
                location={
                    "city": (job.get("location") or "").get("city")
                    if isinstance(job.get("location"), dict)
                    else None,
                    "remote": bool(
                        (job.get("isRemote") if "isRemote" in job else False)
                    ),
                },
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


class AtsApiConnector(PostingConnector):
    """Public ATS board APIs (Greenhouse/Lever/Ashby) — legal, free, no auth
    for public boards; token optional for partner tiers."""

    key = "ats_api"
    title = "ATS public API (Greenhouse / Lever / Ashby)"
    docs_url = "https://docs.career-assistant.local/connectors/ats"
    capabilities = ConnectorCapabilities(
        supports_incremental=True, max_requests_per_minute=20
    )
    fixture_payload = ""

    def config_model(self) -> type[BaseModel]:
        return AtsApiConfig

    async def fetch(self, config, state, *, transport=None, **_kw) -> ConnectorResult:
        cfg = self.config_model().model_validate(config)
        urls = {
            "greenhouse": GREENHOUSE_URL.format(org=cfg.org),
            "lever": LEVER_URL.format(org=cfg.org),
            "ashby": ASHBY_URL.format(org=cfg.org),
        }
        url = urls[cfg.provider]
        if transport is None:
            return ConnectorResult()
        headers = _conditional_headers(state or {})
        if cfg.api_token:
            headers["Authorization"] = f"Bearer {cfg.api_token}"
        status, body, etag, last_modified = await transport(url, headers)
        if status == 304:
            return ConnectorResult(next_state=_merge_state(state, etag, last_modified))
        if status != 200:
            return ConnectorResult(
                partial_errors=[
                    f"ats fetch failed with status {status} for {cfg.provider}/{cfg.org}"
                ]
            )
        parsers = {
            "greenhouse": parse_greenhouse_payload,
            "lever": parse_lever_payload,
            "ashby": parse_ashby_payload,
        }
        try:
            postings = parsers[cfg.provider](body)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return ConnectorResult(partial_errors=[f"ats parse error: {exc}"])
        return ConnectorResult(
            postings=postings, next_state=_merge_state(state, etag, last_modified)
        )


class ManualUrlConfig(BaseModel):
    url: str = Field(min_length=1, max_length=1000)


class ManualUrlConnector(PostingConnector):
    """Paste-a-URL: fetch one page and extract JSON-LD JobPosting data."""

    key = "manual_url"
    title = "Paste a posting URL"
    docs_url = "https://docs.career-assistant.local/connectors/manual"
    capabilities = ConnectorCapabilities(
        supports_incremental=False, max_requests_per_minute=10
    )

    def config_model(self) -> type[BaseModel]:
        return ManualUrlConfig

    async def fetch(self, config, state, *, transport=None, **_kw) -> ConnectorResult:
        cfg = self.config_model().model_validate(config)
        if transport is None:
            return ConnectorResult()
        status, body, etag, last_modified = await transport(
            str(cfg.url), _conditional_headers(state or {})
        )
        if status != 200:
            return ConnectorResult(
                partial_errors=[f"manual fetch failed with status {status}"]
            )
        postings = parse_jsonld_payload(body)
        if not postings:
            title_match = re.search(
                r"<title>(.*?)</title>", body or "", re.DOTALL | re.IGNORECASE
            )
            if title_match:
                postings.append(
                    RawPosting(
                        external_id=cfg.url[:300],
                        title=title_match.group(1).strip()[:300],
                        url=str(cfg.url),
                    )
                )
        return ConnectorResult(
            postings=postings, next_state=_merge_state(state, etag, last_modified)
        )
