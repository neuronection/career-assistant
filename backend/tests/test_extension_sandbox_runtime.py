"""The T2 frozen-packaging capability check (plan 32 Phase 5 follow-up).

The child spawns ``<interpreter> -I -B child.py`` — a PyInstaller-frozen
host has no real interpreter behind ``sys.executable`` and the child
bootstrap ships only as spec-declared data. These tests prove the
DETECTION logic with mocked lookups (enginecheck precedent: capability
detection, never a hard dependency — no real frozen build needed): the
check must fail closed with a surfaced remedy BEFORE any spawn, and the
connector must ride the Phase-5 kill-switch path (self-disable with the
remedy, typed ``unsupported`` partial error).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.extensions.runtime.sandbox import (
    SandboxRuntimeUnavailable,
)
from app.extensions.runtime.sandbox import (
    runtime as sandbox_runtime,
)


@pytest.fixture(autouse=True)
def _fresh_runtime_cache():
    sandbox_runtime.reset_runtime_cache()
    yield
    sandbox_runtime.reset_runtime_cache()


def test_source_layout_passes_with_mocked_probe(monkeypatch):
    """Dev/source posture: assets exist, the (mocked) interpreter probe
    answers — the check returns the spawn pieces."""
    seen: list[list[str]] = []

    def probe(argv: list[str]) -> None:
        seen.append(argv)

    argv, child = sandbox_runtime.check_sandbox_runtime(probe=probe)
    assert argv == [sys.executable]
    assert child == Path(__file__).resolve().parent.parent / (
        "app/extensions/runtime/sandbox/child.py"
    )
    assert child.is_file(), "the dev layout really ships the child bootstrap"
    assert seen == [argv]


def test_success_is_cached_per_process(monkeypatch):
    calls: list[int] = []

    def probe(argv: list[str]) -> None:
        calls.append(1)

    sandbox_runtime.check_sandbox_runtime(probe=probe)
    sandbox_runtime.check_sandbox_runtime(probe=probe)
    assert len(calls) == 1, "the probe runs once per process, not per spawn"


def test_missing_child_asset_fails_with_remedy(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox_runtime, "child_asset", lambda: tmp_path / "nowhere" / "child.py")
    with pytest.raises(SandboxRuntimeUnavailable) as excinfo:
        sandbox_runtime.check_sandbox_runtime(probe=lambda argv: None)
    message = str(excinfo.value)
    assert "child bootstrap is missing" in message
    assert "run-dev.sh" in message, "the remedy names the source-run path"


def test_frozen_host_without_bundled_runtime_fails(monkeypatch, tmp_path):
    """The recorded Phase-5 hazard: frozen career has no interpreter —
    sys.executable is the app bundle. Without a bundled runtime the T2
    tier is honestly unavailable."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "CareerAssistant"))

    with pytest.raises(SandboxRuntimeUnavailable) as excinfo:
        sandbox_runtime.interpreter_argv()
    assert "frozen builds bundle none" in str(excinfo.value)

    with pytest.raises(SandboxRuntimeUnavailable):
        sandbox_runtime.check_sandbox_runtime(probe=lambda argv: None)


def test_frozen_host_with_bundled_runtime_and_bad_probe_fails(monkeypatch, tmp_path):
    """A future package ships ``<bundle>/runtime/python`` — layout-
    accepted, but a probe that cannot answer ``-I -B`` still fails
    closed (a wrong interpreter is as useless as none)."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "python").write_text("", encoding="utf-8")
    sandbox_dir = tmp_path / "app" / "extensions" / "runtime" / "sandbox"
    sandbox_dir.mkdir(parents=True)
    (sandbox_dir / "child.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "CareerAssistant"))

    def broken_probe(argv: list[str]) -> None:
        raise SandboxRuntimeUnavailable(f"{sandbox_runtime._REMEDY} (probe answered rc=1)")

    with pytest.raises(SandboxRuntimeUnavailable) as excinfo:
        sandbox_runtime.check_sandbox_runtime(probe=broken_probe)
    assert "probe" in str(excinfo.value)


def test_frozen_host_with_bundled_runtime_passes(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "python").write_text("", encoding="utf-8")
    sandbox_dir = tmp_path / "app" / "extensions" / "runtime" / "sandbox"
    sandbox_dir.mkdir(parents=True)
    (sandbox_dir / "child.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "CareerAssistant"))

    argv, child = sandbox_runtime.check_sandbox_runtime(probe=lambda a: None)
    assert argv == [str(runtime_dir / "python")]
    assert child == sandbox_dir / "child.py"
