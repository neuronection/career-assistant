"""The T2 sandbox host — one subprocess per imported extension (plan 32
Phase 5 / ADR-0030 clause 1 / capability-rpc.md).

The host IS the perimeter: it spawns the child with a scrubbed minimal
environment (the child binary is launched ``-I`` so PYTHON* variables are
structurally ignored), cwd inside the extension's sandbox workdir, and
on POSIX an ``RLIMIT_AS`` memory cap installed pre-exec. Obligations
enforced here:

* **wall-clock watchdog per call** (configurable, hard default 30 s) —
  an expiry SIGKILLs the child; a watchdog kill = crash = the extension
  self-disables with a surfaced reason (the connector maps
  :class:`SandboxDied` onto the lifecycle vocabulary);
* **memory cap** — POSIX: ``resource.setrlimit(RLIMIT_AS)`` in the
  child's pre-exec, enforced by the kernel. Windows: NOT enforced in v1
  (no pre-exec hook exists there) — the documented degraded posture is
  the wall-clock watchdog plus the call/byte quotas; the residual is
  disclosed, not mitigated (ADR-0030: containment is not trust);
* **concurrent-sandbox cap** per the host profile — over the cap fails
  typed ``budget``, never queues silently;
* **one audit row per capability call** via the injected audit funnel;
* **protocol discipline** — every line validates against the vendored
  capability-rpc schema; garbage lines accumulate violations and the
  child is recycled at three; a protocol-VERSION mismatch is not a
  violation — it terminates the sandbox and self-disables the extension
  with ``unsupported`` (capability-rpc.md §2);
* **run records** — one ``extension_sandbox_runs`` row per spawn, closed
  with outcome + capped reason; boot reconciliation
  (:func:`interrupt_orphans`) closes host-restart orphans as
  ``interrupted`` (host death is never extension failure).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.extensions.polite_http import ERROR_CODES
from app.extensions.runtime.sandbox.protocol import (
    CAP_METHODS,
    EVENT_METHODS,
    FRAMING_MAX_LINE_BYTES,
    PROTOCOL,
    VERSION,
    FramingError,
    encode_line,
    error_envelope,
    validate_document,
)
from app.extensions.sdk import AuditFn
from app.models.extension_model import ExtensionInstall, ExtensionSandboxRun

MAX_PROTOCOL_VIOLATIONS = 3

_LIVE_SANDBOXES = 0


class SandboxDied(Exception):
    """Sandbox death — crash, watchdog kill or recycle. The extension
    self-disables with the surfaced reason (never a silent retry)."""

    def __init__(self, outcome: str, reason: str):
        super().__init__(reason)
        self.outcome = outcome
        self.reason = reason[:1000]


class SandboxIdentityError(Exception):
    """Handshake identity/protocol-version mismatch — typed
    ``unsupported`` at the lifecycle layer (capability-rpc.md §2)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason[:1000]


class SandboxBusy(Exception):
    """Concurrent-sandbox cap reached — typed ``budget`` for this run."""


class SandboxInvokeError(Exception):
    """The extension itself failed its fetch invoke with a typed error —
    the run ends cleanly; the charter code crosses to the result envelope
    verbatim (identity mapping)."""

    def __init__(self, *, code: str, detail: str, retryable: str, retry_after_ms: int | None):
        super().__init__(f"{code}: {detail}")
        self.code = code if code in ERROR_CODES else "provider"
        self.detail = detail
        self.retryable = (
            retryable if retryable in ("yes", "no", "after-delay", "after-config-change") else "no"
        )
        self.retry_after_ms = retry_after_ms

    def envelope(self) -> dict[str, Any]:
        return error_envelope(
            self.code,
            self.detail,
            retryable=self.retryable,
            retry_after_ms=self.retry_after_ms,
        )


@dataclass
class SandboxLimits:
    call_timeout_s: float
    spawn_timeout_s: float
    dispose_timeout_s: float
    memory_mb: int
    max_concurrent: int

    @classmethod
    def from_settings(cls) -> SandboxLimits:
        from app.core.config import settings

        return cls(
            call_timeout_s=settings.extension_sandbox_call_timeout_seconds,
            spawn_timeout_s=settings.extension_sandbox_spawn_timeout_seconds,
            dispose_timeout_s=settings.extension_sandbox_dispose_timeout_seconds,
            memory_mb=settings.extension_sandbox_memory_mb,
            max_concurrent=settings.extension_sandbox_max_concurrent,
        )


