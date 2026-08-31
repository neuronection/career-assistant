"""The `desktop` notification channel (plan 36's registry consumer).

Registered once by the desktop shell; every `EngagementService.emit`
offered here afterwards. Guards run at dispatch — the inbox always
receives the event:
- per-user channel preference (PUT /notifications/preferences),
- quiet hours (enforced server-side here, client-side in the SPA too),
then the toast is pushed via the pywebview bridge; with no live window
the OS fallback (notify-send on Linux) is attempted — degrade, never
crash, never drop below the inbox.
"""

import logging
import shutil
import subprocess
from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.desktop.bridge import DesktopBridge
from app.services.engagement_service import EngagementService
from app.services.notification_channels import register_dispatcher, within_quiet_hours

logger = logging.getLogger(__name__)


def register_desktop_channel(bridge: DesktopBridge) -> None:
    """Install the funnel dispatcher (shell startup only)."""

    async def _dispatch(
        user_id: UUID,
        kind: str,
        title: str,
        body: str,
        payload: dict,
        severity: str,
    ) -> None:
        prefs = await _load_preferences(user_id)
        if not prefs.get("desktop_channel_enabled", True):
            return
        if within_quiet_hours(prefs.get("quiet_hours")):
            return
        link = payload.get("link") if isinstance(payload, dict) else ""
        delivered = bridge.notify(
            title=title,
            body=body,
            kind=kind,
            severity=severity,
            link=str(link or ""),
        )
        if not delivered:
            _os_fallback(title, body)

    register_dispatcher(_dispatch)


async def _load_preferences(user_id: UUID) -> dict:
    """Fresh prefs per dispatch (own session; cheap single-row read)."""
    async with AsyncSessionLocal() as db:
        return await EngagementService(db).get_preferences(user_id)


def _os_fallback(title: str, body: str) -> None:
    """Last-resort OS toast when no webview window can take the push."""
    if shutil.which("notify-send") is None:
        return
    try:
        subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["notify-send", "-a", "Career Assistant", title[:100], body[:200]],
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("OS notification fallback failed", exc_info=True)
