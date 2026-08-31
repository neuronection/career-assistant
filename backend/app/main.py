import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router
from app.core.boot import validate_boot_config
from app.core.config import settings
from app.core.errors import (
    AINotConfiguredError,
    AccountLockedError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
)

logger = logging.getLogger(__name__)

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
# Desktop shell only: pywebview's evaluate_js (the plan-36 bridge push and
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
        if scope["type"] != "http" or not settings.RATE_LIMIT_ENABLED:
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


def _find_spa_dist() -> Path | None:
    """Locate the built SPA directory, or None to serve the API only.

    Resolution order: explicit SPA_DIST setting, frozen-bundle path
    (PyInstaller, Phase 11), then the repository checkout layout.
    """
    candidates = []
    if settings.SPA_DIST:
        candidates.append(Path(settings.SPA_DIST))
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidates.append(Path(bundled) / "frontend" / "dist")
    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "frontend" / "dist")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate boot config (production fails fast), then serve."""
    try:
        for warning in validate_boot_config():
            logger.warning("Boot config warning: %s", warning)
    except Exception as exc:  # noqa: BLE001 — boot must refuse loudly
        logger.critical("Refusing to boot: %s", exc)
        raise
    from app.services.job_worker import drain_queue, start_workers
    from app.services.scheduler.runner import start_scheduler

    workers = await start_workers(settings.JOBS_WORKERS)
    scheduler_task = await start_scheduler()
    try:
        yield
    finally:
        # Quit order (plan 30): stop scheduling first, then drain the queue
        # (bounded — force-kill recovery requeues strays per plan 12), then
        # stop the workers.
        if scheduler_task is not None:
            scheduler_task.cancel()
            await asyncio.gather(scheduler_task, return_exceptions=True)
        try:
            await asyncio.wait_for(
                drain_queue(), timeout=max(settings.JOBS_DRAIN_SECONDS, 1)
            )
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001 — best effort
            logger.warning("Queue drain incomplete at shutdown", exc_info=True)
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


def create_app() -> FastAPI:
    """Build the FastAPI application (API + optional SPA mount)."""
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)

    @application.exception_handler(AccountLockedError)
    async def account_locked_handler(request: Request, exc: AccountLockedError):
        """Brute-force lockout → 423 with generic-ish guidance."""
        return JSONResponse(status_code=423, content={"detail": str(exc)})

    @application.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        """Domain errors → 400 with message."""
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @application.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        """Missing entities → 404."""
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(PermissionDeniedError)
    async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
        """Ownership violations → 403."""
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @application.exception_handler(AINotConfiguredError)
    async def ai_not_configured_handler(request: Request, exc: AINotConfiguredError):
        """Mock/unconfigured AI in production → 503 (never serve fake results)."""
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    application.include_router(api_router)

    @application.get("/health")
    async def health() -> dict:
        """Liveness probe."""
        return {"status": "ok", "app": settings.APP_NAME, "version": settings.VERSION}

    @application.api_route(
        "/api/v1/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def api_fallback(rest: str) -> JSONResponse:
        """Keep unmatched API paths returning JSON 404s instead of the SPA shell."""
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    spa_dist = _find_spa_dist()
    if spa_dist is not None:
        application.mount(
            "/", SpaStaticFiles(directory=spa_dist, html=True), name="spa"
        )
        logger.info("Serving SPA from %s", spa_dist)
    else:
        logger.info("No SPA build found — serving API only")

    return application


app = create_app()
