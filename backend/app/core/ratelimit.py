"""Dependency-free in-process rate limiting (sliding window).

Per-process counters, keyed `(bucket, identity)` — adequate for the
single-process self-host/desktop deployments this project ships as. For a
multi-replica deployment the counters would need to move to shared storage
(out of scope; documented in docs/dev/deployment.md).
"""

import time
from collections import defaultdict, deque

from app.core.config import settings


class SlidingWindowRateLimiter:
    """Allows at most `limit` events per `window_seconds`, per key."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        """Drop all counters (tests isolate their rate-limit spend)."""
        self._events.clear()

    def check(self, bucket: str, identity: str) -> int | None:
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
            "auth": (settings.ratelimit_auth, 60),
            "auth_email": (settings.ratelimit_auth_email, 60),
            "ai": (settings.ratelimit_ai, 60),
            "mcp": (settings.ratelimit_mcp, 60),
            "default": (settings.ratelimit_default, 60),
        }
        return table.get(bucket, table["default"])

    def _prune(self, now: float) -> None:
        # Drop buckets idle for > 1 hour to keep memory bounded.
        stale_before = now - 3600
        for key in [k for k, q in self._events.items() if not q or q[-1] < stale_before]:
            del self._events[key]


limiter = SlidingWindowRateLimiter()


def client_identity(scope) -> str:
    """Client key for per-IP limits — trusted hops only (§7/§16).

    `CAREER_TRUSTED_PROXY_COUNT` (default 0) says how many rightmost
    `X-Forwarded-For` hops are believed; a client-supplied header is
    trusted only as far as the proxy chain is explicitly trusted — with
    0 no forwarded hop is used and the direct socket address keys the
    bucket (set 1 behind the bundled nginx/Caddy). Same semantics as the
    auth-kit's `nx_auth.ratelimit.client_ip`.
    """
    from nx_auth.ratelimit import client_ip

    client = scope.get("client")
    headers = scope.get("headers") or []
    parsed = {k.decode().lower(): v.decode() for k, v in headers}
    return client_ip(
        client[0] if client else None,
        parsed.get("x-forwarded-for", ""),
        settings.trusted_proxy_count,
    )
