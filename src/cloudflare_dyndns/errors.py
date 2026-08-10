from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

logger = logging.getLogger(__name__)


class DynDnsError(Exception):
    status_code: int = 500

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class MissingParameterError(DynDnsError):
    status_code = 400


class InvalidParameterError(DynDnsError):
    status_code = 400


class ZoneNotFoundError(DynDnsError):
    status_code = 404


class RecordNotFoundError(DynDnsError):
    status_code = 404


class ZoneNotAllowedError(DynDnsError):
    status_code = 403


class AuthenticationError(DynDnsError):
    status_code = 401


class AuthorizationError(DynDnsError):
    status_code = 403


class RateLimitedError(DynDnsError):
    status_code = 429


class UpstreamTimeoutError(DynDnsError):
    status_code = 504


class UpstreamError(DynDnsError):
    status_code = 500


_DYNDNS2_CODES: dict[type[DynDnsError], str] = {
    MissingParameterError: "notfqdn",
    InvalidParameterError: "notfqdn",
    ZoneNotFoundError: "nohost",
    RecordNotFoundError: "nohost",
    ZoneNotAllowedError: "!yours",
    AuthenticationError: "badauth",
    AuthorizationError: "!yours",
    RateLimitedError: "abuse",
    UpstreamTimeoutError: "911",
    UpstreamError: "911",
}


def _is_dyndns2_path(path: str) -> bool:
    return path.startswith("/nic/update")


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DynDnsError)
    async def handle_dyndns_error(request: Request, exc: DynDnsError) -> Response:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        if _is_dyndns2_path(request.url.path):
            code = _DYNDNS2_CODES.get(type(exc), "911")
            return PlainTextResponse(code, status_code=exc.status_code, headers=headers)
        return JSONResponse(
            {"status": "error", "message": exc.message},
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> Response:
        logger.exception("unhandled error while processing %s", request.url.path)
        if _is_dyndns2_path(request.url.path):
            return PlainTextResponse("911", status_code=500)
        return JSONResponse(
            {"status": "error", "message": "Internal server error."}, status_code=500
        )
