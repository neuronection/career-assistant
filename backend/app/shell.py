"""Desktop shell: pywebview window (or system browser) over a local server.

Ported from the Study Assistant sibling project. The SPA is served by the
same FastAPI process (see app.main), so the window points at a loopback
URL — the frontend needs no desktop-specific code.
"""

import json
import logging
import os
import socket
import threading
import webbrowser
from collections.abc import MutableMapping, Sequence
from pathlib import Path
from typing import Any, TypedDict

import uvicorn

from app.core.config import settings
from app.main import create_app

logger = logging.getLogger(__name__)

_SNAP_POLLUTED_VARS = (
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "GDK_BACKEND",
    "GIO_MODULE_DIR",
    "GSETTINGS_SCHEMA_DIR",
    "XDG_DATA_HOME",
    "XDG_CONFIG_DIRS",
    "XDG_CACHE_HOME",
)

WINDOW_STATE_FILE = "window-state.json"
DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 800
MIN_WINDOW_WIDTH = 640
MIN_WINDOW_HEIGHT = 480
VISIBLE_MARGIN = 80


def sanitize_environment(
    environ: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    """Undo snap/VS Code environment pollution before GTK/WebKit init."""
    env: MutableMapping[str, str] = os.environ if environ is None else environ

    for name in _SNAP_POLLUTED_VARS:
        original = env.get(f"{name}_VSCODE_SNAP_ORIG")
        if original is not None:
            if original:
                env[name] = original
            else:
                env.pop(name, None)
            continue
        value = env.get(name)
        if not value:
            continue
        if name in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
            kept = [e for e in value.split(":") if e and "/snap/" not in e]
            if kept:
                env[name] = ":".join(kept)
            else:
                env.pop(name, None)
        elif "/snap/" in value:
            env.pop(name, None)
    return env


def find_free_port() -> int:
    """Grab an unused loopback port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class WindowState(TypedDict, total=False):
    width: int
    height: int
    x: int
    y: int
    maximized: bool


def default_window_state() -> WindowState:
    return {"width": DEFAULT_WINDOW_WIDTH, "height": DEFAULT_WINDOW_HEIGHT}


def _screen_for(x: int, y: int, screens: Sequence[Any]) -> Any | None:
    for screen in screens:
        if (
            screen.x <= x < screen.x + screen.width
            and screen.y <= y < screen.y + screen.height
        ):
            return screen
    return None


def clamp_window_state(state: WindowState, screens: Sequence[Any]) -> WindowState:
    """Keep the restored window on-screen and within sane size bounds."""
    width = max(MIN_WINDOW_WIDTH, state.get("width", DEFAULT_WINDOW_WIDTH))
    height = max(MIN_WINDOW_HEIGHT, state.get("height", DEFAULT_WINDOW_HEIGHT))
    clamped: WindowState = {"width": width, "height": height}
    if "maximized" in state:
        clamped["maximized"] = bool(state["maximized"])
    if not screens:
        return clamped

    screen = screens[0]
    if "x" in state and "y" in state:
        screen = _screen_for(int(state["x"]), int(state["y"]), screens) or screen
    width = max(MIN_WINDOW_WIDTH, min(width, screen.width))
    height = max(MIN_WINDOW_HEIGHT, min(height, screen.height))
    clamped["width"] = width
    clamped["height"] = height

    if "x" in state and "y" in state:
        left_limit = screen.x - width + VISIBLE_MARGIN
        right_limit = screen.x + screen.width - VISIBLE_MARGIN
        clamped["x"] = max(left_limit, min(int(state["x"]), right_limit))
        clamped["y"] = max(
            screen.y, min(int(state["y"]), screen.y + screen.height - VISIBLE_MARGIN)
        )
    else:
        clamped["x"] = screen.x + (screen.width - width) // 2
        clamped["y"] = screen.y + (screen.height - height) // 2
    return clamped


def load_window_state(data_dir: Path, screens: Sequence[Any]) -> WindowState:
    path = data_dir / WINDOW_STATE_FILE
    state: WindowState = default_window_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default_window_state()
        state = {
            "width": int(raw.get("width", DEFAULT_WINDOW_WIDTH)),
            "height": int(raw.get("height", DEFAULT_WINDOW_HEIGHT)),
        }
        if isinstance(raw.get("x"), int) and isinstance(raw.get("y"), int):
            state["x"] = raw["x"]
            state["y"] = raw["y"]
        if isinstance(raw.get("maximized"), bool):
            state["maximized"] = raw["maximized"]
    except (OSError, ValueError, TypeError):
        return default_window_state()
    return clamp_window_state(state, screens)


def save_window_state(data_dir: Path, state: WindowState) -> None:
    path = data_dir / WINDOW_STATE_FILE
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(dict(state)), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.warning("Could not persist window state", exc_info=True)


class WindowGeometryTracker:
    """Tracks window geometry events into a persistable WindowState."""

    def __init__(
        self, width: int, height: int, x: int, y: int, maximized: bool = False
    ) -> None:
        self._placed = (x, y)
        self._base: tuple[int, int] | None = None
        self._pre_maximize: tuple[int, int] | None = None
        self.state: WindowState = {
            "width": width,
            "height": height,
            "x": x,
            "y": y,
            "maximized": maximized,
        }

    def on_moved(self, x: int, y: int) -> None:
        if self.state.get("maximized"):
            return
        if self._base is None:
            self._base = (x, y)
            return
        self.state["x"] = self._placed[0] + x - self._base[0]
        self.state["y"] = self._placed[1] + y - self._base[1]

    def on_resized(self, width: int, height: int) -> None:
        if self.state.get("maximized"):
            return
        self.state["width"] = width
        self.state["height"] = height

    def on_maximized(self) -> None:
        self._pre_maximize = (self.state["width"], self.state["height"])
        self.state["maximized"] = True

    def on_restored(self) -> None:
        self.state["maximized"] = False
        if self._pre_maximize is not None:
            self.state["width"], self.state["height"] = self._pre_maximize


def run_browser() -> None:
    """Serve on a loopback port and open the system browser.

    Prefers the configured API_PORT (so it doubles as a lightweight personal
    server), falling back to a random free port when it is taken.
    """
    app = create_app()
    port = settings.API_PORT
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    except OSError:
        port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def _maybe_start_tray(
    session_factory,
    desktop_settings,
    data_dir,
    on_quit,
):
    """Start the pystray icon + poll loop, or None when unavailable.

    Missing pystray / no AppIndicator host ⇒ degrade to window-only mode.
    """
    from app.desktop.tray import TrayActions, TrayIcon

    try:
        import pystray  # noqa: F401
    except Exception:  # noqa: BLE001 — optional desktop dependency
        logger.info("pystray unavailable — running without a tray icon")
        return None
    try:
        actions = TrayActions(session_factory, _bridge_holder["bridge"])
        tray = TrayIcon(actions, desktop_settings, data_dir, on_quit)
        tray.start()
        thread = threading.Thread(target=_tray_loop, args=(tray,), daemon=True)
        thread.start()
        return tray
    except Exception:  # noqa: BLE001 — a missing systray host must not kill us
        logger.warning("Tray init failed — continuing without a tray", exc_info=True)
        return None


def _tray_loop(tray) -> None:
    import time

    while True:
        try:
            tray.poll()
        except Exception:  # noqa: BLE001 — the loop must survive
            logger.debug("Tray poll failed", exc_info=True)
        time.sleep(tray.POLL_SECONDS)


def run(tray_only: bool = False) -> None:
    """Desktop background mode (Phase 30): window + tray over the local
    server; close-to-tray keeps everything running, quit is graceful.

    `tray_only` (--tray) boots hidden for auto-start; the window opens on
    demand (tray or second-launch focus ping). The first-run close-to-tray
    opt-in prompt is rendered by the SPA through the bridge (DesktopApi).
    """
    import webview

    from app.desktop import shell_token
    from app.desktop import notifier
    from app.desktop.bridge import DesktopApi, DesktopBridge
    from app.desktop.single_instance import SingleInstance
    from app.services.notification_channels import unregister_channel

    sanitize_environment()
    data_dir = settings.data_dir_path
    data_dir.mkdir(parents=True, exist_ok=True)

    bridge = DesktopBridge()
    _bridge_holder["bridge"] = bridge
    instance = SingleInstance(data_dir, on_focus_request=bridge.show_and_focus)
    if not instance.acquire():
        # Second launch: the failed acquire already pinged the running
        # instance to focus (socket handshake) — exit instead of binding.
        return

    from app.desktop.settings import DesktopSettings

    desktop_settings = DesktopSettings.load(data_dir)
    _settings_holder["settings"] = desktop_settings
    _settings_holder["data_dir"] = data_dir

    app = create_app()
    port = find_free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    )
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    from app.core.database import AsyncSessionLocal

    _session_factory_holder["factory"] = AsyncSessionLocal

    # The desktop channel consumes the plan-24 funnel from process boot —
    # misfired schedules (asap) surface as toasts, not a silent backlog.
    notifier.register_desktop_channel(bridge)

    # Marks the shell's document requests so the security headers middleware
    # can serve the desktop CSP variant (pywebview's evaluate_js needs it).
    shell_query = shell_token.issue()

    state = load_window_state(data_dir, webview.screens)
    window = webview.create_window(
        settings.APP_NAME,
        f"http://127.0.0.1:{port}/?shell={shell_query}",
        width=state["width"],
        height=state["height"],
        x=state.get("x"),
        y=state.get("y"),
        maximized=state.get("maximized", False),
        min_size=(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
        hidden=tray_only,
        js_api=DesktopApi(bridge),
    )
    if window is None:
        raise RuntimeError("webview window creation failed")
    bridge.attach(window)

    def on_closing():
        """Close-to-tray: hide instead of dying; Quit destroys for real.

        Unchosen (first run before the SPA prompt) closes outright.
        """
        from app.desktop.settings import should_hide_on_close

        if should_hide_on_close(data_dir):
            try:
                window.hide()
            except Exception:  # noqa: BLE001
                logger.warning("Could not hide to tray", exc_info=True)
            return False  # cancels the close (pywebview closing event)
        return None

    tracker = WindowGeometryTracker(
        width=state["width"],
        height=state["height"],
        x=state.get("x", 0),
        y=state.get("y", 0),
        maximized=state.get("maximized", False),
    )
    window.events.closing += on_closing
    window.events.moved += tracker.on_moved
    window.events.resized += tracker.on_resized
    window.events.maximized += tracker.on_maximized
    window.events.restored += tracker.on_restored
    window.events.closed += lambda: save_window_state(data_dir, tracker.state)

    def on_quit() -> None:
        try:
            window.destroy()
        except Exception:  # noqa: BLE001 — the shell is quitting anyway
            logger.warning("Window destroy failed", exc_info=True)

    tray = _maybe_start_tray(
        _session_factory_holder["factory"], desktop_settings, data_dir, on_quit
    )
    if tray_only and tray is None:
        window.show()  # no tray host: degrade to a visible window

    webview.start(private_mode=False, debug=settings.DEBUG)

    # Window gone (quit or real close): same shutdown order as plan 10 —
    # stop uvicorn last (lifespan cancels the scheduler, drains the queue).
    bridge.detach()
    shell_token.reset()
    if tray is not None:
        tray.stop()
    unregister_channel("desktop")
    _bridge_holder["bridge"] = None
    _settings_holder["settings"] = None
    server.should_exit = True
    thread.join(timeout=30)
    instance.release()


_bridge_holder: dict = {"bridge": None}
_settings_holder: dict = {"settings": None, "data_dir": None}
_session_factory_holder: dict = {"factory": None}
