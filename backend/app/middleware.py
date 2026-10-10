"""ASGI middleware for the career app (plan 20 Phase 4 split).

Rate limiting and security headers are the kit's (plan 21): one family
limiter (`nx_auth.ratelimit` — in-memory counter, frozen buckets) and
one `SecurityHeadersMiddleware` (`nx_auth.headers`) with career's
policy; career owns only the bucket routing, the Settings-backed
ceilings and the per-boot shell marker. The X-Profile-Id ownership
binding (identity-auth §15) and the SPA static fallback stay local.
`create_app` registers them in order — profile binding before the auth
kit so session enforcement stays outermost.
"""

import json
from typing import Any

from fastapi.staticfiles import StaticFiles
from nx_auth.headers import HeaderPolicy, SecurityHeadersMiddleware, desktop_csp, web_csp
from nx_auth.ratelimit import (
    InMemoryCounter,
    RateLimitPolicy,
    client_ip,
    mount_rate_limit,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.profile_context import (
    reset_active_profile,
    reset_active_user,
    set_active_profile,
    set_active_user,
)


def ratelimit_ceiling(bucket: str) -> int:
    """§16 ceiling for a family bucket, Settings-routed (D5): the
    `<P>_RATELIMIT_*` fields (requests/minute; 0 disables the bucket)
    resolve per request, so `.env` and OS env behave identically."""
    return int(getattr(settings, f"ratelimit_{bucket.lower()}"))


#: Career's mounted limiter state (plan 21): the in-memory counter is
#: the single-process topology this product ships as; the policy is the
#: app-wide singleton the gateway/MCP/tool throttles share with the
#: middleware (one counter, one degrade-open rule).
RATE_LIMIT_POLICY = RateLimitPolicy(
    ceiling=ratelimit_ceiling,
    enabled=lambda: settings.ratelimit_enabled,
    counter=InMemoryCounter(),
    trusted_proxy_count=settings.trusted_proxy_count,
)

#: Career's header policy (D4): the family CSP template — web strict,
#: desktop variant ONLY under the valid per-boot `?shell=` marker.
HEADER_POLICY = HeaderPolicy(web_csp=web_csp(), desktop_csp=desktop_csp())


def client_identity(scope: dict[str, Any]) -> str:
    """Client key for per-IP limits — trusted hops only (§7/§16).

    `CAREER_TRUSTED_PROXY_COUNT` (default 0) says how many rightmost
    `X-Forwarded-For` hops are believed; a client-supplied header is
    trusted only as far as the proxy chain is explicitly trusted — with
    0 no forwarded hop is used and the direct socket address keys the
    bucket (set 1 behind the bundled nginx/Caddy). Same semantics as
    the auth-kit's `nx_auth.ratelimit.client_ip`.
    """
    client = scope.get("client")
    headers = scope.get("headers") or []
    parsed = {k.decode().lower(): v.decode() for k, v in headers}
    return client_ip(
        client[0] if client else None,
        parsed.get("x-forwarded-for", ""),
        settings.trusted_proxy_count,
    )


#: Login-shaped endpoints ride the AUTH bucket (career's rule; the
#: kit's own auth limiters stay layered on top for the flows it owns).
_AUTH_BUCKET_SUFFIXES = ("/auth/login", "/auth/register", "/admin/instance", "/me/password")


def api_bucket_for(scope: dict[str, Any]) -> str | None:
    """Route an API request to its family bucket (None = untouched)."""
    path = scope.get("path", "")
    if not path.startswith("/api/"):
        return None
    if path.endswith(_AUTH_BUCKET_SUFFIXES):
        return "AUTH"
    return "DEFAULT"


def mount_rate_limiting(application) -> None:
    """Mount the kit limiter + security headers (plan 21 adoption)."""
    mount_rate_limit(application, policy=RATE_LIMIT_POLICY, bucket_for=api_bucket_for)
    application.add_middleware(
        SecurityHeadersMiddleware,
        policy=HEADER_POLICY,
        desktop_marker=_shell_marker,
    )


def _shell_marker(value: str | None) -> bool:
    """The per-boot `?shell=` token (desktop CSP variant gating only —
    the X-Shell-Token request gate is the kit's §11 middleware)."""
    from app.desktop.shell_token import matches

    return matches(value)


# Profile-independent surfaces (identity-auth §15) — they must work
# without `X-Profile-Id` so the SPA can always discover its profiles
# before scoping domain calls. Career's `/me/photo` and `/me/education`
# family lives under `/me` and rides the same exemption (the header
# still binds there when present).
PROFILE_BIND_EXEMPT_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/me",
    "/api/v1/profiles",
    "/api/v1/admin",
    "/api/v1/health",
    "/api/v1/instance",
    "/api/v1/shell",
)


