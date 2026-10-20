"""Linux kernel isolation for the T2 child (plan 37 Phase 5).

The capability RPC seam, the frozen module surface and the audit hooks are
defense in depth; they are not a kernel boundary. This module wraps the
child in bubblewrap with no network namespace route and a read-only view of
only the interpreter, the child script and the extension content. If the
primitive is unavailable the caller must self-disable T2 with a precise
reason — never run weak.

The wrapper is deliberately Linux-first: Windows/macOS hosts report
``t2Isolation: none`` and keep T2 off by default until their primitive
lands (plan 37 §9 / principle 11).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

BWRAP = shutil.which("bwrap")


class IsolationUnavailable(RuntimeError):
    """The platform cannot provide the kernel boundary T2 claims."""


def available() -> bool:
    return sys.platform.startswith("linux") and BWRAP is not None


def posture() -> str:
    """The host-profile value: ``kernel`` only when the primitive is real."""
    return "kernel" if available() else "none"


def _ro_bind(path: str | Path) -> list[str]:
    candidate = Path(path)
    if not candidate.exists():
        return []
    return ["--ro-bind", str(candidate), str(candidate)]


def wrap_child_command(
    *,
    interpreter: list[str],
    child_path: Path,
    content_dir: Path,
    child_args: list[str],
) -> list[str]:
    """Return the argv that runs the child inside the kernel sandbox.

    ``interpreter`` is the host's spawn argv prefix (usually
    ``[sys.executable]``; a frozen build may carry extra flags).
    ``child_args`` are the arguments after the child script path; the
    content dir is mounted at ``/ext`` and any occurrence of the real
    content-dir path is rewritten to ``/ext`` so the child's protocol stays
    unchanged.
    """
    if not available():
        raise IsolationUnavailable(
            "bubblewrap is unavailable on this platform — T2 self-disables "
            "(install bubblewrap or run on a supported Linux host)"
        )

    binds: list[str] = []
    for system_path in ("/usr", "/lib", "/lib64", "/bin", "/sbin"):
        binds.extend(_ro_bind(system_path))
    # The interpreter (venv or system), the child script's directory (host
    # code, read-only) and any prefix the interpreter needs.
    prefixes = {
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(interpreter[0]).resolve().parent,
        Path(interpreter[0]).resolve().parent.parent,
    }
    for prefix in prefixes:
        if str(prefix) not in ("/", ""):
            binds.extend(_ro_bind(prefix))
    binds.extend(_ro_bind(child_path.parent))

    rewritten = [
        str(arg).replace(str(content_dir), "/ext") for arg in child_args
    ]
    argv = [
        str(BWRAP),
        "--unshare-all",
        "--die-with-parent",
        "--clearenv",
        *binds,
        "--ro-bind",
        str(content_dir.resolve()),
        "/ext",
        "--dev",
        "/dev",
        "--tmpfs",
        "/work",
        "--chdir",
        "/work",
        "--setenv",
        "PATH",
        "/usr/local/bin:/usr/bin:/bin",
        "--setenv",
        "HOME",
        "/work",
        *interpreter,
        "-I",
        "-B",
        str(child_path),
        *rewritten,
    ]
    return argv
