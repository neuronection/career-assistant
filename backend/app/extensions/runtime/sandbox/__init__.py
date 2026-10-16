"""The T2 sandbox runner (plan 32 Phase 5 / ADR-0030 ported to Python).

Layout (the trust boundary reads top-down):

* :mod:`.child` — the self-contained sandboxed child (stdlib-only,
  spawned ``-I``); the frozen module surface + the audit wall;
* :mod:`.protocol` — the host seam: framing + the vendored
  capability-rpc schema gate + the typed error envelopes;
* :mod:`.capabilities` — the host-side capability implementations
  (net/state/items/secrets/events), quota-checked and audited;
* :mod:`.host` — one subprocess per extension: spawn, handshake,
  watchdogs, quotas, run records, boot reconciliation;
* :mod:`.runtime` — the frozen-build capability check (interpreter +
  child assets) that gates the spawn;
* :mod:`.connector` — the :class:`~app.extensions.sdk.PostingConnector`
  adapter that routes a T2 instance's fetch through the sandbox.
"""

from app.extensions.runtime.sandbox.host import (
    SandboxBusy,
    SandboxDied,
    SandboxIdentityError,
    SandboxInvokeError,
    SandboxLimits,
    SandboxRunResult,
    interrupt_orphans,
    run_fetch,
    sandbox_capability_auditor,
)
from app.extensions.runtime.sandbox.runtime import SandboxRuntimeUnavailable

__all__ = [
    "SandboxBusy",
    "SandboxDied",
    "SandboxIdentityError",
    "SandboxInvokeError",
    "SandboxLimits",
    "SandboxRunResult",
    "SandboxRuntimeUnavailable",
    "interrupt_orphans",
    "run_fetch",
    "sandbox_capability_auditor",
]
