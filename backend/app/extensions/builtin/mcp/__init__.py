"""The T3 script tier (plan 32 Phase 2 / ADR-0040 D9): external MCP
servers as posting sources.

One configured source = one external MCP server (a stdio subprocess or
an http endpoint) plus ONE allowlisted tool speaking the family fetch
contract::

    fetch_postings(config, state) -> {"items": [...], "next_state": {...}}

The script process runs OUTSIDE the host's politeness perimeter
(ADR-0040 clause 21 / D22): it opens its own sockets with no SSRF
guard, robots.txt check or rate limiting by the app — which is exactly
why this connector's manifest declares no ``net`` domains and why the
host governs only what comes back: every returned row is validated
against :class:`RawPosting` app-side (required fields, http(s) URLs,
char caps, item cap) before anything persists, malformed rows become
typed ``invalid`` partial errors, and every tool call lands on the
audit funnel through the injected ``audit`` callback (one row per
call, D7/D9). Secrets never cross to the script: the optional token is
a sealed slot resolved host-side for the http transport's Bearer
header, and the config handed to the tool is stripped of declared
secret fields.

Disabled by default: the connector registers only when allowlisted
(``CAREER_CONNECTOR_PLUGINS_ALLOWLIST`` containing ``mcp``) —
allowlist-off means the connector is invisible in the catalog and
unknown to the registry (structural, tested).
"""

from __future__ import annotations

import json
import time
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.extensions.sdk import (
    ConnectorCapabilities,
    ConnectorError,
    ConnectorResult,
    ExternalEffect,
    PostingConnector,
    RawPosting,
    connector_manifest,
)

MAX_ITEMS = 300
RAW_JSON_CAP = 8_192


def _allowlist(raw: str) -> list[str]:
    """Comma-separated tool allowlist → clean list."""
    return [tool.strip() for tool in (raw or "").split(",") if tool.strip()]


class McpConfig(BaseModel):
    """One MCP source: transport + the single tool it may call.

    ``allowed_tools`` is the per-tool allowlist (comma-separated; empty
    means just the configured ``tool``). ``token`` is NOT here — it is
    a sealed secret slot (``x-secret`` in the manifest configSchema).
    """

    transport: Literal["stdio", "http"] = "stdio"
    command: str = Field(default="", max_length=1000)
    url: str = Field(default="", max_length=1000)
    tool: str = Field(default="fetch_postings", min_length=1, max_length=120)
    allowed_tools: str = Field(default="", max_length=1000)
    timeout_seconds: int = Field(default=30, ge=5, le=120)

    @model_validator(mode="after")
    def _transport_fields(self) -> McpConfig:
        if self.transport == "stdio" and not self.command.strip():
            raise ValueError("stdio sources need a command line")
        if self.transport == "http" and not self.url.strip().startswith(("http://", "https://")):
            raise ValueError("http sources need an http(s) url")
        allow = _allowlist(self.allowed_tools)
        if allow and self.tool not in allow:
            raise ValueError(f"tool {self.tool!r} is not in this source's allowlist")
        return self


MCP_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "transport": {
            "type": "string",
            "title": "Transport",
            "enum": ["stdio", "http"],
            "default": "stdio",
        },
        "command": {
            "type": "string",
            "title": "Stdio command line (e.g. python /path/to/server.py)",
            "maxLength": 1000,
        },
        "url": {"type": "string", "title": "HTTP server URL", "maxLength": 1000},
        "tool": {
            "type": "string",
            "title": "Fetch tool",
            "default": "fetch_postings",
            "maxLength": 120,
        },
        "allowed_tools": {
            "type": "string",
            "title": "Tool allowlist (comma-separated; empty = just the fetch tool)",
            "maxLength": 1000,
        },
        "timeout_seconds": {
            "type": "number",
            "title": "Tool timeout (seconds)",
            "minimum": 5,
            "maximum": 120,
            "default": 30,
        },
        "token": {
            "type": "string",
            "title": "Bearer token (optional, http transport)",
            "maxLength": 500,
            "x-secret": True,
        },
    },
}


def _invalid(detail: str) -> ConnectorError:
    return ConnectorError(code="invalid", detail=detail[:500], retryable="no")


def _protocol(detail: str) -> ConnectorError:
    return ConnectorError(code="protocol", detail=detail[:500], retryable="after-config-change")


def _classify(exc: Exception, timeout_seconds: int) -> ConnectorError:
    """fastmcp failures → charter errors (classification itself lives in
    the AI layer; only plain data crosses back)."""
    from app.ai.mcp_client import classify_tool_error

    code, detail, retryable = classify_tool_error(exc, timeout_seconds)
    return ConnectorError(code=code, detail=detail, retryable=retryable)  # type: ignore[arg-type]


