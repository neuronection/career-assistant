"""pywebview bridge: the in-process desktop notification + focus channel.

Backend → SPA pushes arrive as `evaluate_js` calls into
`window.__caDesktopBridge.onNotify(...)` (the SPA's handler decides
native Notification API vs in-page fallback — plan 36's single-surface
rule lives there). SPA → backend calls go through the `js_api` object
(`pywebview.api.activate(link)` for toast click-through).
"""

import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

READY_FLAG = "__caDesktopReady"


class DesktopApi:
    """Object exposed to the SPA as `window.pywebview.api`.

    Beyond toast activation this carries the desktop shell settings so
    the first-run close-to-tray prompt renders in-app (the GUI loop is
    already running by then) and stores the user's choice server-side.
    """

    def __init__(self, bridge: "DesktopBridge") -> None:
        self._bridge = bridge

    def ready(self) -> bool:
        """SPA announces the page (and the bridge handler) is live."""
        self._bridge.mark_ready()
        return True

    def activate(self, link: str = "") -> bool:
        """Toast click-through: show/unhide + focus the window.

        The SPA navigates to `link` itself once this resolves — the shell
        never owns the router.
        """
        self._bridge.show_and_focus()
        return True

    def desktop_settings(self) -> dict:
        """Shell prefs for the SPA (close-to-tray prompt state etc.)."""
        from app.shell import _settings_holder

        settings_obj = _settings_holder["settings"]
        if settings_obj is None:
            return {"close_to_tray": None, "autostart": False}
        return {
            "close_to_tray": settings_obj.close_to_tray,
            "autostart": settings_obj.autostart,
        }

    def set_close_to_tray(self, value: bool) -> bool:
        """First-run prompt answer (stores the choice; persists it)."""
        from app.shell import _settings_holder

        settings_obj = _settings_holder["settings"]
        data_dir = _settings_holder["data_dir"]
        if settings_obj is None or data_dir is None:
            return False
        settings_obj.close_to_tray = bool(value)
        settings_obj.save(data_dir)
        return True

    def set_autostart(self, value: bool) -> bool:
        """Toggle login auto-start (tray-menu parity for the SPA)."""
        from app.desktop import autostart
        from app.shell import _settings_holder

        settings_obj = _settings_holder["settings"]
        data_dir = _settings_holder["data_dir"]
        if settings_obj is None or data_dir is None:
            return False
        settings_obj.autostart = bool(autostart.set_autostart(bool(value)))
        settings_obj.save(data_dir)
        return True


class DesktopBridge:
    """Holds the pywebview window and pushes notifications into it.

    Notifications emitted before the SPA signals ready are queued and
    flushed on `ready()` — boot catch-up toasts never race page load.
    """

    def __init__(self) -> None:
        self._window: Any = None
        self._lock = threading.Lock()
        self._ready = False
        self._pending: list[dict] = []

    def attach(self, window: Any) -> None:
        self._window = window

    def detach(self) -> None:
        with self._lock:
            self._window = None
            self._ready = False
            self._pending.clear()

    def mark_ready(self) -> None:
        with self._lock:
            self._ready = True
            pending, self._pending = self._pending, []

        for item in pending:
            self._push_js(item)

    def is_ready(self) -> bool:
        with self._lock:
            return self._ready

    def available(self) -> bool:
        with self._lock:
            return self._window is not None

    def show_and_focus(self) -> None:
        window = self._window
        if window is None:
            return
        try:
            window.show()
            window.restore()
            window.evaluate_js("window.focus()")
        except Exception:  # noqa: BLE001 — focus is best-effort
            logger.warning("Could not focus desktop window", exc_info=True)

    def notify(
        self,
        *,
        title: str,
        body: str,
        kind: str,
        severity: str = "info",
        link: str = "",
    ) -> bool:
        """Push one toast into the page. True when handed to the bridge.

        A False return means no live window — the caller falls back to
        the OS-level path. Content is capped like the inbox rows.
        """
        item = {
            "title": title[:200],
            "body": (body or "")[:500],
            "kind": kind,
            "severity": severity,
            "link": link if isinstance(link, str) and link.startswith("/") else "",
        }
        with self._lock:
            if self._window is None:
                return False
            if not self._ready:
                self._pending.append(item)
                return True
        return self._push_js(item)

    def _push_js(self, item: dict) -> bool:
        window = self._window
        if window is None:
            return False
        try:
            window.evaluate_js(
                f"window.__caDesktopBridge && "
                f"window.__caDesktopBridge.onNotify({json.dumps(item)})"
            )
            return True
        except Exception:  # noqa: BLE001 — toast loss beats a crash
            logger.warning("Desktop toast push failed", exc_info=True)
            return False
