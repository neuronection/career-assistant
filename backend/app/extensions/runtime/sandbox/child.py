"""The T2 sandbox child — one process per imported extension (plan 32
Phase 5 / ADR-0030 clause 2 / capability-rpc.md).

Spawned by the host as ``<python> -I -B <this file> --content-dir ...
--entry extension.py --digest <sha256>`` with a scrubbed minimal
environment (``-I`` structurally ignores PYTHON* env vars and the user
site dir — the spawn form of the env-scrub law, capability-rpc.md §2)
and cwd inside the extension's sandbox workdir. Stdlib only: the child
deliberately imports NOTHING from the host app package, so the host's
config, environment and secrets cannot reach it even by accident.

Frozen module surface (the ADR-0030 law, ported to Python):

* sandboxed code may import ONLY the vendored capability client (the
  ``capability`` module built below — protocol calls + pure helpers);
  a ``sys.addaudithook`` guard denies every other import;
* the audit hook denies socket/subprocess/os-exec family, filesystem
  access (open/stat/listdir/... — no fs capability exists at this
  seam), environment reads, and the eval/exec/compile family;
* ``sys.stdout``/``sys.stderr`` are replaced with sinks before the
  extension loads — extension prints can never corrupt the line-JSON
  protocol framing on the real stdout;
* the extension's namespace gets restricted builtins (no ``open``,
  ``eval``, ``exec``, ``compile``, ``input``, ``breakpoint``) on top.

Containment is not trust (ADR-0030 clause 2): the audit wall limits
blast radius, it does not review intent — the host-side watchdogs,
quotas, digest pinning and one-audit-row-per-call obligations are the
host's half of the boundary (``app.extensions.runtime.sandbox.host``).
"""

from __future__ import annotations

import argparse
import json
import sys
from types import ModuleType
from typing import Any

PROTOCOL = "capability-rpc/1"
VERSION = 1

# Charter limits (extension-charter.json limits — hosts may tighten,
# never loosen; the child mirrors the framing cap exactly).
RPC_LINE_MAX_BYTES = 1_048_576
MANIFEST_MAX_BYTES = 524_288
ERROR_DETAIL_MAX_CHARS = 500
#: The closed error-detail vocabulary (plan 37 7E) — the child keeps its
#: own frozen copy like ERROR_CODES/RETRYABLE (trusted bootstrap, minimal
#: imports); `contract.cap_error_detail` is canonical and the rpc fixtures
#: pin the wire shape identically in every copy.
_ERROR_DETAIL_CAPS = {
    "message": 400, "path": 256, "field": 64, "id": 128, "packId": 128,
    "runId": 128, "slot": 128, "host": 253, "method": 128, "op": 64,
    "stage": 64, "engine": 64, "expected": 128, "actual": 128,
}


def _bounded_detail(detail: Any) -> dict[str, Any]:
    """The bounded error-detail object (7E): declared keys only, `message`
    capped at 400, serialized cap ERROR_DETAIL_MAX_CHARS (truncate
    `message` first, then drop non-`message` keys). A plain string becomes
    `{"message": ...}` at construction — the wire never carries it."""
    if isinstance(detail, str):
        detail = {"message": detail}
    if not isinstance(detail, dict):
        return {}
    out: dict[str, Any] = {}
    for key, cap in _ERROR_DETAIL_CAPS.items():
        value = detail.get(key)
        if isinstance(value, str):
            out[key] = value[:cap]
    for key in ("hop", "limit", "used"):
        value = detail.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            out[key] = value

    def _size() -> int:
        return len(json.dumps(out, separators=(",", ":"), ensure_ascii=False))

    while _size() > ERROR_DETAIL_MAX_CHARS:
        message = out.get("message")
        if message:
            out["message"] = message[: max(0, len(message) - (_size() - ERROR_DETAIL_MAX_CHARS))]
            continue
        droppable = next((k for k in out if k != "message"), None)
        if droppable is None:
            break
        del out[droppable]
    return out
INPUT_MAX_BYTES = 256 * 1024

