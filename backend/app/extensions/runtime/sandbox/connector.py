"""The T2 sandbox connector (plan 32 Phase 5) — the registry-facing
adapter that routes an imported T2 instance's fetch through the sandbox
runner instead of in-process execution (D2/D14).

One instance per imported extension: constructed from the install row
(manifest, content path, digest), its ``fetch`` is the full sandbox run —
spawn → handshake → ``ext.invoke fetch`` → dispose — with every
capability call host-mediated, quota-checked and audited, items
schema-validated and coerced into :class:`RawPosting`, and sandbox death
mapped onto the lifecycle (self-disable with a surfaced reason — ADR-0030
clause 1). T1 builtins are untouched: this class never runs in-process
extension code.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.extensions import contract
from app.extensions.lifecycle import LifecycleError
from app.extensions.runtime.sandbox import (
    SandboxBusy,
    SandboxDied,
    SandboxIdentityError,
    SandboxInvokeError,
)
from app.extensions.runtime.sandbox import (
    host as sandbox_host,
)
from app.extensions.sdk import (
    ConnectorCapabilities,
    ConnectorError,
    ConnectorResult,
    PostingConnector,
    RawPosting,
)
from app.models.extension_model import ExtensionInstall

ITEMS_MAX = 300


def _error(
    code: str, detail: str, retryable: str, retry_after_ms: int | None = None
) -> ConnectorError:
    """Build a typed charter error from seam strings — pydantic validates
    the code against the closed Literal (fail-closed on drift)."""
    return ConnectorError.model_validate(
        {
            "code": code,
            "detail": detail[:500],
            "retryable": retryable,
            "retry_after_ms": retry_after_ms,
        }
    )


class SandboxConnector(PostingConnector):
    """One imported T2 connector instance (the install row is the
    instance, D19)."""

    audits_effects = True

    def __init__(self, db: AsyncSession, install: ExtensionInstall):
        self._db = db
        self._install = install
        manifest = install.manifest or {}
        self._manifest = manifest
        self.key = install.extension_id
        self.title = str(
            ((manifest.get("i18n") or {}).get("locales") or {}).get("en", {}).get("title")
            or install.extension_id
        )
        self.docs_url = str(manifest.get("repository") or "")
        caps = manifest.get("capabilities") or []
        self.capabilities = ConnectorCapabilities(
            network_scopes=sorted(manifest.get("domains") or []),
            requires_credentials=bool(self.secret_slots()) or "secrets" in caps,
            supports_incremental=bool(manifest.get("supportsIncremental")),
            max_requests_per_minute=1_000_000,  # the seam's own quotas govern
            url_fetching="net" in caps,
        )

    def config_model(self) -> type[BaseModel]:
        """The manifest's configSchema is the config contract — validated
        as data through the vendored validator (see ``validate_config``),
        never a dynamic pydantic model."""
        raise NotImplementedError(
            "T2 config validation is data-driven (the manifest's configSchema)"
        )

    def manifest(self) -> dict:
        return dict(self._manifest)

    def validate_config(self, config: dict) -> dict:
        """Config round-trip against the manifest's configSchema (D19 x-secret
        law included: a value under a declared secret slot throws)."""
        for slot in self.secret_slots():
            if config.get(slot):
                raise ValidationError(
                    f"Secret {slot!r} never lives in config — "
                    "send it via the source's secrets payload"
                )
        schema = self._manifest.get("configSchema")
        if schema:
            err = contract.validate(schema, config, schema)
            if err is not None:
                raise ValidationError(f"config invalid for {self.key}: {err}")
        return config

    async def fetch(
        self,
        config: dict,
        state: dict,
        *,
        transport: Any = None,
        secrets: dict | None = None,
        audit: Any = None,
        **_kw: Any,
    ) -> ConnectorResult:
        """One sandboxed fetch run. Sandbox death self-disables the
        extension (lifecycle vocabulary, surfaced reason) and comes back
        as a typed partial error — the host process and other extensions
        are unaffected."""
        try:
            run = await sandbox_host.run_fetch(
                self._db,
                install=self._install,
                config=config,
                state=state,
                secrets=secrets,
                audit=audit,
            )
        except SandboxIdentityError as exc:
            await self._self_disable(f"unsupported: {exc.reason}")
            return self._result([_error("unsupported", exc.reason[:500], "after-config-change")])
        except SandboxBusy as exc:
            return self._result([_error("budget", str(exc), "after-delay")])
        except SandboxDied as exc:
            if exc.outcome == "protocol-violation":
                # Recyclable misbehavior: typed `protocol`, the child dies,
                # the EXTENSION survives — a fresh child spawns next run
                # (capability-rpc.md §1: the peer may kill the process).
                return self._result([_error("protocol", exc.reason[:500], "after-delay")])
            await self._self_disable(f"{exc.outcome}: {exc.reason}")
            return self._result(
                [_error("provider", f"sandbox {exc.outcome}: {exc.reason}"[:500], "no")]
            )
        except SandboxInvokeError as exc:
            # The extension failed its own invoke with a typed code — the
            # run ends cleanly, the code crosses verbatim (no disable).
            return self._result(
                [_error(exc.code, exc.detail[:500], exc.retryable, exc.retry_after_ms)]
            )
        except LifecycleError as exc:
            return self._result(
                [_error("not-ready", f"{exc.code}: {exc.detail}"[:500], "after-config-change")]
            )
        return self._result(
            [ConnectorError.model_validate(error) for error in run.partial_errors],
            items=run.items,
            next_state=run.next_state,
        )

    def _result(
        self,
        errors: list[ConnectorError],
        *,
        items: list[dict[str, Any]] | None = None,
        next_state: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        """Envelope assembly: emitted items were already validated against
        the manifest itemSchema at the seam — the coercion into
        :class:`RawPosting` is the last (stricter) gate; failures become
        typed ``invalid`` partial errors."""
        postings: list[RawPosting] = []
        for raw in (items or [])[:ITEMS_MAX]:
            try:
                postings.append(RawPosting.model_validate(raw))
            except PydanticValidationError as exc:
                errors.append(
                    ConnectorError(
                        code="invalid",
                        detail=f"item {str(raw.get('external_id'))[:80]}: {exc.error_count()} "
                        "validation error(s)",
                        retryable="no",
                    )
                )
        return ConnectorResult(items=postings, next_state=next_state or {}, partial_errors=errors)

    async def _self_disable(self, reason: str) -> None:
        from app.extensions import lifecycle

        await lifecycle.self_disable(self._db, install=self._install, reason=reason)
