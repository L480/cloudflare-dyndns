from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cloudflare_dyndns.api import dyndns2_router, legacy_router
from cloudflare_dyndns.cloudflare_client import CloudflareClient
from cloudflare_dyndns.config import Settings, get_settings
from cloudflare_dyndns.errors import install_exception_handlers
from cloudflare_dyndns.logging import configure_logging, request_id_var
from cloudflare_dyndns.ratelimit import RateLimitMiddleware


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id")
        request_id = incoming if incoming else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.shutting_down = False
        yield
        app.state.shutting_down = True

    app = FastAPI(
        title="cloudflare-dyndns",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.cf_client = CloudflareClient(settings)

    # Starlette runs the most-recently-added middleware outermost, so adding
    # RequestIdMiddleware last makes the request id available to the rate
    # limiter and to every log line for the lifetime of the request.
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(RequestIdMiddleware)

    install_exception_handlers(app)

    app.include_router(legacy_router)
    app.include_router(dyndns2_router)

    if settings.metrics_enabled:
        _mount_metrics(app)

    return app


def _mount_metrics(app: FastAPI) -> None:
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())