# The closed method vocabulary (extension-charter.json rpc).
HOST_METHODS = frozenset({"ext.invoke", "ext.dispose"})
ERROR_CODES = frozenset(
    {
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
    }
)
RETRYABLE = frozenset({"yes", "no", "after-delay", "after-config-change"})

# The frozen import surface: the capability client + pure helpers only
# (ADR-0030 clause 2). Everything else is denied at the import audit
# event; modules the interpreter already loaded at startup (os, sys)
# never fire the event, so the capability-denial wall below is the
# enforcement layer for those — layered, deliberately.
MODULE_ALLOWLIST = frozenset(
    {
        "capability",
        "json",
        "re",
        "math",
        "decimal",
        "statistics",
        "datetime",
        "itertools",
        "functools",
        "collections",
        "heapq",
        "bisect",
        "string",
        "textwrap",
        "unicodedata",
        "random",
    }
)

MAX_PROTOCOL_VIOLATIONS = 3
ENTRY_FILE = "extension.py"


class SandboxViolation(RuntimeError):
    """A denied escape attempt, typed with the charter error code."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail[:ERROR_DETAIL_MAX_CHARS]


class CapabilityError(RuntimeError):
    """A typed error envelope returned by the host for a capability call."""

    def __init__(self, code: str, detail: str, retryable: str, retry_after_ms: int | None):
        super().__init__(detail)
        self.code = code
        self.detail = detail[:ERROR_DETAIL_MAX_CHARS]
        self.retryable = retryable
        self.retry_after_ms = retry_after_ms


# ----------------------------------------------------------------- framing


class Framing:
    """Line-delimited JSON over the real stdio (protocol §1).

    Owned by the protocol loop; the redirected ``sys.stdout`` sinks can
    never reach these descriptors."""

    def __init__(self) -> None:
        self.reader = sys.stdin.buffer
        self.writer = sys.stdout.buffer
        self.violations = 0

    def send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.writer.write(line + b"\n")
        self.writer.flush()

    def recv(self) -> dict[str, Any] | None:
        """One framed line, or None at EOF. Oversized/garbage lines count
        as protocol violations and end the child after repeated ones."""
        while True:
            line = self.reader.readline(RPC_LINE_MAX_BYTES + 2)
            if not line:
                return None
            if not line.endswith(b"\n"):
                self.violate("line exceeds rpcLineMaxBytes")
                continue
            try:
                doc = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                self.violate("line is not valid JSON")
                continue
            if not isinstance(doc, dict):
                self.violate("message is not a JSON object")
                continue
            return doc

    def violate(self, reason: str) -> None:
        self.violations += 1
        if self.violations >= MAX_PROTOCOL_VIOLATIONS:
            sys.exit(3)


def validate_message(doc: dict[str, Any]) -> str | None:
    """Structural gate for one inbound line (the vendored
    capability-rpc.schema.json essentials, mirrored stdlib-only; the
    authoritative full-schema gate is the host seam)."""
    if doc.get("v") != VERSION:
        return "unsupported protocol version"
    mtype = doc.get("type")
    if mtype not in ("call", "result", "error", "event"):
        return "unknown message type"
    mid = doc.get("id")
    if isinstance(mid, bool) or not isinstance(mid, (int, str)):
        return "bad correlation id"
    if isinstance(mid, str) and len(mid) > 64:
        return "bad correlation id"
    extra = set(doc) - {"v", "type", "id", "method", "params", "result", "error"}
    if extra:
        return "unexpected message fields"
    if mtype == "call":
        if doc.get("method") not in HOST_METHODS:
            return "call method outside the host vocabulary"
        if not isinstance(doc.get("params"), dict):
            return "calls carry params"
    elif mtype == "result":
        if not isinstance(doc.get("result"), dict):
            return "results carry a result object"
    elif mtype == "error":
        if doc.get("method") not in HOST_METHODS:
            return "error method outside the host vocabulary"
        err = doc.get("error")
        if not isinstance(err, dict):
            return "errors carry an error envelope"
        if err.get("code") not in ERROR_CODES or err.get("retryable") not in RETRYABLE:
            return "error envelope outside the charter enum"
        if not isinstance(err.get("detail"), str):
            return "error detail must be a string"
    return None


# ------------------------------------------------------- the frozen client


class CapabilityClient:
    """The vendored SDK capability client — the ONLY privileged object
    exposed to sandboxed code (protocol §4 calls, §6 events).

    Calls are legal only inside an ``ext.invoke`` (serialized per
    process, charter rpc law); the loop toggles :attr:`active`."""

    def __init__(self, framing: Framing) -> None:
        self._framing = framing
        self._next_id = 1
        self.active = False

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.active:
            raise CapabilityError(
                "protocol",
                "capability calls are legal only inside an invoke",
                "after-config-change",
                None,
            )
        mid = self._next_id
        self._next_id += 1
        self._framing.send(
            {"v": VERSION, "type": "call", "id": mid, "method": method, "params": params}
        )
        while True:
            line = self._framing.reader.readline(RPC_LINE_MAX_BYTES + 2)
            if not line or not line.endswith(b"\n"):
                raise CapabilityError(
                    "protocol", "host connection closed", "after-config-change", None
                )
            try:
                doc = json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                raise CapabilityError("protocol", "unparseable host reply", "yes", None) from exc
            if doc.get("id") != mid:
                raise CapabilityError("protocol", "reply correlation mismatch", "yes", None)
            if doc.get("type") == "result":
                result = doc.get("result")
                return result if isinstance(result, dict) else {}
            error = doc.get("error") or {}
            retry_after = error.get("retryAfterMs")
            raise CapabilityError(
                str(error.get("code")),
                str(error.get("detail")),
                str(error.get("retryable")),
                retry_after if isinstance(retry_after, int) else None,
            )

    def _event(self, method: str, params: dict[str, Any]) -> None:
        if not self.active:
            return
        self._framing.send(
            {
                "v": VERSION,
                "type": "event",
                "id": f"e{self._next_id}",
                "method": method,
                "params": params,
            }
        )
        self._next_id += 1

    # -- the frozen authoring surface ------------------------------------

    def net_fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        """The only network path (D14): host-mediated, polite-runtime,
        scoped to the manifest's declared domains on every hop."""
        params: dict[str, Any] = {"url": url}
        if method != "GET":
            params["method"] = method
        if headers:
            params["headers"] = headers
        if body is not None:
            params["body"] = body
        if max_bytes is not None:
            params["maxBytes"] = max_bytes
        return self._call("cap.net.fetch", params)

    def state_get(self, key: str) -> Any:
        return self._call("cap.state.get", {"key": key}).get("value")

    def state_set(self, key: str, value: Any) -> int:
        return int(self._call("cap.state.set", {"key": key, "value": value}).get("bytes") or 0)

    def items_emit(self, items: list[dict[str, Any]]) -> int:
        return int(self._call("cap.items.emit", {"items": items}).get("accepted") or 0)

    def secrets_need(self, slot: str) -> str:
        """Resolution status, never a value (D14): returns the placeholder
        the host substitutes host-side into the next ``net.fetch`` HEADER
        (URL placeholders are refused typed at the seam — secrets ride
        headers only) — the secret value itself is structurally unable to
        cross this seam."""
        return str(self._call("cap.secrets.need", {"slot": slot}).get("injectedAs") or "")

    def progress(self, *, percent: int | None = None, message_key: str | None = None) -> None:
        params: dict[str, Any] = {}
        if percent is not None:
            params["percent"] = percent
        if message_key is not None:
            params["messageKey"] = message_key
        self._event("evt.progress", params)

    def log(self, level: str, message: str) -> None:
        self._event("evt.log", {"level": level, "message": message[:500]})


