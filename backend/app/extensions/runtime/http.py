"""The connector transport runtime (plan 32 Phase 1): the polite
HttpTransport injected into every connector fetch.

Everything network-shaped about posting sources funnels through here —
the vendored family runtime (:mod:`app.extensions.polite_http`)
configured from ``CAREER_*`` Settings escape hatches (never raw
os.environ): the SSRF guard (resolve-then-connect pinning, reserved
ranges, every address checked, re-validated on EVERY redirect hop),
robots.txt (fail-closed on 5xx), per-host token buckets sized by each
connector's declared cap, conditional GET and response size caps. This
closes the 2026-09-11 security audit's connector-URL SSRF finding and
makes the documented politeness real.

Product knobs (Settings; all fail closed): ``connector_allowed_hosts``
(bypass the private-range check for trusted self-hosted boards),
``connector_allow_private_hosts`` + ``connector_block_private_ranges``
(wholesale hatches, default off/on), ``connector_pin_addresses``
(default on — DNS-rebind TOCTOU pinning), ``connector_respect_robots``
(default on), ``connector_requests_per_minute`` (global ceiling; the
connector's declared cap wins when lower), ``connector_max_response_mb``,
``connector_read_timeout_seconds``, ``connector_max_retries``.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.extensions import polite_http
from app.extensions.sdk import HttpTransport

_robots: polite_http.RobotsCache | None = None
_limiters: dict[int, polite_http.HostRateLimiter] = {}
_client: httpx.AsyncClient | None = None


def _http_client() -> httpx.AsyncClient:
    """One shared no-auto-redirect client (the runtime walks redirects
    itself so every hop is re-guarded)."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(settings.connector_read_timeout_seconds, connect=5.0),
        )
    return _client


def connector_client() -> httpx.AsyncClient:
    """The shared no-auto-redirect client (public seam for wrappers such as
    the T2 secret-scoped hop guard, which decorates the same instance)."""
    return _http_client()


async def close_connector_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _base_config() -> polite_http.PoliteHttpConfig:
    return polite_http.PoliteHttpConfig(
        guard=polite_http.NetGuardConfig(
            allowed_hosts=frozenset(h.lower() for h in settings.connector_allowed_hosts),
            allow_private=settings.connector_allow_private_hosts,
            block_private_ranges=settings.connector_block_private_ranges,
        ),
        requests_per_minute=settings.connector_requests_per_minute,
        max_response_bytes=settings.connector_max_response_mb * 1024 * 1024,
        max_retries=settings.connector_max_retries,
        respect_robots=settings.connector_respect_robots,
        pin_resolved_address=settings.connector_pin_addresses,
    )


def _rate_limiter(requests_per_minute: int) -> polite_http.HostRateLimiter:
    import time

    limiter = _limiters.get(requests_per_minute)
    if limiter is None:
        limiter = polite_http.HostRateLimiter(
            requests_per_minute=requests_per_minute, clock=time.monotonic
        )
        _limiters[requests_per_minute] = limiter
    return limiter


def reset_runtime() -> None:
    """Test hook: drop shared caches (robots, limiters, client)."""
    global _robots, _client
    _robots = None
    _limiters.clear()
    _client = None


def build_transport(
    *,
    domains: frozenset[str] | None = None,
    requests_per_minute: int | None = None,
    client: httpx.AsyncClient | None = None,
    config: polite_http.PoliteHttpConfig | None = None,
    resolver: polite_http.Resolver | None = None,
    max_response_bytes: int | None = None,
) -> HttpTransport:
    """Build the polite HttpTransport for one connector.

    ``domains`` scopes every hop to the connector's declared network
    scopes (manifest ``domains`` — the charter ``net`` law); url-shaped
    connectors without static scopes pass None and rely on the SSRF guard
    alone. ``requests_per_minute`` takes the connector's declared cap
    when lower than the global ceiling. ``max_response_bytes`` tightens
    the response cap below the global ceiling (the T2 seam's per-call
    ``maxBytes``). ``client`` and ``resolver`` are the test seams
    (``httpx.MockTransport`` + a fake resolver — no network in unit
    tests).
    """
    global _robots
    cfg = config or _base_config()
    rpm = min(int(requests_per_minute or cfg.requests_per_minute), cfg.requests_per_minute)
    rpm = max(1, rpm)
    if max_response_bytes is not None:
        max_response_bytes = max(1, int(max_response_bytes))
        if max_response_bytes < cfg.max_response_bytes:
            cfg = polite_http.PoliteHttpConfig(
                guard=cfg.guard,
                domains=cfg.domains,
                requests_per_minute=cfg.requests_per_minute,
                max_response_bytes=max_response_bytes,
                connect_timeout=cfg.connect_timeout,
                read_timeout=cfg.read_timeout,
                max_retries=cfg.max_retries,
                max_redirects=cfg.max_redirects,
                user_agent=cfg.user_agent,
                respect_robots=cfg.respect_robots,
                pin_resolved_address=cfg.pin_resolved_address,
            )
    if _robots is None:
        _robots = polite_http.RobotsCache()
    http = client or _http_client()
    limiter = _rate_limiter(rpm)
    scoped = polite_http.PoliteHttpConfig(
        guard=cfg.guard,
        domains=domains or frozenset(),
        requests_per_minute=rpm,
        max_response_bytes=cfg.max_response_bytes,
        connect_timeout=cfg.connect_timeout,
        read_timeout=cfg.read_timeout,
        max_retries=cfg.max_retries,
        max_redirects=cfg.max_redirects,
        user_agent=cfg.user_agent,
        respect_robots=cfg.respect_robots,
        pin_resolved_address=cfg.pin_resolved_address,
    )

    async def transport(url: str, headers: dict[str, str]) -> polite_http.PoliteResponse:
        return await polite_http.polite_get(
            url,
            client=http,
            config=scoped,
            headers=headers,
            resolver=resolver,
            rate=limiter,
            robots=_robots,
        )

    return transport
