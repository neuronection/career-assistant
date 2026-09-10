"""Desktop shell settings: `<data_dir>/desktop-settings.json`.

Shell-level prefs only (tray behaviour, auto-start) — they gate window
behaviour, not notification delivery. Notification *channel* preferences
(desktop toasts on/off, quiet hours) live server-side per user in
`notification_preferences` so the dispatch guard can honor them.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DESKTOP_SETTINGS_FILE = "desktop-settings.json"

PROMPT_NEEDED = None  # close_to_tray value: the user has not chosen yet.


class DesktopSettings:
    """Close-to-tray / auto-start switches persisted in the data dir."""

    def __init__(
        self,
        close_to_tray: Optional[bool] = None,
        autostart: bool = False,
    ) -> None:
        self.close_to_tray = close_to_tray
        self.autostart = autostart

    @classmethod
    def load(cls, data_dir: Path) -> "DesktopSettings":
        path = data_dir / DESKTOP_SETTINGS_FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls()
            close = raw.get("close_to_tray", PROMPT_NEEDED)
            return cls(
                close_to_tray=None if close is None else bool(close),
                autostart=bool(raw.get("autostart", False)),
            )
        except (OSError, ValueError):
            return cls()

    def save(self, data_dir: Path) -> None:
        path = data_dir / DESKTOP_SETTINGS_FILE
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(
                    {
                        "close_to_tray": self.close_to_tray,
                        "autostart": self.autostart,
                    }
                ),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except OSError:
            logger.warning("Could not persist desktop settings", exc_info=True)


def resolve_close_to_tray(settings: DesktopSettings) -> bool:
    """Whether a window close should hide to the tray.

    The plan default is ON *after* the opt-in first-run prompt: until the
    user chooses, the shell asks once (prompt) and stores the answer —
    an unchosen setting falls back to closing outright (least surprise).
    """
    return settings.close_to_tray is True


def should_hide_on_close(data_dir: Path) -> bool:
    """Fresh-read check for the shell's closing handler (tray toggles
    rewrite the file at runtime)."""
    return DesktopSettings.load(data_dir).close_to_tray is True