def build_capability_module(client: CapabilityClient) -> ModuleType:
    """The frozen ``capability`` module — the sandbox's entire SDK."""
    module = ModuleType("capability")
    module.__doc__ = "The capability client — the extension sandbox's whole SDK."
    module.net_fetch = client.net_fetch  # type: ignore[attr-defined]
    module.state_get = client.state_get  # type: ignore[attr-defined]
    module.state_set = client.state_set  # type: ignore[attr-defined]
    module.items_emit = client.items_emit  # type: ignore[attr-defined]
    module.secrets_need = client.secrets_need  # type: ignore[attr-defined]
    module.progress = client.progress  # type: ignore[attr-defined]
    module.log = client.log  # type: ignore[attr-defined]
    module.SandboxError = CapabilityError  # type: ignore[attr-defined]
    module.__all__ = [  # type: ignore[attr-defined]
        "net_fetch",
        "state_get",
        "state_set",
        "items_emit",
        "secrets_need",
        "progress",
        "log",
        "SandboxError",
    ]
    return module


# ------------------------------------------------------------ the audit wall


def install_audit_wall(entry_code: object) -> None:
    """``sys.addaudithook`` enforcement of the frozen surface.

    Denials are typed (charter codes): filesystem family → ``path-denied``,
    socket/subprocess family → ``net-denied``, import/eval-family →
    ``unsupported``, environment family → ``invalid``. Details carry the
    operation and (where safe) the resource NAME — never host paths.
    """

    def hook(event: str, args: tuple[object, ...]) -> None:
        if event == "exec":
            if args and args[0] is entry_code:
                return
            raise SandboxViolation("unsupported", "dynamic execution denied")
        if event in ("compile", "builtins.input", "builtins.breakpoint"):
            raise SandboxViolation("unsupported", f"{event} denied")
        if event == "import":
            module = str(args[0]) if args else ""
            if module not in MODULE_ALLOWLIST:
                raise SandboxViolation(
                    "unsupported", f"import {module!r} outside the frozen module surface"
                )
        if event == "open":
            raise SandboxViolation(
                "path-denied", "filesystem access denied (no fs capability at this seam)"
            )
        if event in (
            "os.system",
            "os.exec",
            "os.fork",
            "os.forkpty",
            "os.spawn",
            "os.posix_spawn",
            "os.posix_spawnp",
            "subprocess.Popen",
            "os.startfile",
        ):
            raise SandboxViolation(
                "net-denied", f"{event} denied (no process capability at this seam)"
            )
        if event in (
            "socket.__new__",
            "socket.bind",
            "socket.connect",
            "socket.sendto",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyname_ex",
            "socket.getnameinfo",
        ):
            raise SandboxViolation(
                "net-denied", f"{event} denied (connectors never open sockets, D14)"
            )
        if event in (
            "os.remove",
            "os.rename",
            "os.replace",
            "os.rmdir",
            "os.unlink",
            "os.mkdir",
            "os.chmod",
            "os.chown",
            "os.link",
            "os.symlink",
            "os.truncate",
            "os.utime",
            "os.listdir",
            "os.scandir",
        ):
            raise SandboxViolation("path-denied", f"{event} denied (no fs capability at this seam)")
        # Disclosed residual (ADR-0030 'containment is not trust'): CPython
        # raises no audit event for os.stat/lstat, so metadata probing of
        # guessed paths is not denyable here — content access (open,
        # listdir) is, which is the exfiltration-relevant surface.
        if event in ("os.putenv", "os.unsetenv", "os.environ"):
            raise SandboxViolation(
                "invalid", "environment access denied (host env never crosses the seam)"
            )
        if event in (
            "os.dup",
            "os.dup2",
            "os.pipe",
            "os.kill",
            "os.killpg",
            "os.setuid",
            "os.setgid",
            "os.setgroups",
            "os.setsid",
        ):
            raise SandboxViolation("net-denied", f"{event} denied")
        if event in (
            "ctypes.dlopen",
            "ctypes.dlsym",
            "ctypes.call_function",
            "mmap.__new__",
            "pty.spawn",
            "pickle.find_class",
            "webbrowser.open",
        ):
            raise SandboxViolation("unsupported", f"{event} denied")

    sys.addaudithook(hook)


