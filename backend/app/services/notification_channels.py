"""Notification channel registry (plan 36).

Emit stays single-funnel (NotificationService.emit writes event + inbox
rows); this module is the *dispatch* seam, mirroring the connector
registry: built-ins auto-register, plugins arrive via the
`career_assistant.notification_channels` entry-point group and are
admin-opt-in through `NOTIFICATION_CHANNELS_ALLOWLIST`.

Guardrails (kind enabled, quiet hours, max/day) run centrally in the
service before `send`; channels only transport and report a
`(DeliveryStatus, error)` outcome. A broken channel must never break an
emit — the inbox row is authoritative.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import metadata
from typing import Optional
from datetime import datetime, timezone
from uuid import UUID

from app.models.enums import DeliveryStatus

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "career_assistant.notification_channels"


@dataclass
class DeliveryContext:
    """Everything a channel needs to transport one event to one user."""

    event_id: UUID
    user_id: UUID
    kind: str
    title: str
    body: str
    payload: dict = field(default_factory=dict)
    severity: str = "info"


class BaseChannel:
    """One transport. `available()` is mode/capability, never user state."""

    key: str = ""

    def available(self) -> bool:
        raise NotImplementedError

    async def send(self, ctx: DeliveryContext) -> tuple[str, Optional[str]]:
        """Deliver; returns (status, error). Never raises by contract."""
        raise NotImplementedError


class InAppChannel(BaseChannel):
    """The inbox itself — the recipient row is the delivered surface."""

    key = "in_app"

    def available(self) -> bool:
        return True

    async def send(self, ctx: DeliveryContext) -> tuple[str, Optional[str]]:
        return DeliveryStatus.DELIVERED.value, None


_BUILTINS_KEYS = ("in_app", "browser")

_registry: dict[str, BaseChannel] = {}
_plugins_loaded = False


def _ensure_builtins() -> None:
    """Built-ins register lazily (import-time cycle avoidance).

    `in_app` is always present; `browser` arrives with the webpush
    module when its transport is importable. The desktop shell registers
    its channel at boot (runtime, needs the bridge).
    """
    if "in_app" not in _registry:
        _registry["in_app"] = InAppChannel()
    if "browser" not in _registry:
        try:
            from app.services.webpush_service import BrowserPushChannel

            if BrowserPushChannel().available():
                _registry["browser"] = BrowserPushChannel()
        except ImportError:
            pass


def plugin_allowed(key: str) -> bool:
    from app.core.config import settings

    allowlist = getattr(settings, "NOTIFICATION_CHANNELS_ALLOWLIST", None) or []
    return key in allowlist


def _load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    _ensure_builtins()
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        return
    for ep in eps:
        try:
            channel = ep.load()()
        except Exception as exc:  # noqa: BLE001 — one bad plugin never breaks boot
            logger.warning("Notification channel %s failed to load: %s", ep.name, exc)
            continue
        if not isinstance(channel, BaseChannel):
            logger.warning("Notification channel %s is not a BaseChannel", ep.name)
            continue
        if not plugin_allowed(channel.key):
            logger.info(
                "Notification channel %s discovered but not allowlisted — skipping",
                channel.key,
            )
            continue
        _registry.setdefault(channel.key, channel)


def register_channel(channel: BaseChannel) -> None:
    """Runtime registration (desktop shell, tests)."""
    _registry[channel.key] = channel


def unregister_channel(key: str) -> None:
    if key in _BUILTINS_KEYS:
        return
    _registry.pop(key, None)


def get_channel(key: str) -> Optional[BaseChannel]:
    _load_plugins()
    return _registry.get(key)


def registered_channels() -> list[str]:
    _load_plugins()
    return list(_registry)


def available_channels() -> list[str]:
    """Channel capabilities declared by mode (plan 36 desktop scenario).

    One build, capabilities declared: the desktop shell registers its
    channel in-process at boot; web deployments carry the `browser`
    (VAPID) slot.
    """
    _load_plugins()
    return [key for key, channel in _registry.items() if channel.available()]


def within_quiet_hours(quiet: Optional[dict], now: Optional[datetime] = None) -> bool:
    """True when `now` (UTC) falls inside {start, end} HH:MM quiet hours.

    Overnight windows (start > end) wrap midnight. Per-rule pings (plan
    28) and the dispatch guards share this one implementation.
    """
    if not quiet:
        return False
    from datetime import datetime as dt

    moment = (now or dt.now(timezone.utc)).time()
    try:
        start = dt.strptime(quiet["start"], "%H:%M").time()
        end = dt.strptime(quiet["end"], "%H:%M").time()
    except (KeyError, TypeError, ValueError):
        return False
    if start <= end:
        return start <= moment <= end
    return moment >= start or moment <= end


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
