"""The host-side capability implementations (plan 32 Phase 5 /
capability-rpc.md §4).

Every ``cap.*`` call a sandbox makes lands here, where it is validated at
the seam, quota-checked, executed host-side and audited (one audit row
per capability call — the caller injects the audit funnel callback):

* ``cap.net.fetch`` — the ONLY network path (D14): the vendored polite
  runtime, scoped to the manifest's DECLARED DOMAINS on every hop
  (polite_http re-validates each redirect target); this host serves GET
  only in v1 (a legal charter tightening — hosts may tighten, never
  loosen); declared secret slots resolve host-side into header values or
  the URL via the ``{{secret:<slot>}}`` placeholder the extension
  received from ``cap.secrets.need`` — the value itself is structurally
  unable to cross the seam (it never appears in a message payload);
* ``cap.state.get`` / ``cap.state.set`` — extension-owned state on the
  install row (``extension_state``), quota'd by the charter's
  ``limits.stateMaxBytes`` per instance, key-pattern-checked;
* ``cap.items.emit`` — each item validated against the manifest's
  ``itemSchema`` before buffering; invalid batches are rejected typed and
  count against the run's error budget;
* ``cap.secrets.need`` — resolution STATUS for a declared slot, never a
  value: the result is the placeholder to embed in the next
  ``net.fetch``, or the typed ``needs-secret`` error;
* ``evt.progress`` / ``evt.log`` — observations only, rate-capped per
  run, never instructions.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.extensions import contract, polite_http
from app.extensions.runtime.http import build_transport
from app.extensions.runtime.sandbox.protocol import error_envelope
from app.extensions.sdk import AuditFn, ExternalEffect
from app.models.extension_model import ExtensionInstall

STATE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
SECRET_REF_PATTERN = re.compile(r"\{\{secret:([a-z][a-z0-9-]{0,63})\}\}")
# Charter limits.stateMaxBytes — the per-instance state quota.
STATE_MAX_BYTES = 262_144
ITEMS_PER_CALL_MAX = 256
ITEM_JSON_MAX_BYTES = 32 * 1024
ITEMS_PER_RUN_MAX = 300
URL_MAX_CHARS = 2048
HEADERS_MAX = 16
HEADER_VALUE_MAX_CHARS = 1024
SECRET_PLACEHOLDER = "{{secret:%s}}"
LOG_LEVELS = frozenset({"debug", "info", "warn", "error"})
PROGRESS_KEY_MAX_CHARS = 120
_ERRORS_PER_RUN_MAX = 100


def _detail(data: Any) -> str:
    """Capped JSON detail — data, never a raw exception string."""
    try:
        return json.dumps(data, separators=(",", ":"), default=str)[:500]
    except (TypeError, ValueError):
        return "{}"


class QuotaExhausted(Exception):
    """Typed ``budget`` (retryable after-config-change) — never a silent
    drop."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail[:500]


class SeamError(Exception):
    """One typed seam refusal — mapped to the charter error envelope."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        retryable: str | None = None,
        retry_after_ms: int | None = None,
    ):
        super().__init__(detail)
        self.code = code
        self.envelope = error_envelope(
            code, detail, retryable=retryable, retry_after_ms=retry_after_ms
        )


class _DayBucket:
    """Process-lifetime bytes/day accounting per extension (the charter's
    ``bytes/day`` quota; resets on host restart — a disclosed residual:
    the per-run and per-minute quotas are the hard walls)."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[str, int]] = {}

    def charge(self, extension_id: str, nbytes: int, cap: int) -> None:
        day = datetime.now(UTC).date().isoformat()
        bucket_day, used = self._buckets.get(extension_id, (day, 0))
        if bucket_day != day:
            bucket_day, used = day, 0
        used += nbytes
        if used > cap:
            raise QuotaExhausted(f"daily byte quota exhausted ({cap} bytes/day)")
        self._buckets[extension_id] = (day, used)


