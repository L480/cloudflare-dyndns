from __future__ import annotations

import io
import json
import logging

from cloudflare_dyndns.config import Settings
from cloudflare_dyndns.logging import configure_logging, redact

REALISTIC_TOKEN = "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789_-abcdefgh"  # noqa: S105


def test_redact_strips_token_query_param() -> None:
    text = f"GET /?token={REALISTIC_TOKEN}&zone=example.com HTTP/1.1"
    assert REALISTIC_TOKEN not in redact(text)


def test_redact_strips_authorization_header() -> None:
    text = f"Authorization: Bearer {REALISTIC_TOKEN}"
    assert REALISTIC_TOKEN not in redact(text)


def test_redact_strips_bare_token_like_string() -> None:
    text = f"upstream said: invalid credential {REALISTIC_TOKEN} rejected"
    assert REALISTIC_TOKEN not in redact(text)


def test_configured_logger_emits_no_token_substring() -> None:
    settings = Settings(log_format="json")
    configure_logging(settings)

    stream = io.StringIO()
    root = logging.getLogger()
    for handler in root.handlers:
        handler.stream = stream  # type: ignore[attr-defined]

    logger = logging.getLogger("cloudflare_dyndns.test")
    logger.info(
        "request failed url=%s auth=%s",
        f"https://dyndns.example/?token={REALISTIC_TOKEN}&zone=example.com",
        f"Authorization: Bearer {REALISTIC_TOKEN}",
    )

    output = stream.getvalue()
    assert REALISTIC_TOKEN not in output
    payload = json.loads(output)
    assert REALISTIC_TOKEN not in json.dumps(payload)