def _profile_bind_exempt(path: str) -> bool:
    """Prefix match on path-segment boundaries — `/api/v1/me` must never
    swallow `/api/v1/metrics`."""
    # URL-addressable rendered images (`<img>`/`<link>` cannot send the
    # profile header): preview.png thumbnails are user-scoped GETs whose
    # handlers do their own ownership checks, so they skip the bind.
    if path.endswith("/preview.png"):
        return True
    for prefix in PROFILE_BIND_EXEMPT_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


async def _send_json_error(send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class ProfileBindingMiddleware:
    """X-Profile-Id ownership binding (identity-auth §15).

    Runs *inside* session enforcement (the verified `nx_principal` is in
    scope state — the auth-kit middleware was mounted later, so it wraps
    this one) and binds user + profile into contextvars:

    - server: absent header ⇒ 400; malformed, unknown, or unowned
      ⇒ 403 — no silent default in web mode;
    - desktop: absent header ⇒ the last-used profile (Default
      fallback) — the silent boot UX; an explicit header touches
      `last_used_at` (§6);
    - exempt prefixes (auth, `/me`, `/profiles`, `/admin`, health,
      docs, the render beacon) work without the header — they still
      bind when a valid header rides along.
    """

    def __init__(self, app, session_factory=None):
        self.app = app
        self.session_factory = session_factory

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        principal = scope.get("state", {}).get("nx_principal")
        user_id = principal.user_id if principal is not None else None
        raw = headers.get("x-profile-id")
        exempt = _profile_bind_exempt(path)
        profile_id = None
        factory = getattr(scope["app"].state, "profile_sessions", None) or (self.session_factory)
        if factory is None:
            from app.core.database import AsyncSessionLocal

            factory = AsyncSessionLocal
        async with factory() as session:
            if raw:
                profile = None
                if user_id is not None:
                    from app.services.profiles_service import get_owned_profile

                    profile = await get_owned_profile(session, user_id, raw)
                if profile is None:
                    if not exempt:
                        await _send_json_error(send, 403, "profile not allowed")
                        return
                else:
                    profile_id = str(profile.id)
            elif not exempt:
                if user_id is None:
                    await _send_json_error(send, 401, "Not authenticated")
                    return
                if str(settings.identity_mode) != "desktop":
                    await _send_json_error(send, 400, "X-Profile-Id required")
                    return
                from app.services.profiles_service import (
                    get_or_create_default,
                    last_used_profile,
                )

                profile = await last_used_profile(session, user_id) or None
                if profile is None:
                    profile = await get_or_create_default(session, user_id)
                profile_id = str(profile.id)
            if profile_id is not None and str(settings.identity_mode) == "desktop" and raw:
                from app.services.profiles_service import touch_last_used

                await touch_last_used(session, profile_id)
            await session.commit()
        user_token = set_active_user(user_id)
        profile_token = set_active_profile(profile_id)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_active_profile(profile_token)
            reset_active_user(user_token)


class SpaStaticFiles(StaticFiles):
    """StaticFiles that serves index.html for client-side SPA routes.

    Only paths without a file extension fall back to the app shell, so a
    genuinely missing asset (e.g. /assets/chunk.js) still 404s honestly.
    """

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
            response = await super().get_response("index.html", scope)
        return response
