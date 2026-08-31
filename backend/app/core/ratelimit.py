"""Dependency-free in-process rate limiting (sliding window).

Per-process counters, keyed `(bucket, identity)` — adequate for the
single-process self-host/desktop deployments this project ships as. For a
multi-replica deployment the counters would need to move to shared storage
(out of scope; documented in docs/deploy.md).
"""

import time
from collections import defaultdict, deque
from typing import Optional

from app.core.config import settings


class SlidingWindowRateLimiter:
    """Allows at most `limit` events per `window_seconds`, per key."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, bucket: str, identity: str) -> Optional[int]:
        """Record one event; return retry-after seconds when over the limit.

        Also returns the current bucket spec: (limit, window) resolved by
        the caller-provided bucket name via `limits_for`.
        """
        limit, window = self._limits(bucket)
        if limit <= 0:
            return None
        now = time.monotonic()
        key = (bucket, identity)
        events = self._events[key]
        cutoff = now - window
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= limit:
            retry_after = int(window - (now - events[0])) + 1
            self._prune(now)
            return max(retry_after, 1)
        events.append(now)
        if len(self._events) > 10_000:
            self._prune(now)
        return None

    def _limits(self, bucket: str) -> tuple[int, int]:
        table = {
            "auth": (settings.AUTH_RATE_LIMIT, 60),
            "auth_email": (settings.AUTH_RATE_LIMIT, 60),
            "ai": (settings.AI_RATE_LIMIT, 60),
            "default": (settings.DEFAULT_RATE_LIMIT, 60),
        }
        return table.get(bucket, table["default"])

    def _prune(self, now: float) -> None:
        # Drop buckets idle for > 1 hour to keep memory bounded.
        stale_before = now - 3600
        for key in [
            k for k, q in self._events.items() if not q or q[-1] < stale_before
        ]:
            del self._events[key]


limiter = SlidingWindowRateLimiter()


def client_identity(scope) -> str:
    """Best-effort client key: rightmost proxy-forwarded hop when present.

    Reverse proxies (Caddy, nginx) append the immediate client IP to
    X-Forwarded-For, so the last entry is the hop our own proxy observed;
    earlier entries are client-supplied and would allow identity rotation.
    Without the header the direct socket address is used.
    """
    client = scope.get("client")
    headers = scope.get("headers") or []
    parsed = {k.decode().lower(): v.decode() for k, v in headers}
    forwarded = parsed.get("x-forwarded-for", "")
    real_ip = forwarded.split(",")[-1].strip()
    if real_ip:
        return real_ip
    return client[0] if client else "unknown"
