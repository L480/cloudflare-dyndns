from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from cloudflare_dyndns.config import Settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_REDACTED = "***redacted***"
_TOKEN_PARAM_RE = re.compile(r"(token=)[^&\s]+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"(authorization[=:]\s*(?:bearer|basic)\s+)\S+", re.IGNORECASE)
_TOKEN_LIKE_RE = re.compile(r"\b[A-Za-z0-9_-]{30,}\b")


def redact(text: str) -> str:
    """Scrub anything token-shaped from a piece of text."""
    text = _TOKEN_PARAM_RE.sub(rf"\1{_REDACTED}", text)
    text = _AUTH_HEADER_RE.sub(rf"\1{_REDACTED}", text)
    text = _TOKEN_LIKE_RE.sub(_REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    """Scrub token-shaped values from log records before they are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.getMessage()))
        record.args = ()
        return True


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s")
        )
    handler.addFilter(RequestContextFilter())
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers.clear()
    uvicorn_access.propagate = False
    uvicorn_access.disabled = True

    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.handlers.clear()
    uvicorn_error.propagate = True
