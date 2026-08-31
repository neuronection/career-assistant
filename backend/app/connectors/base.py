"""Connector SDK (Phase 26): the only extension point for posting sources.

Connectors are pure normalizers: `fetch(config, state) -> ConnectorResult`
with no DB and no AI access. Everything downstream (mapping, fit, feed,
alerts) is connector-agnostic. Legal/operational constraints are a
contract: connectors declare rate limits; the runtime enforces polite
fetching (conditional GET, per-source caps, robots.txt for URL kinds).
"""

from __future__ import annotations

from datetime import datetime
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field

from app.models.base import StructuredJSON  # noqa: F401 — re-export convenience


class SalarySpec(BaseModel):
    """ISO-4217 currency + NUMERIC range + period (plan 42 money policy)."""

    currency: str = Field(default="USD", min_length=3, max_length=3)
    min: Optional[float] = Field(default=None, ge=0)
    max: Optional[float] = Field(default=None, ge=0)
    period: Literal["hour", "day", "week", "month", "year"] = "year"


class LocationSpec(BaseModel):
    city: Optional[str] = None
    country: Optional[str] = None
    remote: bool = False


class RawPosting(BaseModel):
    """The only type a connector may emit — normalized, pre-taxonomy."""

    external_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    org: str = Field(default="", max_length=200)
    location: LocationSpec = Field(default_factory=LocationSpec)
    url: str = Field(default="", max_length=1000)
    posted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    salary: Optional[SalarySpec] = None
    seniority: Optional[
        Literal["intern", "junior", "mid", "senior", "lead", "principal"]
    ] = None
    employment_type: Optional[
        Literal["full_time", "part_time", "contract", "temporary", "internship"]
    ] = None
    contract_type: Optional[str] = Field(default=None, max_length=60)
    onsite_policy: Optional[Literal["onsite", "hybrid", "remote"]] = None
    work_hours: Optional[str] = Field(default=None, max_length=60)
    hours_per_week_min: Optional[float] = Field(default=None, ge=0)
    hours_per_week_max: Optional[float] = Field(default=None, ge=0)
    travel_class: Optional[str] = Field(default=None, max_length=60)
    education_level: Optional[str] = Field(default=None, max_length=40)
    # Skill mentions BEFORE taxonomy mapping (free text/keys); core maps them.
    skills_raw: list[str] = Field(default_factory=list, max_length=60)
    raw: dict = Field(default_factory=dict)


class ConnectorCapabilities(BaseModel):
    network_scopes: list[str] = Field(default_factory=list)
    requires_credentials: bool = False
    supports_incremental: bool = False
    max_requests_per_minute: int = Field(default=30, ge=1)
    url_fetching: bool = True


class ConnectorResult(BaseModel):
    postings: list[RawPosting] = Field(default_factory=list)
    next_state: dict = Field(default_factory=dict)
    partial_errors: list[str] = Field(default_factory=list)


# Transport injected by the runtime (or tests): polite GET returning
# (status, body, etag, last_modified). Connectors never open sockets
# themselves, so isolation + rate limiting stay in one place.
HttpTransport = Callable[
    [str, dict], Awaitable[tuple[int, str, str | None, str | None]]
]

FetchFn = Callable[..., Awaitable[ConnectorResult]]


class PostingConnector:
    """Protocol every connector engine implements (see dev/plans/26)."""

    key: str = ""
    title: str = ""
    docs_url: str = ""
    capabilities: ConnectorCapabilities = ConnectorCapabilities()
    fixture_payload: str | bytes = ""

    def config_model(self) -> type[BaseModel]:
        raise NotImplementedError

    async def fetch(
        self,
        config: dict,
        state: dict,
        *,
        transport: HttpTransport | None = None,
    ) -> ConnectorResult:
        raise NotImplementedError

    def validate_config(self, config: dict) -> dict:
        """Config round-trip: validated JSONB for `job_sources.config`."""
        return self.config_model().model_validate(config).model_dump(mode="json")


class EmptyConfig(BaseModel):
    """For connectors that need no per-source settings."""
