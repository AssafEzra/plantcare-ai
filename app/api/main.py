"""FastAPI application.

Minimal at this stage: enough structure to serve authenticated routes with the
API_CONTRACTS envelopes. Rate limiting, readiness probes and the full router set
arrive with the API-structure PR; the error handling and request-id plumbing here
are already the versions those will build on.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import profile
from app.common.errors import AppError, NotFoundError, ValidationFailedError
from app.config.logging import configure_logging, get_logger
from app.config.settings import get_settings

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(environment=settings.app_env, debug=settings.app_debug)
    log.info("api.startup", environment=settings.app_env, debug=settings.app_debug)
    yield
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

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        response.headers["X-Request-ID"] = request_id
        return response

    def _envelope(request: Request, error: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=error.http_status,
            content=error.to_envelope(request_id),
            headers={"X-Request-ID": request_id},
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
        return {"status": "ok"}

    app.include_router(profile.router, prefix="/v1")
    return app


app = create_app()
