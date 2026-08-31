"""Auto-start on login (opt-in), per-OS: XDG `.desktop` autostart on
Linux, HKCU Run key on Windows, a Launch Agent plist on macOS — all
launch `--tray` so boot lands in tray-only mode.
"""

import logging
import os
import sys
from pathlib import Path
from typing import MutableMapping, Optional

logger = logging.getLogger(__name__)

AUTOSTART_FILE = "career-assistant.desktop"
PLIST_FILE = "com.neuronection.career-assistant.plist"


def _exec_command() -> str:
    """The command line the autostart entry should launch."""
    exe = sys.executable or "python3"
    return f'"{exe}" -m careerassistant app --tray'


def autostart_path(
    environ: Optional[MutableMapping[str, str]] = None,
) -> Optional[Path]:
    env = os.environ if environ is None else environ
    if sys.platform == "linux":
        config_home = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(config_home) / "autostart" / AUTOSTART_FILE
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / PLIST_FILE
    return None  # Windows uses the registry, not a file.


def is_autostart_enabled(environ: Optional[MutableMapping[str, str]] = None) -> bool:
    path = autostart_path(environ)
    if path is not None:
        return path.is_file()
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            )
            winreg.QueryValueEx(key, "CareerAssistant")
            return True
        except OSError:
            return False
    return False


def set_autostart(
    enabled: bool, environ: Optional[MutableMapping[str, str]] = None
) -> bool:
    """Write or remove the login-start entry; True when the state stuck.

    Unsupported platforms degrade honestly (False) — never crash the tray.
    """
    if enabled:
        return _enable(environ)
    return _disable(environ)


def _enable(environ: Optional[MutableMapping[str, str]]) -> bool:
    path = autostart_path(environ)
    if path is None:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            with key:
                winreg.SetValueEx(
                    key, "CareerAssistant", 0, winreg.REG_SZ, _exec_command()
                )
            return True
        except OSError:
            logger.warning("Could not write Windows Run key", exc_info=True)
            return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            body = _launch_agent_plist()
        else:
            body = _xdotool_free_desktop_entry()
        path.write_text(body, encoding="utf-8")
        return True
    except OSError:
        logger.warning("Could not write autostart entry", exc_info=True)
        return False


def _disable(environ: Optional[MutableMapping[str, str]]) -> bool:
    path = autostart_path(environ)
    if path is None:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            with key:
                winreg.DeleteValue(key, "CareerAssistant")
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _xdotool_free_desktop_entry() -> str:
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Career Assistant",
            "Comment=Career Assistant in the background (tray)",
            f"Exec={_exec_command()}",
            "Terminal=false",
            "X-GNOME-Autostart-enabled=true",
            "Categories=Network;Office;",
            "",
        ]
    )


def _launch_agent_plist() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.neuronection.career-assistant</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable or "python3"}</string>
    <string>-m</string><string>careerassistant</string>
    <string>app</string><string>--tray</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
"""
