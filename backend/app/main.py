import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.boot import configure_logging, validate_boot_config
from app.auth.install import install_identity
from app.core.config import Settings, settings
from app.core.errors import (
    AINotConfiguredError,
    AccountLockedError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
)
from app.middleware import (
    ProfileBindingMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    SpaStaticFiles,
)

logger = logging.getLogger(__name__)


def _find_spa_dist() -> Path | None:
    """Locate the built SPA directory, or None to serve the API only.

    Resolution order: explicit SPA_DIST setting, frozen-bundle path
    (PyInstaller, Phase 11), then the repository checkout layout.
    """
    candidates = []
    if settings.spa_dist:
        candidates.append(Path(settings.spa_dist))
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidates.append(Path(bundled) / "frontend" / "dist")
    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "frontend" / "dist")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate boot config (production fails fast), then serve."""
    configure_logging()
    try:
        for warning in validate_boot_config():
            logger.warning("Boot config warning: %s", warning)
    except Exception as exc:  # noqa: BLE001 — boot must refuse loudly
        logger.critical("Refusing to boot: %s", exc)
        raise
    from app.services.job_worker import drain_queue, start_workers
    from app.services.scheduler.runner import start_scheduler

    # Warm VAPID keys before any dispatch can run: generating them lazily
    # inside a notification emit would write on a second connection while
    # the caller's transaction holds the SQLite write lock.
    from app.services.notification_channels import get_channel

    channel = get_channel("browser")
    if channel is not None and channel.available():
        from app.services.webpush_service import get_or_create_vapid_keys

        try:
            await get_or_create_vapid_keys()
        except Exception:  # noqa: BLE001 — push degrades fail-soft, boot must not hinge
            logger.warning(
                "VAPID key warm-up failed; browser push degraded", exc_info=True
            )

    # Warm the LangGraph checkpointer BEFORE any worker or request can run:
    # its first-run migration issues CREATE INDEX CONCURRENTLY, which waits
    # on every pre-existing transaction snapshot — running it lazily
    # mid-flight (a handler's own open session included) self-deadlocks.
    from app.ai.checkpointer import get_checkpointer, prune_desktop_checkpoints

    try:
        await get_checkpointer()
    except Exception:  # noqa: BLE001 — degrade fail-soft, boot must not hinge
        logger.warning(
            "Checkpointer warm-up failed; graph flows degraded", exc_info=True
        )
    # Retention beat (plan 98): desktop checkpoints grow unboundedly —
    # prune stale threads at boot (server-mode Postgres: Phase-4 trigger).
    pruned = prune_desktop_checkpoints()
    if pruned:
        logger.info("Checkpoint prune removed %d stale rows", pruned)

    workers = await start_workers(settings.jobs_workers)
    scheduler_task = await start_scheduler()
    try:
        yield
    finally:
        # Quit order: stop scheduling first, then drain the queue
        # (bounded — force-kill recovery requeues strays per), then
        # stop the workers.
        if scheduler_task is not None:
            scheduler_task.cancel()
            await asyncio.gather(scheduler_task, return_exceptions=True)
        try:
            await asyncio.wait_for(
                drain_queue(), timeout=max(settings.jobs_drain_seconds, 1)
            )
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001 — best effort
            logger.warning("Queue drain incomplete at shutdown", exc_info=True)
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        try:
            from app.services.cv_pdf_service import shutdown_engine

            await shutdown_engine()
        except Exception:  # noqa: BLE001 — best effort cleanup
            logger.warning("PDF engine shutdown failed", exc_info=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application (API + optional SPA mount).

    The build and the services read the module-global `settings`; the
    optional argument swaps that instance in for the whole build (the
    family DI seam, plan 20 D5). Entrypoints reuse the module-level `app`
    so each process constructs the application exactly once.
    """
    if settings is not None:
        globals()["settings"] = settings
    settings = globals()["settings"]
    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
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

    # §15 binding runs INSIDE session enforcement: the auth kit mounts
    # after this line, so its middleware wraps the binding one and the
    # verified `nx_principal` is in scope state when we read it (study's
    # ordering).
    application.add_middleware(ProfileBindingMiddleware)

    install_identity(application, settings)

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

    @application.exception_handler(ConflictError)
    async def conflict_error_handler(request: Request, exc: ConflictError):
        """Concurrent modification → 409."""
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(AINotConfiguredError)
    async def ai_not_configured_handler(request: Request, exc: AINotConfiguredError):
        """Mock/unconfigured AI in production → 503 (never serve fake results)."""
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    application.include_router(api_router)

    # MCP server: read-scope tools over Streamable HTTP,
    # token-authenticated and rate-limited — mounted, not routed.
    from app.ai.mcp_server import build_mcp_asgi_app

    application.mount("/mcp", build_mcp_asgi_app())

    @application.get("/health", tags=["health"])
    async def health() -> dict:
        """Liveness probe."""
        return {"status": "ok", "app": settings.app_name, "version": settings.version}

    shell_router = APIRouter(tags=["health"])

    @shell_router.post("/shell/rendered", status_code=204)
    async def shell_rendered(request: Request) -> None:
        """The web shell's WebKit-sentinel beacon: SPA finished rendering."""
        request.app.state.spa_rendered = True

    application.include_router(shell_router, prefix="/api/v1")

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