@dataclass
class SandboxRunResult:
    """Everything one sandboxed fetch produced — all of it host-validated."""

    output: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    partial_errors: list[dict[str, Any]] = field(default_factory=list)
    progress_events: list[dict[str, Any]] = field(default_factory=list)
    log_events: list[dict[str, Any]] = field(default_factory=list)
    events_dropped: int = 0
    calls_served: int = 0
    net_calls: int = 0
    bytes_used: int = 0
    run_id: Any = None
    outcome: str = "completed"
    reason: str = ""

    @property
    def next_state(self) -> dict[str, Any]:
        state = self.output.get("next_state")
        return state if isinstance(state, dict) else {}


def child_entry() -> Path:
    """The self-contained child bootstrap (stdlib-only, no package
    imports) — spawned directly, ``-I`` isolated. Frozen builds read the
    spec-declared datas copy (see :mod:`.runtime` for the layout)."""
    from app.extensions.runtime.sandbox import runtime as sandbox_runtime

    return sandbox_runtime.child_asset()


def _child_env(workdir: Path) -> dict[str, str]:
    """Scrubbed minimal environment (capability-rpc.md §2): no host env,
    no CAREER_*, no PYTHON* (the ``-I`` flag ignores them structurally
    anyway), HOME pinned to the sandbox workdir."""
    return {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": str(workdir)}


def _preexec(memory_mb: int) -> Any:
    """POSIX pre-exec: the kernel-enforced address-space cap (the memory
    watchdog). Windows has no pre-exec hook — the degraded posture is
    documented in the module docstring and the Connector SDK docs
    (docs/dev/sdk/security-and-gotchas.md)."""
    if sys.platform == "win32":  # pragma: no cover — platform guard
        return None

    def apply() -> None:  # pragma: no cover — runs in the forked child
        import resource

        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    return apply


async def run_fetch(
    db: AsyncSession,
    *,
    install: ExtensionInstall,
    config: dict[str, Any],
    state: dict[str, Any],
    secrets: dict[str, str] | None = None,
    audit: AuditFn | None = None,
    limits: SandboxLimits | None = None,
) -> SandboxRunResult:
    """One sandboxed fetch run: spawn → handshake (hello) →
    ``ext.invoke fetch`` under the watchdog → dispose. Sandbox death,
    identity mismatches and the concurrency cap raise; the caller maps
    them onto the lifecycle."""
    from app.core.config import settings

    if not settings.extension_sandbox_enabled:
        raise SandboxIdentityError("the T2 sandbox tier is disabled on this host")
    caps = install.manifest.get("capabilities") or []
    if "net" in caps and not install.manifest.get("domains"):
        raise SandboxIdentityError("net declared without its domain scope — refuse to spawn")
    lim = limits or SandboxLimits.from_settings()
    global _LIVE_SANDBOXES
    if lim.max_concurrent <= _LIVE_SANDBOXES:
        raise SandboxBusy(
            f"concurrent sandbox cap reached ({lim.max_concurrent}) — budget, never a queue"
        )
    _LIVE_SANDBOXES += 1
    try:
        return await _run_fetch_locked(
            db,
            install=install,
            config=config,
            state=state,
            secrets=secrets,
            audit=audit,
            limits=lim,
        )
    finally:
        _LIVE_SANDBOXES -= 1


async def _run_fetch_locked(
    db: AsyncSession,
    *,
    install: ExtensionInstall,
    config: dict[str, Any],
    state: dict[str, Any],
    secrets: dict[str, str] | None,
    audit: AuditFn | None,
    limits: SandboxLimits,
) -> SandboxRunResult:
    from app.extensions.runtime.sandbox.capabilities import CapabilityProvider

    workdir = _workdir(install.extension_id)
    from app.extensions.runtime.sandbox import runtime as sandbox_runtime
    from app.extensions.runtime.sandbox.isolation import available, wrap_child_command

    interpreter = sandbox_runtime.check_sandbox_runtime()[0]
    if not available():
        raise sandbox_runtime.SandboxRuntimeUnavailable(
            "kernel isolation (bubblewrap) is unavailable on this platform — "
            "T2 self-disables; install bubblewrap or use a supported Linux host"
        )
    child_args = [
        "--protocol",
        PROTOCOL,
        "--content-dir",
        install.content_path,
        "--entry",
        "extension.py",
        "--digest",
        install.digest,
    ]
    argv = wrap_child_command(
        interpreter=interpreter,
        child_path=child_entry(),
        content_dir=Path(install.content_path),
        child_args=child_args,
    )
    spawn_kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.DEVNULL,
        "env": {},
        "cwd": str(workdir),
        "limit": FRAMING_MAX_LINE_BYTES,
        "start_new_session": True,
    }
    preexec = _preexec(limits.memory_mb)
    if preexec is not None and sys.platform != "win32":
        spawn_kwargs["preexec_fn"] = preexec
    try:
        proc = await asyncio.create_subprocess_exec(*argv, **spawn_kwargs)
    except OSError as exc:
        raise SandboxDied("crashed", f"sandbox spawn failed: {exc.__class__.__name__}") from exc

    run_row = ExtensionSandboxRun(
        install_id=install.id,
        extension_id=install.extension_id,
        digest=install.digest,
        pid=proc.pid,
    )
    db.add(run_row)
    await db.flush()

    provider = CapabilityProvider(db=db, install=install, secrets=secrets, audit=audit)
    session = _SandboxSession(
        proc,
        provider,
        limits,
        run_row=run_row,
        expected_identity={
            "id": install.extension_id,
            "version": str(install.version or ""),
            "digest": install.digest,
        },
    )
    try:
        return await session.run(config, state)
    finally:
        await session.terminate()


