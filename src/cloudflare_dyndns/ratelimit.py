from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import ASGIApp

from cloudflare_dyndns.config import Settings

Clock = Callable[[], float]


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    """Per-key token bucket. One instance is shared across all clients."""

    def __init__(self, rate_per_minute: int, burst: int, clock: Clock = time.monotonic) -> None:
        self._rate_per_second = rate_per_minute / 60.0
        self._burst = float(max(burst, 1))
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str) -> tuple[bool, float]:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._burst, last_refill=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.last_refill)
            bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate_per_second)
            bucket.last_refill = now

        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True, 0.0

        deficit = 1 - bucket.tokens
        retry_after = deficit / self._rate_per_second if self._rate_per_second > 0 else 60.0
        return False, retry_after


def resolve_client_ip(request: Request, trusted_proxies: list[IPv4Network | IPv6Network]) -> str:
    """Resolve the client IP, honouring X-Forwarded-For only from a trusted peer."""
    peer = request.client.host if request.client else "unknown"
    if not trusted_proxies or peer == "unknown":
        return peer

    try:
        peer_addr: IPv4Address | IPv6Address | None = ip_address(peer)
    except ValueError:
        peer_addr = None

    if peer_addr is None or not any(peer_addr in net for net in trusted_proxies):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    return forwarded.split(",")[0].strip()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        limiter: TokenBucketLimiter | None = None,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._limiter = limiter or TokenBucketLimiter(
            settings.rate_limit_per_minute, settings.rate_limit_burst
        )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self._settings.rate_limit_enabled:
            return await call_next(request)

        client_ip = resolve_client_ip(request, self._settings.trusted_proxies)
        allowed, retry_after = self._limiter.allow(client_ip)
        if allowed:
            return await call_next(request)

        headers = {
            "Retry-After": str(max(1, int(retry_after) + 1)),
            "X-RateLimit-Limit": str(self._settings.rate_limit_per_minute),
            "X-RateLimit-Remaining": "0",
        }
        if request.url.path.startswith("/nic/update"):
            return PlainTextResponse("abuse", status_code=429, headers=headers)
        return JSONResponse(
            {"status": "error", "message": "Too many requests."}, status_code=429, headers=headers
        )