class CapabilityProvider:
    """One sandbox run's capability seam. Per-run state lives here; the
    call-rate rings and day buckets are shared per extension."""

    _rate_rings: ClassVar[dict[str, deque[float]]] = {}
    _day_buckets: ClassVar[dict[str, _DayBucket]] = {}

    def __init__(
        self,
        *,
        db: AsyncSession,
        install: ExtensionInstall,
        secrets: dict[str, str] | None = None,
        audit: AuditFn | None = None,
        limits: dict[str, int] | None = None,
    ) -> None:
        from app.core.config import settings

        self._db = db
        self._install = install
        self._secrets = secrets or {}
        self._audit = audit
        limits = limits or {}
        manifest = install.manifest or {}
        self._item_schema = manifest.get("itemSchema") or {}
        self._declared_slots = self._secret_slot_ids(manifest)
        self._domains = frozenset(manifest.get("domains") or [])
        caps = manifest.get("capabilities") or []
        self._net_declared = "net" in caps
        self._state_declared = "state" in caps
        self._calls_per_minute = limits.get(
            "calls_per_minute", settings.extension_sandbox_calls_per_minute
        )
        self._max_calls_per_run = limits.get(
            "max_calls_per_run", settings.extension_sandbox_max_calls_per_run
        )
        self._bytes_per_day = limits.get("bytes_per_day", settings.extension_sandbox_bytes_per_day)
        self._events_per_run = limits.get(
            "events_per_run", settings.extension_sandbox_events_per_run
        )
        self.calls_served = 0
        self._events_used = 0
        self.errors: list[dict[str, Any]] = []
        self.progress_events: list[dict[str, Any]] = []
        self.log_events: list[dict[str, Any]] = []
        self.events_dropped = 0
        self.items: list[dict[str, Any]] = []
        self.net_calls = 0
        self.bytes_used = 0

    # -- the seam ---------------------------------------------------------

    async def handle(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one capability call: quota gate → validation →
        execution → audit row. Raises the typed seam errors; the host
        loop turns them into the wire's error envelopes (the audit row is
        written in ``finally`` either way — one row per call, riding the
        caller's transaction)."""
        started = time.monotonic()
        code: str | None = None
        try:
            self._quota_gate(method)
            return await self._dispatch(method, params)
        except QuotaExhausted:
            code = "budget"
            raise
        except SeamError as exc:
            code = exc.code
            raise
        finally:
            self.calls_served += 1
            if self._audit is not None:
                await self._audit(
                    ExternalEffect(
                        kind="sandbox_capability_call",
                        ref=f"{self._install.extension_id}:{method}",
                        arguments={
                            "argsHash": hashlib.sha256(
                                json.dumps(params, sort_keys=True, default=str).encode()
                            ).hexdigest(),
                            "callNumber": self.calls_served,
                        },
                        meta={"digest": self._install.digest, "tier": self._install.tier},
                        ok=code is None,
                        error=code or "",
                        latency_ms=(time.monotonic() - started) * 1000,
                    )
                )

    async def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "cap.net.fetch":
            return await self._net_fetch(params)
        if method == "cap.state.get":
            return self._state_get(params)
        if method == "cap.state.set":
            return self._state_set(params)
        if method == "cap.items.emit":
            return self._items_emit(params)
        if method == "cap.secrets.need":
            return self._secrets_need(params)
        if method == "evt.progress":
            return self._progress(params)
        if method == "evt.log":
            return self._log(params)
        raise SeamError("unsupported", _detail({"method": method}))

    # -- quotas -------------------------------------------------------------

    def _quota_gate(self, method: str) -> None:
        if self.calls_served >= self._max_calls_per_run:
            raise QuotaExhausted(
                f"per-run call quota exhausted ({self._max_calls_per_run} calls/run)"
            )
        ring = self._rate_rings.setdefault(self._install.extension_id, deque())
        now = time.monotonic()
        while ring and now - ring[0] > 60.0:
            ring.popleft()
        if len(ring) >= self._calls_per_minute:
            raise QuotaExhausted(
                f"call rate quota exhausted ({self._calls_per_minute} calls/minute)"
            )
        ring.append(now)
        if method == "cap.net.fetch":
            self.net_calls += 1

    def _charge_bytes(self, nbytes: int) -> None:
        self.bytes_used += nbytes
        bucket = self._day_buckets.setdefault(self._install.extension_id, _DayBucket())
        bucket.charge(self._install.extension_id, nbytes, self._bytes_per_day)

    # -- cap.net.fetch --------------------------------------------------------

    async def _net_fetch(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._net_declared:
            raise SeamError("unsupported", _detail({"reason": "net not declared in the manifest"}))
        url = params.get("url")
        if not isinstance(url, str) or not url or len(url) > URL_MAX_CHARS:
            raise SeamError("invalid", _detail({"field": "url"}))
        method = params.get("method", "GET")
        if method != "GET":
            raise SeamError(
                "unsupported", _detail({"reason": "this host serves GET net.fetch only in v1"})
            )
        if params.get("body") is not None:
            raise SeamError(
                "unsupported", _detail({"reason": "net.fetch bodies are not served on this host"})
            )
        headers = self._validated_headers(params.get("headers") or {})
        url = self._inject_secrets(url)
        headers = {name: self._inject_secrets(value) for name, value in headers.items()}
        max_bytes = params.get("maxBytes")
        if max_bytes is not None and (
            isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1
        ):
            raise SeamError("invalid", _detail({"field": "maxBytes"}))
        from app.core.config import settings

        cap = (
            int(max_bytes)
            if max_bytes is not None
            else settings.connector_max_response_mb * 1024 * 1024
        )
        transport = build_transport(
            domains=self._domains,
            requests_per_minute=settings.connector_requests_per_minute,
            max_response_bytes=cap,
        )
        try:
            response = await transport(url, headers)
        except polite_http.PoliteHttpError as exc:
            # net-denied (guard / robots / domain scope — every hop) and
            # friends cross as the SAME typed codes (identity mapping).
            raise SeamError(
                exc.code,
                _detail({"net": exc.detail}),
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            ) from exc
        self._charge_bytes(len(response.body.encode("utf-8")) + len(url))
        return {
            "status": response.status,
            "headers": dict(list(response.headers.items())[:32]),
            "body": response.body,
            "finalUrl": response.url or url,
        }

    def _validated_headers(self, raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict) or len(raw) > HEADERS_MAX:
            raise SeamError("invalid", _detail({"field": "headers"}))
        validated: dict[str, str] = {}
        for name, value in raw.items():
            if not isinstance(name, str) or not name or len(name) > 128:
                raise SeamError("invalid", _detail({"field": "headers"}))
            if not isinstance(value, str) or len(value) > HEADER_VALUE_MAX_CHARS:
                raise SeamError("invalid", _detail({"field": "headers"}))
            validated[name] = value
        return validated

    # -- cap.state ------------------------------------------------------------

    def _state(self) -> dict[str, Any]:
        state = self._install.extension_state
        return state if isinstance(state, dict) else {}

    def _state_key(self, params: dict[str, Any]) -> str:
        key = params.get("key")
        if not isinstance(key, str) or not STATE_KEY_PATTERN.fullmatch(key):
            raise SeamError("invalid", _detail({"field": "key"}))
        return key

    def _state_get(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._state_declared:
            raise SeamError(
                "unsupported", _detail({"reason": "state not declared in the manifest"})
            )
        return {"value": self._state().get(self._state_key(params))}

    def _state_set(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._state_declared:
            raise SeamError(
                "unsupported", _detail({"reason": "state not declared in the manifest"})
            )
        key = self._state_key(params)
        if "value" not in params:
            raise SeamError("invalid", _detail({"field": "value"}))
        before = len(json.dumps(self._state(), default=str).encode("utf-8"))
        state = dict(self._state())
        state[key] = params["value"]
        serialized = len(json.dumps(state, default=str).encode("utf-8"))
        if serialized > STATE_MAX_BYTES:
            raise SeamError(
                "budget", _detail({"reason": "state exceeds stateMaxBytes", "bytes": serialized})
            )
        self._install.extension_state = state
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(self._install, "extension_state")
        self._charge_bytes(max(0, serialized - before))
        return {"bytes": serialized}

    # -- cap.items.emit ---------------------------------------------------------

    def _items_emit(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_items = params.get("items")
        if not isinstance(raw_items, list) or len(raw_items) > ITEMS_PER_CALL_MAX:
            raise SeamError("invalid", _detail({"field": "items"}))
        if len(self.items) + len(raw_items) > ITEMS_PER_RUN_MAX:
            raise SeamError(
                "budget", _detail({"reason": "item cap per run", "cap": ITEMS_PER_RUN_MAX})
            )
        accepted: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                self._reject_batch("items must be objects")
            size = len(json.dumps(item, default=str).encode("utf-8"))
            if size > ITEM_JSON_MAX_BYTES:
                self._reject_batch("item exceeds the 32 KiB JSON cap")
            if self._item_schema:
                err = contract.validate(self._item_schema, item, self._item_schema)
                if err is not None:
                    self._reject_batch(f"item fails the manifest itemSchema: {err}")
            accepted.append(item)
        self.items.extend(accepted)
        self._charge_bytes(
            sum(len(json.dumps(item, default=str).encode("utf-8")) for item in accepted)
        )
        return {"accepted": len(accepted)}

    def _reject_batch(self, reason: str) -> None:
        """Invalid batches are rejected WHOLE (atomic), typed, and count
        against the run's error budget (charter items law)."""
        detail = _detail({"items": reason})
        if len(self.errors) < _ERRORS_PER_RUN_MAX:
            self.errors.append({"code": "invalid", "detail": detail, "retryable": "no"})
        raise SeamError("invalid", detail)

    # -- cap.secrets.need ---------------------------------------------------------

    def _secrets_need(self, params: dict[str, Any]) -> dict[str, Any]:
        slot = params.get("slot")
        if not isinstance(slot, str) or not slot or len(slot) > 128:
            raise SeamError("invalid", _detail({"field": "slot"}))
        if slot not in self._declared_slots:
            raise SeamError("invalid", _detail({"reason": "slot not declared in the manifest"}))
        if not self._secrets.get(slot):
            raise SeamError(
                "needs-secret", _detail({"slot": slot}), retryable="after-config-change"
            )
        # STATUS only — the value never crosses (D14); the extension embeds
        # the placeholder and the host substitutes host-side.
        return {"resolved": True, "injectedAs": SECRET_PLACEHOLDER % slot}

    def _inject_secrets(self, text: str) -> str:
        """Host-side substitution of ``{{secret:<slot>}}`` placeholders —
        the ONLY path a secret value may travel (host → upstream, inside
        the request; never host → sandbox). Undeclared slots are invalid;
        declared-but-unresolved slots fail needs-secret."""
        for slot in SECRET_REF_PATTERN.findall(text):
            if slot not in self._declared_slots:
                raise SeamError("invalid", _detail({"reason": "slot not declared"}))
            if not self._secrets.get(slot):
                raise SeamError(
                    "needs-secret", _detail({"slot": slot}), retryable="after-config-change"
                )

        def sub(match: re.Match[str]) -> str:
            return str(self._secrets.get(match.group(1)) or "")

        return SECRET_REF_PATTERN.sub(sub, text)

    # -- events ---------------------------------------------------------------------

    def _progress(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._event_budget():
            return {}
        event: dict[str, Any] = {}
        percent = params.get("percent")
        if percent is not None:
            if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
                raise SeamError("invalid", _detail({"field": "percent"}))
            event["percent"] = percent
        message_key = params.get("messageKey")
        if message_key is not None:
            if not isinstance(message_key, str) or len(message_key) > PROGRESS_KEY_MAX_CHARS:
                raise SeamError("invalid", _detail({"field": "messageKey"}))
            event["messageKey"] = message_key
        if len(self.progress_events) < 32:
            self.progress_events.append(event)
        return {}

    def _log(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._event_budget():
            return {}
        level = params.get("level")
        message = params.get("message")
        if level not in LOG_LEVELS or not isinstance(message, str):
            raise SeamError("invalid", _detail({"field": "level"}))
        if len(self.log_events) < 50:
            self.log_events.append({"level": level, "message": message[:500]})
        return {}

    def _event_budget(self) -> bool:
        if self._events_used >= self._events_per_run:
            self.events_dropped += 1
            return False
        self._events_used += 1
        return True

    # -- helpers ------------------------------------------------------------------------

    @staticmethod
    def _secret_slot_ids(manifest: dict[str, Any]) -> frozenset[str]:
        slots = set(contract.secret_fields(manifest.get("configSchema")))
        for entry in manifest.get("secrets") or []:
            if isinstance(entry, dict) and entry.get("id"):
                slots.add(str(entry["id"]))
        return frozenset(slots)

    @classmethod
    def reset_shared_state(cls) -> None:
        """Test hook: drop the process-lifetime rate rings and day
        buckets."""
        cls._rate_rings.clear()
        cls._day_buckets.clear()
