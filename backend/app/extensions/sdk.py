"""Connector SDK (Phase 26 / plan 32 Phase 1): the only extension point for
posting sources.

Connectors are pure normalizers: ``fetch(config, state, transport) ->
ConnectorResult`` with no DB and no AI access. Everything downstream
(mapping, fit, feed, alerts) is connector-agnostic. The result envelope is
the family extension charter's connector shape (ADR-0040 clause 9, D18
convergence): ``items``, opaque ``next_state`` and ``partial_errors`` as
TYPED charter errors (:class:`ConnectorError`) — never strings.

Politeness is enforced, not documented: connectors never open sockets.
The runtime injects the vendored polite HTTP transport
(:mod:`app.extensions.polite_http`, built app-side by
:mod:`app.extensions.runtime.http`) — SSRF guard with resolve-then-connect
pinning re-validated on every redirect hop, robots.txt (fail-closed),
per-host token buckets sized by each connector's declared cap,
conditional GET and response size caps. Legal/operational constraints are
a contract: declare your rate limit and network scopes; the runtime
enforces them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.extensions.polite_http import PoliteHttpError, PoliteResponse
from app.models.base import StructuredJSON  # noqa: F401 — re-export convenience

__all__ = [
    "RAW_POSTING_ITEM_SCHEMA",
    "AuditFn",
    "ConnectorCapabilities",
    "ConnectorError",
    "ConnectorResult",
    "EmptyConfig",
    "ExternalEffect",
    "HttpTransport",
    "LocationSpec",
    "PostingConnector",
    "RawPosting",
    "SalarySpec",
    "connector_manifest",
]

ErrorCode = Literal[
    "not-ready",
    "needs-secret",
    "invalid",
    "unsupported",
    "io",
    "not-found",
    "path-denied",
    "net-denied",
    "auth",
    "rate-limited",
    "unreachable",
    "protocol",
    "provider",
    "budget",
    "canceled",
]

Retryable = Literal["yes", "no", "after-delay", "after-config-change"]


class ConnectorError(BaseModel):
    """One typed charter error (ADR-0040 clause 4) — the only shape a
    partial error may take. ``detail`` is capped data, never a raw
    exception dump; ``retry_after_ms`` surfaces the RFC 7231 payload when
    the upstream sent one."""

    code: ErrorCode
    detail: str = Field(default="", max_length=500)
    retryable: Retryable
    retry_after_ms: int | None = Field(default=None, ge=0)

    @classmethod
    def from_polite(cls, exc: PoliteHttpError) -> ConnectorError:
        return cls(
            code=exc.code,  # type: ignore[arg-type]
            detail=exc.detail,
            retryable=exc.retryable,  # type: ignore[arg-type]
            retry_after_ms=exc.retry_after_ms,
        )

    @classmethod
    def needs_secret(cls, detail: str) -> ConnectorError:
        return cls(code="needs-secret", detail=detail[:500], retryable="after-config-change")


class SalarySpec(BaseModel):
    """ISO-4217 currency + NUMERIC range + period."""

    currency: str = Field(default="USD", min_length=3, max_length=3)
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, ge=0)
    period: Literal["hour", "day", "week", "month", "year"] = "year"


class LocationSpec(BaseModel):
    city: str | None = None
    country: str | None = None
    remote: bool = False


class RawPosting(BaseModel):
    """The only type a connector may emit — normalized, pre-taxonomy."""

    external_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    org: str = Field(default="", max_length=200)
    location: LocationSpec = Field(default_factory=LocationSpec)
    url: str = Field(default="", max_length=1000)
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    salary: SalarySpec | None = None
    seniority: Literal["intern", "junior", "mid", "senior", "lead", "principal"] | None = None
    employment_type: (
        Literal["full_time", "part_time", "contract", "temporary", "internship"] | None
    ) = None
    contract_type: str | None = Field(default=None, max_length=60)
    onsite_policy: Literal["onsite", "hybrid", "remote"] | None = None
    work_hours: str | None = Field(default=None, max_length=60)
    hours_per_week_min: float | None = Field(default=None, ge=0)
    hours_per_week_max: float | None = Field(default=None, ge=0)
    travel_class: str | None = Field(default=None, max_length=60)
    education_level: str | None = Field(default=None, max_length=40)
    # Skill mentions BEFORE taxonomy mapping (free text/keys); core maps them.
    skills_raw: list[str] = Field(default_factory=list, max_length=60)
    raw: dict = Field(default_factory=dict)


class ConnectorCapabilities(BaseModel):
    """Declared operational constraints; the runtime enforces them."""

    network_scopes: list[str] = Field(default_factory=list)
    requires_credentials: bool = False
    supports_incremental: bool = False
    max_requests_per_minute: int = Field(default=30, ge=1)
    url_fetching: bool = True


class ConnectorResult(BaseModel):
    """The charter result envelope (ADR-0040 clause 9): ``{items,
    next_state, partial_errors}``. ``next_state`` is opaque and
    host-round-tripped (conditional-GET validators ride it)."""

    items: list[RawPosting] = Field(default_factory=list)
    next_state: dict = Field(default_factory=dict)
    partial_errors: list[ConnectorError] = Field(default_factory=list)


# Transport injected by the runtime (or tests): a polite GET over the
# vendored runtime. Connectors never open sockets themselves, so the SSRF
# guard, robots, rate caps and size caps stay in one place.
HttpTransport = Callable[[str, dict], Awaitable[PoliteResponse]]


class ExternalEffect(BaseModel):
    """One observable external interaction of a fetch (charter lifecycle
    law: one audit row per external effect). Connectors with effects
    outside the injected transport — the T3 script tier's MCP tool calls
    — report each one through the injected ``audit`` callback; the host
    maps it onto the audit funnel. ``arguments``/``meta`` must already
    be secret-free."""

    kind: Literal["mcp_tool_call"]
    ref: str = Field(max_length=300)
    arguments: dict = Field(default_factory=dict)
    meta: dict = Field(default_factory=dict)
    ok: bool = True
    error: str = Field(default="", max_length=1000)
    latency_ms: float = Field(default=0.0, ge=0)


AuditFn = Callable[[ExternalEffect], Awaitable[None]]

FetchFn = Callable[..., Awaitable[ConnectorResult]]

RAW_POSTING_ITEM_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "external_id": {"type": "string", "title": "External id"},
        "title": {"type": "string", "title": "Title"},
        "url": {"type": "string", "title": "URL"},
    },
    "required": ["external_id", "title"],
}


def connector_manifest(
    *,
    manifest_id: str,
    title: str,
    config_schema: dict,
    capabilities: list[str],
    supports_incremental: bool,
    domains: list[str] | None = None,
    version: str = "1.0.0",
    description: str = "",
) -> dict:
    """Build a connector-kind extension manifest (envelope ``extension/v1``,
    ADR-0040 clause 5) for a bundled connector. ``capabilities`` declares
    the charter truth — ``net`` requires ``domains`` (the polite runtime's
    declared-domain scope); bundled connectors that fetch user-configured
    URLs declare ``sync`` only and get the host-side guard per instance."""

    manifest: dict = {
        "apiVersion": "extension/v1",
        "kindVersion": 1,
        "kind": "connector",
        "id": manifest_id,
        "version": version,
        "description": description[:400],
        "author": "Neuronection",
        "license": "MIT",
        "capabilities": capabilities,
        "configSchema": config_schema,
        "itemSchema": RAW_POSTING_ITEM_SCHEMA,
        "supportsIncremental": supports_incremental,
        "i18n": {
            "defaultLocale": "en",
            "locales": {"en": {"title": title, "summary": description[:200]}},
        },
    }
    if domains:
        manifest["domains"] = domains
    return manifest


class PostingConnector:
    """Protocol every connector engine implements."""

    key: str = ""
    title: str = ""
    docs_url: str = ""
    capabilities: ConnectorCapabilities = ConnectorCapabilities()
    fixture_payload: str | bytes = ""
    # Connectors that cause effects outside the injected transport (the
    # T3 script tier) set this: sync/probe then inject the ``audit``
    # callback so every external effect lands on the audit funnel.
    audits_effects: bool = False

    def config_model(self) -> type[BaseModel]:
        raise NotImplementedError

    def manifest(self) -> dict:
        """The connector-kind extension manifest — validated against the
        vendored envelope schema at registration (data, not code)."""
        return connector_manifest(
            manifest_id=f"career-{self.key.replace('_', '-')}",
            title=self.title or self.key,
            config_schema={
                "type": "object",
                "properties": {
                    name: {"type": _field_type(annotation)}
                    for name, annotation in self.config_model().model_fields.items()
                },
            },
            capabilities=["sync"],
            supports_incremental=self.capabilities.supports_incremental,
        )

    async def fetch(
        self,
        config: dict,
        state: dict,
        *,
        transport: HttpTransport | None = None,
        secrets: dict | None = None,
        audit: AuditFn | None = None,
    ) -> ConnectorResult:
        raise NotImplementedError

    def secret_slots(self) -> dict[str, str]:
        """Declared secret slots (D19): manifest ``configSchema`` fields
        marked ``x-secret: true`` plus the manifest ``secrets`` list —
        slot id → purpose. Values live only in the atrest-sealed
        ``job_sources.secrets`` store (INV-4), never in config."""
        from app.extensions.contract import secret_fields

        manifest = self.manifest()
        slots = dict.fromkeys(secret_fields(manifest.get("configSchema")), "")
        for slot in manifest.get("secrets") or []:
            if isinstance(slot, dict) and slot.get("id"):
                slots[slot["id"]] = slot.get("purpose") or ""
        return slots

    def validate_config(self, config: dict) -> dict:
        """Config round-trip: validated JSONB for `job_sources.config`.

        The x-secret law (ADR-0040 clause 18): a value present for any
        declared secret slot is a registration-time THROW — secrets never
        live in stored config. Model violations surface as the app's
        ValidationError (HTTP 400 at the admin API), never a raw
        pydantic dump."""
        from app.core.errors import ValidationError

        for field in self.secret_slots():
            if config.get(field):
                raise ValidationError(
                    f"Secret {field!r} never lives in config — "
                    "send it via the source's secrets payload"
                )
        from pydantic import ValidationError as PydanticValidationError

        try:
            return self.config_model().model_validate(config).model_dump(mode="json")
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc


def _field_type(annotation: object) -> str:
    """Rough JSON-schema type for the default manifest's configSchema."""
    import types
    import typing

    origin = typing.get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _field_type(args[0]) if args else "string"
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "number"
    if annotation is float:
        return "number"
    if isinstance(annotation, type) and issubclass(annotation, str):
        return "string"
    if origin in (list, dict):
        return "array" if origin is list else "string"
    return "string"


class EmptyConfig(BaseModel):
    """For connectors that need no per-source settings."""
