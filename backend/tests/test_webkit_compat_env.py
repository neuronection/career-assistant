"""WebKit GPU→software→browser fallback chain (ported from study-assistant).

Same contract as study: EGL probe decides GPU vs software rendering, the
render sentinel relaunches with software when the SPA never renders, and
still-dead relaunches into browser mode.
"""

import sys
import threading
from types import SimpleNamespace

import pytest

import app.shell as shell
from app.shell import (
    _plan_fallback,
    _relaunch_argv,
    _watch_renderer,
    apply_webkit_compat_env,
)


def test_compat_env_software_when_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell, "_egl_probe", lambda: False)
    env = apply_webkit_compat_env({})
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert env["WEBKIT_DISABLE_DMABUF_RENDERER"] == "1"
    assert env["WEBKIT_DISABLE_COMPOSITING_MODE"] == "1"
    assert env["GDK_BACKEND"] == "x11"
    assert env["WEBKIT_DISABLE_SANDBOX"] == "1"


def test_compat_env_gpu_when_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell, "_egl_probe", lambda: True)
    env = apply_webkit_compat_env({})
    assert "LIBGL_ALWAYS_SOFTWARE" not in env
    assert "WEBKIT_DISABLE_DMABUF_RENDERER" not in env
    assert "WEBKIT_DISABLE_COMPOSITING_MODE" not in env


def test_compat_env_gpu_forced_overrides_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shell, "_egl_probe", lambda: False)
    env = apply_webkit_compat_env({"CA_WEBKIT_GPU": "1"})
    assert "LIBGL_ALWAYS_SOFTWARE" not in env


def test_compat_env_soft_fallback_marker_forces_software(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shell, "_egl_probe", lambda: True)
    env = apply_webkit_compat_env({"CA_WEBKIT_SOFT_FALLBACK": "1"})
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"


def test_compat_env_persisted_marker_forces_software(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A machine whose GPU path failed once (EGL probe OK, WebKit EGL
    BAD_PARAMETER blank window) must not repeat the blank boot: the
    persisted marker short-circuits the probe on later launches."""
    monkeypatch.setattr(shell, "_egl_probe", lambda: True)
    marker = tmp_path / "webkit_soft_fallback"
    marker.write_text("1", encoding="utf-8")
    env = apply_webkit_compat_env({}, marker=marker)
    assert env["WEBKIT_DISABLE_DMABUF_RENDERER"] == "1"


def test_compat_env_probe_pass_writes_no_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(shell, "_egl_probe", lambda: True)
    marker = tmp_path / "webkit_soft_fallback"
    apply_webkit_compat_env({}, marker=marker)
    assert not marker.exists()
    assert "LIBGL_ALWAYS_SOFTWARE" not in {}


def test_compat_env_software_write_persists_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(shell, "_egl_probe", lambda: False)
    marker = tmp_path / "nested" / "webkit_soft_fallback"
    env = apply_webkit_compat_env({}, marker=marker)
    assert env["WEBKIT_DISABLE_DMABUF_RENDERER"] == "1"
    assert marker.exists()


def test_compat_env_skips_probe_off_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shell, "_egl_probe", lambda: False)
    env = apply_webkit_compat_env({})
    assert "WEBKIT_DISABLE_DMABUF_RENDERER" not in env


def test_relaunch_argv_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/usr/lib/careerassistant/careerassistant")
    monkeypatch.setattr(sys, "argv", ["/usr/lib/careerassistant/careerassistant"])
    assert _relaunch_argv("app") == ["/usr/lib/careerassistant/careerassistant", "app"]


def test_relaunch_argv_dev_replaces_mode_keeps_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(
        sys, "argv", ["backend/careerassistant/__main__.py", "web", "--flag"]
    )
    assert _relaunch_argv("app") == [
        "/usr/bin/python3",
        "-m",
        "careerassistant",
        "--flag",
        "app",
    ]


def test_plan_fallback_first_step_software() -> None:
    env: dict[str, str] = {}
    mode, event = _plan_fallback(env)
    assert mode == "app"
    assert event == "webkit_renderer_dead_relaunching_software"
    assert env["CA_WEBKIT_SOFT_FALLBACK"] == "1"


def test_plan_fallback_second_step_browser() -> None:
    env = {"CA_WEBKIT_SOFT_FALLBACK": "1"}
    mode, event = _plan_fallback(env)
    assert mode == "web"
    assert event == "webkit_still_dead_relaunching_browser_mode"
    assert env["CA_WEBKIT_BROWSER_FALLBACK"] == "1"


def _app_with_state(**attrs: object):
    from fastapi import FastAPI

    app = FastAPI()
    for key, value in attrs.items():
        setattr(app.state, key, value)
    return app


def test_watch_renderer_relaunches_when_page_never_loads() -> None:
    app = _app_with_state()
    fired: list[bool] = []
    _watch_renderer(app, threading.Event(), 0.3, lambda: fired.append(True))
    assert fired == [True]


def test_watch_renderer_quiet_when_page_loaded() -> None:
    app = _app_with_state(spa_rendered=True)
    fired: list[bool] = []
    _watch_renderer(app, threading.Event(), 0.3, lambda: fired.append(True))
    assert fired == []


def test_watch_renderer_cancelled() -> None:
    app = _app_with_state()
    cancel = threading.Event()
    cancel.set()
    fired: list[bool] = []
    _watch_renderer(app, cancel, 0.3, lambda: fired.append(True))
    assert fired == []


def test_watch_renderer_no_relaunch_loop_after_success() -> None:
    app = _app_with_state()
    marker = SimpleNamespace(relaunched=False)

    def relaunch() -> None:
        marker.relaunched = True

    thread = threading.Thread(
        target=_watch_renderer, args=(app, threading.Event(), 0.5, relaunch)
    )
    thread.start()
    import time

    time.sleep(0.1)
    app.state.spa_rendered = True
    thread.join()
    assert marker.relaunched is False


def test_relaunch_self_logs_and_execs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sentinel relaunch crashed on logger.warning(argv=...) — an
    invalid logging kwarg — so the software fallback never engaged
    (Mint 22 blank-window report). The call must be %-style and still
    exec the new process."""
    calls: list[tuple] = []

    def fake_warning(msg, *args, **kwargs):
        calls.append((msg % args if args else msg, kwargs))

    def fake_execv(path, argv):
        calls.append(("execv", argv))

    monkeypatch.setattr(shell.logger, "warning", fake_warning)
    monkeypatch.setattr(shell.os, "execv", fake_execv)
    shell._relaunch_self()
    assert calls[-1][0] == "execv"
    assert not any("argv" in kw for _, kw in calls if isinstance(kw, dict))


def test_software_env_pins_mesa_egl_vendor_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """LIBGL_ALWAYS_SOFTWARE only steers Mesa — on glvnd machines whose
    default EGL vendor is broken hardware (Mint 22 report: EGL_BAD_PARAMETER
    even in software mode), the software fallback must pin Mesa's vendor
    json or WebKit never paints."""
    monkeypatch.setattr(shell, "_egl_probe", lambda: False)
    monkeypatch.setattr(shell, "_MESA_EGL_JSON", tmp_path / "50_mesa.json")
    (tmp_path / "50_mesa.json").write_text("{}", encoding="utf-8")
    env = apply_webkit_compat_env({})
    assert env["__EGL_VENDOR_LIBRARY_FILENAMES"] == str(tmp_path / "50_mesa.json")