def _workdir(extension_id: str) -> Path:
    from app.core.config import settings

    workdir = Path(settings.data_dir) / "sandbox" / extension_id
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


class _SandboxSession:
    """One live child: the reader loop, pending-call futures, the
    violation counter and the teardown."""

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        provider: Any,
        limits: SandboxLimits,
        *,
        run_row: ExtensionSandboxRun,
        expected_identity: dict[str, str],
    ) -> None:
        self.proc = proc
        self.provider = provider
        self.limits = limits
        self.run_row = run_row
        self.expected_identity = expected_identity
        self.violations = 0
        self.pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0
        self._eof_marked = False
        self.disposed = False
        self.death: SandboxDied | None = None
        self.identity_error: SandboxIdentityError | None = None
        self.invoke_error: SandboxInvokeError | None = None

    # -- wire helpers -------------------------------------------------------

    def _send(self, message: dict[str, Any]) -> None:
        writer = self.proc.stdin
        if writer is None:  # pragma: no cover — stdin is always PIPE
            raise SandboxDied("crashed", "sandbox stdin closed")
        try:
            writer.write(encode_line(message))
        except (ConnectionError, BrokenPipeError, OSError) as exc:
            raise SandboxDied("crashed", "sandbox pipe closed") from exc

    async def _send_error(self, mid: str, method: str, envelope: dict[str, Any]) -> None:
        self._send({"v": VERSION, "type": "error", "id": mid, "method": method, "error": envelope})

    # -- the run ------------------------------------------------------------

    async def run(self, config: dict[str, Any], state: dict[str, Any]) -> SandboxRunResult:
        reader = asyncio.create_task(self._reader())
        self.reader_task = reader
        try:
            identity = await self._invoke(
                "hello", {}, timeout=self.limits.spawn_timeout_s, phase="handshake"
            )
            if identity != self.expected_identity:
                self.identity_error = SandboxIdentityError(
                    "handshake identity mismatch — the sandbox did not come up as the "
                    f"pinned extension (declared {identity!r})"
                )
                raise self.identity_error
            output = await self._invoke(
                "fetch",
                {"config": config, "state": state},
                timeout=self.limits.call_timeout_s,
                phase="fetch",
            )
            if self.death is not None:
                raise self.death
            await self._dispose()
            return SandboxRunResult(
                output=output,
                items=list(self.provider.items),
                partial_errors=list(self.provider.errors),
                progress_events=list(self.provider.progress_events),
                log_events=list(self.provider.log_events),
                events_dropped=self.provider.events_dropped,
                calls_served=self.provider.calls_served,
                net_calls=self.provider.net_calls,
                bytes_used=self.provider.bytes_used,
                run_id=self.run_row.id,
                outcome="completed",
            )
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
            await self._close_run_row()

    async def _invoke(
        self, op: str, payload: dict[str, Any], *, timeout: float, phase: str
    ) -> dict[str, Any]:
        self._next_id += 1
        mid = f"host-{self._next_id}"
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending[mid] = future
        self._send(
            {
                "v": VERSION,
                "type": "call",
                "id": mid,
                "method": "ext.invoke",
                "params": {"op": op, "input": payload},
            }
        )
        try:
            reply = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self.death = SandboxDied(
                "watchdog",
                f"wall-clock watchdog killed the sandbox during {phase} ({timeout:g}s)",
            )
            self._kill()
            raise self.death from None
        if "error" in reply:
            error = reply["error"]
            if phase == "handshake":
                raise SandboxIdentityError(
                    f"handshake refused: {error.get('code')}: {error.get('detail')}"
                )
            self.invoke_error = SandboxInvokeError(
                code=str(error.get("code") or "provider"),
                detail=str(error.get("detail") or ""),
                retryable=str(error.get("retryable") or "no"),
                retry_after_ms=(
                    error.get("retryAfterMs")
                    if isinstance(error.get("retryAfterMs"), int)
                    else None
                ),
            )
            raise self.invoke_error
        result = reply.get("result") or {}
        output = result.get("output")
        return output if isinstance(output, dict) else {}

    async def _dispose(self) -> None:
        """Graceful dispose (protocol §5): flush + exit 0, SIGKILL after
        the dispose deadline."""
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending["dispose"] = future
        try:
            self._send(
                {
                    "v": VERSION,
                    "type": "call",
                    "id": "dispose",
                    "method": "ext.dispose",
                    "params": {},
                }
            )
        except SandboxDied:
            return
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=self.limits.dispose_timeout_s)
            await asyncio.wait_for(self.proc.wait(), timeout=self.limits.dispose_timeout_s)
            self.disposed = True
        except (TimeoutError, asyncio.CancelledError):
            self._kill()

    async def terminate(self) -> None:
        if self.proc.returncode is None:
            self._kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.proc.wait(), timeout=2.0)

    def _kill(self) -> None:
        with contextlib.suppress(ProcessLookupError, OSError):
            if self.proc.returncode is None:
                self.proc.kill()

    async def _close_run_row(self) -> None:
        if self.run_row.ended_at is not None:
            return
        self.run_row.ended_at = datetime.now(UTC)
        if self.identity_error is not None:
            self.run_row.outcome = "crashed"
            self.run_row.reason = self.identity_error.reason
        elif self.disposed:
            # The graceful path won — an EOF race during teardown is the
            # normal exit, never a crash.
            self.run_row.outcome = "completed"
            self.run_row.reason = (
                f"invoke error: {self.invoke_error.code}" if self.invoke_error else ""
            )
        elif self.death is not None:
            self.run_row.outcome = self.death.outcome
            self.run_row.reason = self.death.reason
        elif self.proc.returncode not in (0, None):
            self.run_row.outcome = "crashed"
            self.run_row.reason = f"sandbox exited {self.proc.returncode}"
        else:
            self.run_row.outcome = "completed"
            self.run_row.reason = (
                f"invoke error: {self.invoke_error.code}" if self.invoke_error else ""
            )

    # -- the reader -----------------------------------------------------------

    async def _reader(self) -> None:
        assert self.proc.stdout is not None
        while True:
            try:
                line = await self.proc.stdout.readline()
            except ValueError:
                await self._violation("line exceeds rpcLineMaxBytes")
                continue
            if not line:
                break
            try:
                text = line.decode("utf-8")
                doc = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError):
                await self._violation("line is not valid JSON")
                continue
            if not isinstance(doc, dict):
                await self._violation("message is not a JSON object")
                continue
            if doc.get("v") != VERSION:
                # A version mismatch is NOT a violation: terminate the
                # sandbox, self-disable with unsupported (§2).
                self.identity_error = SandboxIdentityError(
                    f"protocol version mismatch: {doc.get('v')!r} (host speaks "
                    f"capability-rpc/{VERSION})"
                )
                self._kill()
                break
            try:
                validate_document(doc)
            except FramingError as exc:
                await self._violation(exc.detail)
                continue
            mtype = doc.get("type")
            mid = doc.get("id")
            if mtype == "call":
                await self._serve(doc, mid)
            elif mtype == "event":
                await self._event(doc)
            elif isinstance(mid, str) and mid in self.pending:
                future = self.pending.pop(mid)
                if not future.done():
                    future.set_result(doc)
            else:
                await self._violation(f"unsolicited {mtype} with unknown id")
        self._mark_eof()

    def _mark_eof(self) -> None:
        """The child's output closed (or the reader bailed): nothing
        pending will ever be answered — fail the waiters now instead of
        burning the watchdog. After a normal dispose this is the clean
        exit; an identity error is the cause when the version gate
        fired."""
        if self._eof_marked:
            return
        self._eof_marked = True
        cause: BaseException | None = None
        if self.identity_error is not None:
            cause = self.identity_error
        elif self.death is not None:
            cause = self.death
        elif not self.disposed:
            code = self.proc.returncode
            self.death = SandboxDied(
                "crashed",
                "sandbox closed its output "
                + (f"with exit code {code}" if code else "without answering"),
            )
            cause = self.death
        else:
            cause = None
        for mid, future in list(self.pending.items()):
            if not future.done() and cause is not None:
                future.set_exception(cause)
            self.pending.pop(mid, None)

    async def _serve(self, doc: dict[str, Any], mid: Any) -> None:
        from app.extensions.runtime.sandbox.capabilities import QuotaExhausted, SeamError

        method = str(doc.get("method") or "")
        if method not in CAP_METHODS:
            # Unknown methods are refused — never dispatched, never
            # reflected (capability-rpc.md §3).
            await self._send_error(
                mid, method or "unknown", error_envelope("unsupported", "unknown method")
            )
            return
        try:
            result = await asyncio.wait_for(
                self.provider.handle(method, doc.get("params") or {}),
                timeout=self.limits.call_timeout_s,
            )
        except TimeoutError:
            self.death = SandboxDied(
                "watchdog",
                f"wall-clock watchdog killed the sandbox during {method} "
                f"({self.limits.call_timeout_s:g}s)",
            )
            self._kill()
            return
        except asyncio.CancelledError:
            raise
        except QuotaExhausted as exc:
            await self._send_error(mid, method, error_envelope("budget", exc.detail))
            return
        except SeamError as exc:
            await self._send_error(mid, method, exc.envelope)
            return
        self._send({"v": VERSION, "type": "result", "id": mid, "result": result})

    async def _event(self, doc: dict[str, Any]) -> None:
        from app.extensions.runtime.sandbox.capabilities import QuotaExhausted, SeamError

        method = str(doc.get("method") or "")
        if method not in EVENT_METHODS:
            await self._violation(f"event method outside the vocabulary: {method}")
            return
        try:
            await self.provider.handle(method, doc.get("params") or {})
        except (QuotaExhausted, SeamError):
            return

    async def _violation(self, detail: str) -> None:
        self.violations += 1
        if self.violations >= MAX_PROTOCOL_VIOLATIONS:
            self.death = SandboxDied(
                "protocol-violation",
                f"recycled after {self.violations} protocol violations (last: {detail})",
            )
            self._kill()