class McpConnector(PostingConnector):
    """T3 external-process postings source (MCP). Admin-allowlisted,
    per-source tool allowlist, app-side row validation + caps, one
    audit row per tool call."""

    key = "mcp"
    title = "MCP script (external process)"
    docs_url = "https://docs.career-assistant.local/connectors/mcp"
    capabilities = ConnectorCapabilities(supports_incremental=True, url_fetching=False)
    allowlist_gated = True
    audits_effects = True

    def config_model(self) -> type[BaseModel]:
        return McpConfig

    def manifest(self) -> dict:
        # No `net`/domains by design: the script process's own sockets
        # are outside the host perimeter (D22) — disclosed honestly in
        # the description instead of smuggled in as a capability.
        return connector_manifest(
            manifest_id="career-mcp",
            title="MCP script (external process)",
            description="Runs an external MCP server in its own process — it opens "
            "its own network connections outside the app's SSRF/robots/rate "
            "perimeter — and ingests the postings it returns. The app governs "
            "only what comes back: rows are validated and capped. "
            "Admin-allowlisted; per-source tool allowlist and timeout.",
            config_schema=MCP_CONFIG_SCHEMA,
            capabilities=["sync", "secrets"],
            supports_incremental=True,
        )

    def _client_for(self, cfg: McpConfig, token: str):
        """Delegate client construction to the AI layer (fastmcp imports
        are AI-layer-only; factored for test injection)."""
        from app.ai.mcp_client import client_for_spec

        return client_for_spec(
            transport=cfg.transport,
            url=cfg.url,
            command=cfg.command,
            token=token,
            timeout_seconds=cfg.timeout_seconds,
        )

    async def fetch(
        self,
        config: dict,
        state: dict,
        *,
        transport=None,
        secrets: dict | None = None,
        audit=None,
        **_kw,
    ) -> ConnectorResult:
        cfg = self.config_model().model_validate(config)
        secret_slots = self.secret_slots()
        safe_config = {k: v for k, v in dict(config).items() if k not in secret_slots}
        arguments = {"config": safe_config, "state": dict(state or {})}
        effect = ExternalEffect(
            kind="mcp_tool_call",
            ref=cfg.tool,
            arguments=arguments,
            meta={"transport": cfg.transport, "server": (cfg.command or cfg.url)[:200]},
        )
        started = time.monotonic()
        try:
            client = self._client_for(cfg, str((secrets or {}).get("token") or ""))
            async with client as session:
                result = await session.call_tool(cfg.tool, arguments, timeout=cfg.timeout_seconds)
            texts = [
                block.text
                for block in (result.content or [])
                if getattr(block, "text", None) is not None
            ]
        except Exception as exc:
            error = _classify(exc, cfg.timeout_seconds)
            if audit is not None:
                effect.ok = False
                effect.error = f"{error.code}: {error.detail}"
                effect.latency_ms = (time.monotonic() - started) * 1000
                await audit(effect)
            return ConnectorResult(partial_errors=[error])
        effect.latency_ms = (time.monotonic() - started) * 1000
        if audit is not None:
            await audit(effect)

        rows, next_state, tool_errors, envelope_error = self._parse_envelope(texts)
        if envelope_error is not None:
            return ConnectorResult(partial_errors=[envelope_error])
        items, errors = self._validate_rows(rows)
        errors.extend(tool_errors)
        return ConnectorResult(items=items, next_state=next_state, partial_errors=errors)

    def _parse_envelope(
        self, texts: list[str]
    ) -> tuple[list, dict, list[ConnectorError], ConnectorError | None]:
        """The tool's first text block must be the family envelope JSON:
        ``{"items": [...], "next_state": {...}, "partial_errors": [...]}``."""
        if not texts:
            return [], {}, [], _protocol("tool returned no text content")
        try:
            payload = json.loads(texts[0])
        except json.JSONDecodeError as exc:
            return [], {}, [], _protocol(f"tool output is not JSON: {exc}")
        if not isinstance(payload, dict):
            return [], {}, [], _protocol("tool output is not the {items, next_state} envelope")
        rows = payload.get("items", [])
        if not isinstance(rows, list):
            return [], {}, [], _protocol("envelope items is not a list")
        next_state = payload.get("next_state") or {}
        errors: list[ConnectorError] = []
        if not isinstance(next_state, dict):
            errors.append(_invalid("envelope next_state is not an object — dropped"))
            next_state = {}
        if len(json.dumps(next_state, default=str)) > RAW_JSON_CAP:
            errors.append(_invalid("envelope next_state exceeds the size cap — dropped"))
            next_state = {}
        for entry in payload.get("partial_errors") or []:
            try:
                errors.append(ConnectorError.model_validate(entry))
            except Exception:
                errors.append(_invalid(f"unusable partial error from tool: {entry!r}"))
        return rows, next_state, errors, None

    def _validate_rows(self, rows: list) -> tuple[list[RawPosting], list[ConnectorError]]:
        """Every row is untrusted: schema-check against RawPosting
        (required fields, char caps), require http(s) URLs, cap the item
        count and the raw bag — malformed rows become typed ``invalid``
        errors and never persist (study's McpDiscoveryProvider
        discipline, D9)."""
        items: list[RawPosting] = []
        errors: list[ConnectorError] = []
        if len(rows) > MAX_ITEMS:
            errors.append(
                _invalid(f"{len(rows) - MAX_ITEMS} row(s) beyond the {MAX_ITEMS}-item cap dropped")
            )
        for index, row in enumerate(rows[:MAX_ITEMS]):
            if not isinstance(row, dict):
                errors.append(_invalid(f"row {index}: not an object"))
                continue
            url = str(row.get("url") or "")
            if url and not url.lower().startswith(("http://", "https://")):
                errors.append(
                    _invalid(f"row {index} ({row.get('external_id')!r}): url must be http(s)")
                )
                continue
            try:
                if len(json.dumps(row.get("raw") or {}, default=str)) > RAW_JSON_CAP:
                    errors.append(
                        _invalid(f"row {index} ({row.get('external_id')!r}): raw exceeds size cap")
                    )
                    continue
                items.append(RawPosting.model_validate(row))
            except Exception as exc:
                errors.append(_invalid(f"row {index}: {exc}"))
        return items, errors