def restricted_builtins() -> dict[str, object]:
    """Builtins for the extension namespace: the safe core, minus the
    eval-family and filesystem surface (the audit wall stays the real
    enforcement; this is the second layer)."""
    blocked = frozenset(
        {
            "open",
            "exec",
            "eval",
            "compile",
            "input",
            "breakpoint",
            "exit",
            "quit",
            "help",
            "license",
            "credits",
            "copyright",
        }
    )
    builtins_module = sys.modules["builtins"]
    safe = {
        name: getattr(builtins_module, name)
        for name in dir(builtins_module)
        if not name.startswith("_") and name not in blocked
    }
    safe["__import__"] = __import__
    safe["__build_class__"] = builtins_module.__build_class__
    return safe


# ------------------------------------------------------- content integrity


def digest_content(content_dir: str) -> str:
    """Mirror of the host's ``lifecycle.digest_tree`` (sorted rel paths,
    path+NUL+size+NUL+bytes; .git/symlinks/non-regular skipped) — the
    child refuses to run unless the tree hashes to the pinned digest."""
    import hashlib
    from pathlib import Path

    root = Path(content_dir)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


class _Sink:
    """Replaces sys.stdout/stderr before the extension loads — prints can
    never corrupt protocol framing (bounded, discarded)."""

    def __init__(self) -> None:
        self.count = 0

    def write(self, text: str) -> int:
        self.count += len(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def close(self) -> None:
        return None

    @property
    def encoding(self) -> str:
        return "utf-8"


# --------------------------------------------------------------- the loop


def extension_error(exc: BaseException) -> dict[str, Any]:
    """Map an extension exception onto the charter error envelope —
    capped JSON data, never a raw exception string (protocol §8)."""
    if isinstance(exc, CapabilityError):
        envelope: dict[str, Any] = {
            "code": exc.code if exc.code in ERROR_CODES else "provider",
            "detail": _bounded_detail(exc.detail),
            "retryable": exc.retryable if exc.retryable in RETRYABLE else "no",
        }
        if exc.retry_after_ms is not None:
            envelope["retryAfterMs"] = exc.retry_after_ms
        return envelope
    if isinstance(exc, SandboxViolation):
        return {
            "code": exc.code,
            "detail": _bounded_detail({"message": exc.detail}),
            "retryable": "no",
        }
    return {
        "code": "provider",
        "detail": _bounded_detail({"engine": type(exc).__name__}),
        "retryable": "no",
    }


def load_extension(
    content_dir: str, entry: str, digest: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Trusted bootstrap phase — runs BEFORE the audit wall exists.

    Reads + compiles the entry (the tree's digest was verified by the
    caller before this ran), pre-imports the allowlist (so later imports
    of allowed modules are cache hits, not audit events), and executes
    the entry in a restricted namespace with the frozen ``capability``
    module injected. Returns (identity, load_error) — exactly one is
    meaningful: a load failure becomes the typed error every invoke
    receives, never a silent half-run."""
    from pathlib import Path

    try:
        root = Path(content_dir)
        manifest_bytes = (root / "manifest.json").read_bytes()
        if len(manifest_bytes) > MANIFEST_MAX_BYTES:
            raise ValueError("manifest exceeds manifestMaxBytes")
        manifest = json.loads(manifest_bytes)
        source = (root / entry).read_bytes()
        namespace: dict[str, Any] = {
            "__name__": "extension",
            "__file__": entry,
            "__builtins__": restricted_builtins(),
        }
        # Import the allowlist up front; hand the frozen client to the
        # extension through ``sys.modules`` (plain ``import capability``).
        for module_name in sorted(MODULE_ALLOWLIST):
            if module_name != "capability" and module_name not in sys.modules:
                __import__(module_name)
        client = CapabilityClient(FRAMING)
        capability = build_capability_module(client)
        sys.modules["capability"] = capability
        namespace["capability"] = capability
        code = compile(source, entry, "exec")
        install_audit_wall(code)
        exec(code, namespace)
    except SandboxViolation as exc:
        return {}, {
            "code": exc.code,
            "detail": _bounded_detail({"message": exc.detail}),
            "retryable": "no",
        }
    except Exception:
        return {}, {
            "code": "invalid",
            "detail": _bounded_detail({"stage": "load"}),
            "retryable": "no",
        }
    identity = {
        "id": str(manifest.get("id") or ""),
        "version": str(manifest.get("version") or ""),
        "digest": digest,
    }
    return {"identity": identity, "client": client, "namespace": namespace}, None


FRAMING = Framing()


def run(content_dir: str, entry: str, digest: str) -> int:
    # Redirect FIRST — extension top-level prints must never touch the
    # protocol stream. The Framing holds the real descriptors.
    sys.stdout = _Sink()  # type: ignore[assignment]
    sys.stderr = _Sink()  # type: ignore[assignment]
    loaded, identity_error = load_extension(content_dir, entry, digest)
    client: CapabilityClient | None = loaded.get("client")
    namespace: dict[str, Any] = loaded.get("namespace") or {}
    if client is None:
        client = CapabilityClient(FRAMING)

    while True:
        doc = FRAMING.recv()
        if doc is None:
            return 0
        problem = validate_message(doc)
        if problem is not None:
            FRAMING.violate(problem)
            continue
        mtype, mid = doc["type"], doc["id"]
        if mtype in ("result", "error", "event"):
            FRAMING.violate(f"unexpected {mtype} toward the extension")
            continue
        method = doc["method"]
        params = doc.get("params") or {}
        if method == "ext.dispose":
            FRAMING.send({"v": VERSION, "type": "result", "id": mid, "result": {}})
            return 0
        if identity_error is not None:
            FRAMING.send(
                {
                    "v": VERSION,
                    "type": "error",
                    "id": mid,
                    "method": method,
                    "error": identity_error,
                }
            )
            continue
        op = str(params.get("op") or "")
        if op == "hello":
            FRAMING.send(
                {
                    "v": VERSION,
                    "type": "result",
                    "id": mid,
                    "result": {"output": dict(loaded["identity"])},
                }
            )
            continue
        handler = namespace.get("fetch") if op == "fetch" else None
        if op != "fetch" or not callable(handler):
            FRAMING.send(
                {
                    "v": VERSION,
                    "type": "error",
                    "id": mid,
                    "method": method,
                    "error": {
                        "code": "unsupported",
                        "detail": _bounded_detail({"op": op[:64]}),
                        "retryable": "no",
                    },
                }
            )
            continue
        raw_input = params.get("input")
        if not isinstance(raw_input, dict):
            FRAMING.send(
                {
                    "v": VERSION,
                    "type": "error",
                    "id": mid,
                    "method": method,
                    "error": {
                        "code": "invalid",
                        "detail": "invoke input must be an object",
                        "retryable": "no",
                    },
                }
            )
            continue
        if len(json.dumps(raw_input).encode("utf-8")) > INPUT_MAX_BYTES:
            FRAMING.send(
                {
                    "v": VERSION,
                    "type": "error",
                    "id": mid,
                    "method": method,
                    "error": {
                        "code": "invalid",
                        "detail": "invoke input exceeds the byte cap",
                        "retryable": "no",
                    },
                }
            )
            continue
        client.active = True
        try:
            output = handler(raw_input.get("config") or {}, raw_input.get("state") or {})
            if not isinstance(output, dict):
                raise CapabilityError("invalid", "fetch must return an object", "no", None)
            FRAMING.send({"v": VERSION, "type": "result", "id": mid, "result": {"output": output}})
        except BaseException as exc:
            FRAMING.send(
                {
                    "v": VERSION,
                    "type": "error",
                    "id": mid,
                    "method": method,
                    "error": extension_error(exc),
                }
            )
        finally:
            client.active = False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extension-sandbox-child")
    parser.add_argument("--protocol", default=PROTOCOL)
    parser.add_argument("--content-dir", required=True)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--digest", required=True)
    args = parser.parse_args(argv)
    if args.protocol != PROTOCOL:
        return 2
    if args.entry != ENTRY_FILE:
        return 2
    try:
        actual = digest_content(args.content_dir)
    except OSError:
        return 2
    if actual != args.digest:
        return 2
    return run(args.content_dir, args.entry, actual)


if __name__ == "__main__":
    try:
        exit_code = main()
    except (Exception, KeyboardInterrupt):  # pragma: no cover — never leak a traceback
        exit_code = 70
    sys.exit(exit_code)
