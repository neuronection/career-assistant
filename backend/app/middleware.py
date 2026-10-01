"""ASGI middleware for the career app (plan 20 Phase 4 split).

Security headers (web/desktop CSP variants incl. the `?shell=` marker),
per-IP sliding-window rate limiting, the X-Profile-Id ownership binding
(identity-auth §15) and the SPA static fallback. `create_app` registers
them in order — profile binding before the auth kit so session
enforcement stays outermost.
"""

import json
from urllib.parse import parse_qs

from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.profile_context import (
    reset_active_profile,
    reset_active_user,
    set_active_profile,
    set_active_user,
)

_X_CONTENT_TYPE = ("x-content-type-options", "nosniff")
_X_FRAME = ("x-frame-options", "DENY")
_REFERRER = ("referrer-policy", "strict-origin-when-cross-origin")
_CSP_BODY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline';"
    " script-src {script}; connect-src 'self'; font-src 'self' data:; object-src 'none';"
    " frame-ancestors 'none'; base-uri 'self'"
)
# Web deployment: no eval, no inline scripts.
WEB_CSP = _CSP_BODY.format(script="'self'")
# Desktop shell only: pywebview's evaluate_js (the bridge push and
# the toast-activation focus) runs through the page JS context, and
# WebKitGTK/WebView2 apply the page CSP to it. Gated per request by the
# per-boot shell token (app.desktop.shell_token) — browsers never see it.
DESKTOP_CSP = _CSP_BODY.format(script="'self' 'unsafe-eval'")


class SecurityHeadersMiddleware:
    """Attach hardened response headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.desktop.shell_token import QUERY_PARAM, matches

        desktop_request = matches(
            parse_qs(scope.get("query_string", b"").decode("latin-1")).get(
                QUERY_PARAM, [None]
            )[0]
        )
        csp = DESKTOP_CSP if desktop_request else WEB_CSP
        headers = (
            _X_CONTENT_TYPE,
            _X_FRAME,
            _REFERRER,
            ("content-security-policy", csp),
        )

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in headers:
                    response_headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RateLimitMiddleware:
    """Per-IP sliding-window limits on the API (see app.core.ratelimit)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.ratelimit_enabled:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        from app.core.ratelimit import client_identity, limiter

        identity = client_identity(scope)
        bucket = (
            "auth" if path.endswith(("/auth/login", "/auth/register")) else "default"
        )
        retry_after = limiter.check(bucket, identity)
        if retry_after is not None:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


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
        factory = getattr(scope["app"].state, "profile_sessions", None) or (
            self.session_factory
        )
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
            if (
                profile_id is not None
                and str(settings.identity_mode) == "desktop"
                and raw
            ):
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


