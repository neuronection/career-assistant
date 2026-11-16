import asyncio
import contextlib
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.auth.install import install_identity
from app.core.boot import configure_logging, validate_boot_config
from app.core.config import Settings, settings
from app.core.errors import (
    AccountLockedError,
    AIBudgetExceededError,
    AINotConfiguredError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
)
from app.middleware import (
    ProfileBindingMiddleware,
    SpaStaticFiles,
    mount_rate_limiting,
)
from app.services.profile.document_storage import DocumentStorage
from app.storage.bootstrap import open_configured_store, register, resolve_storage_config
from app.storage.health import STATUS_DEGRADED, STATUS_UNAVAILABLE, StorageHealthProbe
from app.storage.object_storage import (
    InvalidObjectKey,
    ObjectNotFound,
    ObjectTooLarge,
    StorageAuthError,
    StorageConfigError,
    StorageError,
    StorageUnavailable,
    UnsupportedOperation,
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
    """Configure logging, then serve (boot guards run in create_app)."""
    configure_logging()
    # GitOps desired-state reconcile at boot (plan 32 Phase 3 / ADR-0040
    # D13) — best-effort, never fatal: reconcile installs and moves pins
    # only; a failed fetch leaves pins untouched.
    from app.extensions.lifecycle import reconcile_boot
    from app.services.job_worker import drain_queue, start_workers

    # Warm VAPID keys before any dispatch can run: generating them lazily
    # inside a notification emit would write on a second connection while
    # the caller's transaction holds the SQLite write lock.
    from app.services.notification_channels import get_channel
    from app.services.scheduler.runner import start_scheduler

    try:
        await reconcile_boot()
    except Exception:
        logger.warning("extension desired-state reconcile failed at boot", exc_info=True)

    channel = get_channel("browser")
    if channel is not None and channel.available():
        from app.services.webpush_service import get_or_create_vapid_keys

        try:
            await get_or_create_vapid_keys()
        except Exception:
            logger.warning("VAPID key warm-up failed; browser push degraded", exc_info=True)

    # Warm the LangGraph checkpointer BEFORE any worker or request can run:
    # its first-run migration issues CREATE INDEX CONCURRENTLY, which waits
    # on every pre-existing transaction snapshot — running it lazily
    # mid-flight (a handler's own open session included) self-deadlocks.
    from app.ai.checkpointer import get_checkpointer, prune_desktop_checkpoints

    try:
        await get_checkpointer()
    except Exception:
        logger.warning("Checkpointer warm-up failed; graph flows degraded", exc_info=True)
    # Retention beat (plan 98): desktop checkpoints grow unboundedly —
    # prune stale threads at boot (server-mode Postgres: Phase-4 trigger).
    pruned = prune_desktop_checkpoints()
    if pruned:
        logger.info("Checkpoint prune removed %d stale rows", pruned)

    workers = await start_workers(
        settings.jobs_workers,
        ingest_worker_count=settings.jobs_ingest_workers,
        vector_worker_count=settings.jobs_vector_workers,
    )
    scheduler_task = await start_scheduler()
    # Boot complete (readiness hard check, plan 64 §1.4): schedulers and
    # workers are running. `/ready` flips from 503 to 200 only after this.
    app.state.boot_complete = True
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
            await asyncio.wait_for(drain_queue(), timeout=max(settings.jobs_drain_seconds, 1))
        except (TimeoutError, Exception):
            logger.warning("Queue drain incomplete at shutdown", exc_info=True)
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        try:
            from app.services.cv.cv_pdf_service import shutdown_engine

            await shutdown_engine()
        except Exception:
            logger.warning("PDF engine shutdown failed", exc_info=True)
        try:
            from app.extensions.runtime.http import close_connector_client

            await close_connector_client()
        except Exception:
            logger.warning("Connector client shutdown failed", exc_info=True)
        try:
            from app.ai.tracing import sink as tracing_sink

            tracing_sink().shutdown()
        except Exception:
            logger.warning("Tracing shutdown failed", exc_info=True)
        try:
            app.state.objects.close()
        except Exception:
            logger.warning("Object-storage shutdown failed", exc_info=True)


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
    # Resolve (and fail) the storage configuration before anything serves:
    # a bad bucket/container, credential pair, TLS or cloud/local mismatch
    # is a boot error, never a first-upload error (ADR-0057).
    resolve_storage_config(settings)
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
    application.state.settings = settings
    storage_config, objects = open_configured_store(settings)
    register(storage_config, objects)
    application.state.storage_config = storage_config
    application.state.objects = objects
    application.state.storage_health = StorageHealthProbe(storage_config, objects)
    application.state.document_storage = DocumentStorage(objects)
    # Readiness gate (plan 64 §1.4): flipped True by the lifespan once
    # boot completed (workers + scheduler live). Until then `/ready`
    # answers 503 so a proxy never routes traffic into a half-booted app.
    application.state.boot_complete = False
    # Kit limiter + security headers (plan 21): same registration order
    # as the product-local middlewares they replaced — headers wrap the
    # limiter so a 429 still carries the hardened header set.
    mount_rate_limiting(application)

    # §15 binding runs INSIDE session enforcement: the auth kit mounts
    # after this line, so its middleware wraps the binding one and the
    # verified `nx_principal` is in scope state when we read it (study's
    # ordering).
    application.add_middleware(ProfileBindingMiddleware)

    # Production boot guards (ADR-0028): fail fast BEFORE the keyring is
    # built, so weak/partial pins die with BootConfigError's guidance
    # instead of a raw KeyRing ValueError at construction.
    try:
        for warning in validate_boot_config():
            logger.warning("Boot config warning: %s", warning)
    except Exception as exc:
        logger.critical("Refusing to boot: %s", exc)
        raise

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

    from app.services.retrieval_actions import RetrievalActionRefused

    @application.exception_handler(RetrievalActionRefused)
    async def retrieval_refusal_handler(request: Request, exc: RetrievalActionRefused):
        """A retrieval gate/state refusal carries its structured evidence."""
        return JSONResponse(status_code=409, content=exc.payload)

    @application.exception_handler(AIBudgetExceededError)
    async def ai_budget_handler(request: Request, exc: AIBudgetExceededError):
        """An exhausted AI token budget → 429, like the rate limiter."""
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @application.exception_handler(AINotConfiguredError)
    async def ai_not_configured_handler(request: Request, exc: AINotConfiguredError):
        """Mock/unconfigured AI in production → 503 (never serve fake results)."""
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    # Object-storage failures map onto the HTTP edge with contract classes
    # (ADR-0057 §6): a missing object is a 404, an oversized body a 413, a
    # backend that cannot perform the operation a 409, transient/provider
    # auth failures a 503, and configuration/programmer errors a 500.
    @application.exception_handler(ObjectTooLarge)
    async def object_too_large_handler(request: Request, exc: ObjectTooLarge):
        return JSONResponse(status_code=413, content={"detail": str(exc)})

    @application.exception_handler(ObjectNotFound)
    async def object_not_found_handler(request: Request, exc: ObjectNotFound):
        return JSONResponse(status_code=404, content={"detail": "Object not found"})

    @application.exception_handler(UnsupportedOperation)
    async def unsupported_operation_handler(request: Request, exc: UnsupportedOperation):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(StorageUnavailable)
    async def storage_unavailable_handler(request: Request, exc: StorageUnavailable):
        logger.warning("Object storage unavailable: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503, content={"detail": "Object storage is temporarily unavailable"}
        )

    @application.exception_handler(StorageAuthError)
    async def storage_auth_handler(request: Request, exc: StorageAuthError):
        logger.error("Object storage auth failure: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503, content={"detail": "Object storage credentials are unavailable"}
        )

    @application.exception_handler(StorageConfigError)
    async def storage_config_handler(request: Request, exc: StorageConfigError):
        logger.error("Object storage config failure: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Object storage is misconfigured"})

    @application.exception_handler(InvalidObjectKey)
    async def invalid_object_key_handler(request: Request, exc: InvalidObjectKey):
        logger.error("Object storage key failure: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Invalid object key"})

    @application.exception_handler(StorageError)
    async def storage_error_handler(request: Request, exc: StorageError):
        logger.warning("Object storage operation failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503, content={"detail": "Object storage is temporarily unavailable"}
        )

    from fastapi.exceptions import RequestValidationError

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        """422 with the field errors; the echoed input is dropped.

        The default handler serializes the offending input, which breaks the
        response for a non-JSON-compliant value (``Infinity``) and reflects
        user data back; keep the location, message and type only.
        """
        detail = [
            {key: value for key, value in error.items() if key in {"loc", "msg", "type"}}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    application.include_router(api_router)

    # MCP server: the registry projection over Streamable HTTP,
    # token-authenticated and rate-limited — mounted, not routed. The
    # inner app serves at its root (the mount strips `/mcp`), and its
    # lifespan owns the session manager's task group, so it is composed
    # into the app lifespan below.
    from app.ai.mcp_server import build_mcp_asgi_app

    mcp_asgi = build_mcp_asgi_app()

    class _McpSlashMiddleware:
        """Serve ``/mcp`` without Starlette's trailing-slash redirect."""

        def __init__(self, app) -> None:
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http" and scope.get("path") == "/mcp":
                scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
            await self.app(scope, receive, send)

    application.add_middleware(_McpSlashMiddleware)
    application.mount("/mcp", mcp_asgi)

    _base_lifespan = application.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _combined_lifespan(scope_app):
        async with mcp_asgi.lifespan(scope_app), _base_lifespan(scope_app):
            yield

    application.router.lifespan_context = _combined_lifespan

    @application.get("/health", tags=["health"])
    async def health(response: Response) -> dict:
        """Liveness probe: dependency states ride the payload.

        A transient storage-provider failure degrades open (200,
        ``storage.status: degraded``); the endpoint returns 503 only when
        object storage is required or the failure has been sustained.
        """
        storage = await anyio.to_thread.run_sync(application.state.storage_health.snapshot)
        if storage.failed:
            response.status_code = 503
            overall = "unhealthy"
        elif storage.status == STATUS_DEGRADED:
            overall = "degraded"
        else:
            overall = "ok"
        return {
            "status": overall,
            "app": settings.app_name,
            "version": settings.version,
            "storage": storage.payload(),
        }

    @application.get("/ready", tags=["health"])
    async def ready(request: Request, response: Response) -> dict:
        """Readiness probe (plan 64 §1.4): hard checks only, 503 otherwise.

        Hard: boot complete, the datastore is reachable **and at this
        release's Alembic head** (the one-shot migrate job finished), and
        required object storage is available. Soft signals — optional
        storage degradation, Redis, queue age — never flip readiness, so a
        degraded-but-serving instance stays ready while a half-migrated or
        still-booting one is pulled out of rotation.
        """
        checks: dict[str, str] = {}
        boot_complete = bool(getattr(request.app.state, "boot_complete", False))
        checks["boot"] = "complete" if boot_complete else "starting"

        from app.storage.readiness import database_at_head

        db_ready, db_detail = await anyio.to_thread.run_sync(database_at_head)
        checks["database"] = db_detail

        storage = await anyio.to_thread.run_sync(request.app.state.storage_health.snapshot)
        # Required storage is hard; optional/local storage degrades open.
        storage_ready = not (storage.required and storage.status == STATUS_UNAVAILABLE)
        checks["storage"] = storage.payload()["status"]

        ready = boot_complete and db_ready and storage_ready
        if not ready:
            response.status_code = 503
        return {"status": "ready" if ready else "not_ready", "checks": checks}

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
        application.mount("/", SpaStaticFiles(directory=spa_dist, html=True), name="spa")
        logger.info("Serving SPA from %s", spa_dist)
    else:
        logger.info("No SPA build found — serving API only")

    return application


app = create_app()