async def interrupt_orphans(db: AsyncSession) -> int:
    """Boot reconciliation (ADR-0030's AppService boot pattern, ported):
    runs still marked ``running`` when the host boots were orphaned by a
    host restart — closed as ``interrupted``, which is never an extension
    failure. Returns the number of rows closed."""
    from sqlalchemy import select

    orphans = (
        (
            await db.execute(
                select(ExtensionSandboxRun).where(ExtensionSandboxRun.ended_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for row in orphans:
        row.ended_at = now
        row.outcome = "interrupted"
        row.reason = "host restarted while the sandbox was live"
    return len(orphans)


def sandbox_capability_auditor(db: AsyncSession, extension_id: str) -> AuditFn:
    """The audit funnel adapter: one ``ai_generations`` row per sandbox
    capability call (``AITaskType.SANDBOX_CAPABILITY_CALL``, provider
    ``sandbox``) — the same funnel the MCP bridge rides. Rows commit with
    the caller's transaction."""

    async def audit(effect: Any) -> None:
        if getattr(effect, "kind", None) != "sandbox_capability_call":
            return
        from app.ai.gateway import _record
        from app.models.enums import AITaskType

        await _record(
            db,
            None,
            AITaskType.SANDBOX_CAPABILITY_CALL,
            "sandbox",
            f"sandbox:{effect.ref}",
            {
                "arguments": effect.arguments,
                "meta": effect.meta,
                "ok": effect.ok,
                "error": effect.error,
            },
            None,
            None,
            effect.latency_ms,
            "ok" if effect.ok else "error",
            effect.error[:1000],
            model_name=extension_id,
            provider_type="sandbox",
        )

    return audit
