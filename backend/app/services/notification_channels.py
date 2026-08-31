"""Notification channel registry (Phase 30, groundwork for plan 36).

Emit stays single-funnel (EngagementService.emit writes the inbox row);
this module is the *dispatch* seam: process-level channel consumers
register here and every emitted notification is offered to them. Plan 36
replaces this with the full per-kind × per-channel registry + delivery
log — the funnel contract (emit → dispatch, guards at dispatch) carries
over unchanged.
"""

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

Dispatcher = Callable[[UUID, str, str, str, dict, str], Awaitable[None]]

_dispatcher: Optional[Dispatcher] = None


def register_dispatcher(fn: Dispatcher) -> None:
    """Register the process-level dispatch consumer (desktop shell only)."""
    global _dispatcher
    _dispatcher = fn


def unregister_dispatcher() -> None:
    """Drop the registered consumer (shell shutdown; web mode has none)."""
    global _dispatcher
    _dispatcher = None


def has_dispatcher() -> bool:
    return _dispatcher is not None


async def dispatch_notification(
    user_id: UUID,
    kind: str,
    title: str,
    body: str,
    payload: dict,
    severity: str,
) -> None:
    """Offer one emitted notification to the registered consumer.

    Fail-soft by contract: a broken channel must never break an emit.
    """
    if _dispatcher is None:
        return
    try:
        await _dispatcher(user_id, kind, title, body, payload, severity)
    except Exception:  # noqa: BLE001 — dispatch must never break emit
        logger.warning("Notification dispatch failed", exc_info=True)


def available_channels() -> list[str]:
    """Channel capabilities declared by mode (plan 36 desktop scenario).

    One build, capabilities declared: the desktop shell runs the server
    in-process, so `desktop` is available; web deployments declare the
    `browser` slot (VAPID arrives with plan 36).
    """
    from app.core.config import settings

    return ["in_app", "desktop"] if settings.DESKTOP_MODE else ["in_app", "browser"]


def within_quiet_hours(quiet: Optional[dict], now: Optional[datetime] = None) -> bool:
    """True when `now` (UTC) falls inside {start, end} HH:MM quiet hours.

    Overnight windows (start > end) wrap midnight. Shared by per-rule
    pings (plan 28) and desktop dispatch guards (plan 30).
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
