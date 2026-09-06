"""FastAPI application.

Minimal at this stage: enough structure to serve authenticated routes with the
API_CONTRACTS envelopes. Rate limiting, readiness probes and the full router set
arrive with the API-structure PR; the error handling and request-id plumbing here
are already the versions those will build on.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import (
    admin,
    agent_requests,
    care,
    care_tasks,
    identification,
    knowledge,
    notifications,
    plant_detail,
    plant_images,
    plants,
    profile,
)
from app.api.routers import health as health_router
from app.common.errors import AppError, NotFoundError, ValidationFailedError
from app.config.logging import configure_logging, get_logger
from app.config.settings import get_settings
from app.infrastructure.supabase.client import anon_client

log = get_logger(__name__)


async def _tick_loop(interval_seconds: int) -> None:
    """Run the scheduler sweep forever, every `interval_seconds`.

    PR 24 plans a Railway cron service calling `POST /v1/internal/tick`, and until
    that ships nothing calls it at all: tasks are never materialised, nothing ever
    goes OVERDUE, no MISSED event is written and no reminder is sent. A deployment
    of the API alone should not be silently inert, so the API carries its own
    timer.

    The cron does not replace this so much as make it redundant: `run_tick` is
    idempotent, so a cron firing while this loop runs produces the same state as
    either alone. Setting `INTERNAL_TICK_INTERVAL_SECONDS=0` turns the timer off
    for a deployment that would rather have only the cron.

    Two things this must never do: block the event loop, and die. `run_tick` is
    synchronous Supabase I/O, so it goes to a worker thread; every exception is
    logged and swallowed, because a transient database error must not leave the
    process with no scheduler until someone restarts it.
    """
    from app.orchestration.services import tick

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            outcome = await asyncio.to_thread(tick.run_tick, now_utc=datetime.now(UTC))
            log.info("scheduler.timer_tick", **asdict(outcome))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("scheduler.timer_failed", error_type=type(exc).__name__, error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(environment=settings.app_env, debug=settings.app_debug)
    log.info("api.startup", environment=settings.app_env, debug=settings.app_debug)

    timer: asyncio.Task[None] | None = None
    interval = settings.internal_tick_interval_seconds
    if interval > 0:
        timer = asyncio.create_task(_tick_loop(interval))
        log.info("scheduler.timer_started", interval_seconds=interval)

    try:
        yield
    finally:
        if timer is not None:
            timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await timer
        log.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PlantCare AI",
        version="0.1.0",
        lifespan=lifespan,
        # The OpenAPI schema is useful in DEV and noise in PROD.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id

        # DEPLOYMENT §9 names duration among the fields worth logging. The path is
        # the route template rather than the raw URL, so ids do not end up in logs
        # and the lines stay aggregatable.
        route = request.scope.get("route")
        log.info(
            "request.complete",
            method=request.method,
            path=getattr(route, "path", request.url.path),
            status=response.status_code,
            duration=duration_ms,
        )
        return response

    def _envelope(request: Request, error: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        headers = {"X-Request-ID": request_id}

        # A 429 without Retry-After tells a client it was throttled but not for how
        # long, which invites an immediate retry and makes the problem worse.
        retry_after = error.details.get("retry_after_seconds")
        if error.http_status == 429 and retry_after:
            headers["Retry-After"] = str(retry_after)

        return JSONResponse(
            status_code=error.http_status,
            content=error.to_envelope(request_id),
            headers=headers,
        )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        log.info("request.error", code=exc.code, status=exc.http_status)
        return _envelope(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Field names and reasons are safe to return; input values are not echoed,
        # since a rejected body may contain something sensitive.
        fields = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "reason": err["msg"]}
            for err in exc.errors()
        ]
        return _envelope(request, ValidationFailedError(details={"fields": fields}))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _envelope(request, NotFoundError())
        return _envelope(
            request, AppError(str(exc.detail)) if exc.status_code >= 500 else NotFoundError()
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it: DEPLOYMENT §9 wants troubleshootable
        # logs and API_CONTRACTS wants safe error messages.
        log.exception("request.unhandled", error_type=type(exc).__name__)
        return _envelope(request, AppError())

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        """Liveness: is the process up? Deliberately checks nothing else.

        A liveness probe that touches the database restarts a healthy container
        during a database blip, which turns a partial outage into a total one.
        """
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        """Readiness: can this instance actually serve traffic?

        Runs a trivial query so a broken or unreachable database takes the
        instance out of rotation rather than letting it accept requests it cannot
        answer. Anonymous by design - it proves connectivity, not authorisation,
        and RLS means it reads nothing.
        """
        try:
            anon_client().table("species").select("id").limit(1).execute()
        except Exception as exc:
            log.warning("readiness.failed", error_type=type(exc).__name__)
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "checks": {"database": "failed"}},
            )
        return JSONResponse(status_code=200, content={"status": "ok", "checks": {"database": "ok"}})

    app.include_router(profile.router, prefix="/v1")
    app.include_router(plants.router, prefix="/v1")
    app.include_router(plant_detail.router, prefix="/v1")
    app.include_router(plant_images.router, prefix="/v1")
    app.include_router(agent_requests.router, prefix="/v1")
    app.include_router(identification.router, prefix="/v1")
    app.include_router(knowledge.router, prefix="/v1")
    app.include_router(admin.router, prefix="/v1")
    app.include_router(care.router, prefix="/v1")
    app.include_router(care_tasks.router, prefix="/v1")
    app.include_router(health_router.router, prefix="/v1")
    app.include_router(notifications.router, prefix="/v1")
    return app


app = create_app()
