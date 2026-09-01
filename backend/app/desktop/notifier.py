"""The `desktop` notification channel (plan 36 registry consumer).

Registered once by the desktop shell; the service runs the guardrails
(kind enabled, quiet hours, max/day) *before* calling `send`, so this
class only transports: pywebview bridge push with an OS fallback when no
live window can take it. Degrade, never crash, never drop below the
inbox.
"""

import logging
import shutil
import subprocess
from typing import Optional

from app.desktop.bridge import DesktopBridge
from app.models.enums import DeliveryStatus
from app.services.notification_channels import BaseChannel, DeliveryContext

logger = logging.getLogger(__name__)


class DesktopChannel(BaseChannel):
    """OS toasts through the pywebview bridge (in-process server)."""

    key = "desktop"

    def __init__(self, bridge: DesktopBridge):
        self._bridge = bridge

    def available(self) -> bool:
        return self._bridge is not None

    async def send(self, ctx: DeliveryContext) -> tuple[str, Optional[str]]:
        link = ctx.payload.get("link") if isinstance(ctx.payload, dict) else ""
        delivered = self._bridge.notify(
            title=ctx.title,
            body=ctx.body,
            kind=ctx.kind,
            severity=ctx.severity,
            link=str(link or ""),
        )
        if delivered:
            return DeliveryStatus.DELIVERED.value, None
        if _os_fallback(ctx.title, ctx.body):
            return DeliveryStatus.SENT.value, None
        return DeliveryStatus.FAILED.value, "no_window_or_os_fallback"


def _os_fallback(title: str, body: str) -> bool:
    """Last-resort OS toast when no webview window can take the push."""
    if shutil.which("notify-send") is None:
        return False
    try:
        subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["notify-send", "-a", "Career Assistant", title[:100], body[:200]],
            timeout=5,
            check=False,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        logger.warning("OS notification fallback failed", exc_info=True)
        return False


def register_desktop_channel(bridge: DesktopBridge) -> None:
    """Install the channel (shell startup only)."""
    from app.services.notification_channels import register_channel

    register_channel(DesktopChannel(bridge))
