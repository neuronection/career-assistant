"""Frozen-build capability check for the T2 sandbox (plan 32 Phase 5
follow-up). The child spawns as ``<interpreter> -I -B child.py`` — a
PyInstaller-frozen host has no real interpreter behind ``sys.executable``
(it is the app bundle itself), and the frozen layout ships the child
bootstrap only as spec-declared data. The enginecheck precedent (plan
76): capability detection, never a hard dependency — an absent runtime
raises :class:`SandboxRuntimeUnavailable` BEFORE any spawn, and the
connector rides the Phase-5 kill-switch path (self-disable with the
surfaced remedy), so a T2 install on a frozen build degrades honestly
instead of crashing every sync.

Frozen layout (the spec's datas entry documents the same):
``sys._MEIPASS/app/extensions/runtime/sandbox/child.py`` next to the
bundled ``contracts/`` set.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

#: Time-boxed interpreter probe (`<python> -I -B -c "print(major)"`).
_PROBE_TIMEOUT_S = 10.0

_PROBE_CODE = "import sys; print(sys.version_info[0])"

_REMEDY = (
    "the T2 sandbox needs a Python interpreter to spawn its child — "
    "frozen builds bundle none (sys.executable is the app itself); "
    "run the T2 host from source (./scripts/run-dev.sh) or ship a "
    "bundled runtime in the package layout"
)

ProbeFn = Callable[[list[str]], None]


class SandboxRuntimeUnavailable(Exception):
    """The host cannot spawn sandbox children (assets or interpreter
    missing) — the surfaced reason names the remedy."""


def child_asset() -> Path:
    """The child bootstrap's real file path — dev/source layout next to
    this module, the frozen bundle's datas copy when packaged."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "app" / "extensions" / "runtime" / "sandbox" / "child.py"
    return Path(__file__).resolve().parent / "child.py"


def interpreter_argv() -> list[str]:
    """The spawn prefix for sandbox children.

    From source this is the running interpreter (the project venv).
    Frozen builds bundle no interpreter: the check accepts a runtime
    dropped into the bundle layout (``<bundle>/runtime/python``) so a
    future package can carry one without code changes."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        bundled = base / "runtime" / "python"
        if bundled.is_file():
            return [str(bundled)]
        raise SandboxRuntimeUnavailable(_REMEDY)
    return [sys.executable]


def _default_probe(argv: list[str]) -> None:
    """One real probe: the interpreter must answer ``-I -B`` isolated."""
    try:
        result = subprocess.run(
            [*argv, "-I", "-B", "-c", _PROBE_CODE],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SandboxRuntimeUnavailable(
            f"{_REMEDY} (probe failed: {exc.__class__.__name__})"
        ) from exc
    if result.returncode != 0 or not result.stdout.strip().isdigit():
        raise SandboxRuntimeUnavailable(f"{_REMEDY} (probe answered rc={result.returncode})")


_probe_cache: tuple[list[str], Path] | None = None


def check_sandbox_runtime(*, probe: ProbeFn | None = None) -> tuple[list[str], Path]:
    """Verify the child assets exist and the interpreter spawns isolated.

    Cached per process after the first success; every failure raises
    :class:`SandboxRuntimeUnavailable` with the remedy — callers map it
    onto the lifecycle (self-disable), never a raw traceback."""
    global _probe_cache
    if _probe_cache is not None:
        return _probe_cache
    argv = interpreter_argv()
    child = child_asset()
    if not child.is_file():
        raise SandboxRuntimeUnavailable(
            f"the sandbox child bootstrap is missing from this install "
            f"(expected {child}) — {_REMEDY}"
        )
    (probe or _default_probe)(argv)
    _probe_cache = (argv, child)
    return _probe_cache


def reset_runtime_cache() -> None:
    """Test hook: drop the per-process probe cache."""
    global _probe_cache
    _probe_cache = None
