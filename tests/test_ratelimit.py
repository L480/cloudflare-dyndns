from __future__ import annotations

from ipaddress import IPv4Network

from starlette.requests import Request

from cloudflare_dyndns.ratelimit import TokenBucketLimiter, resolve_client_ip


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_burst_allowance_then_denied() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(rate_per_minute=60, burst=3, clock=clock)
    assert [limiter.allow("1.2.3.4")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.allow("1.2.3.4")
    assert allowed is False
    assert retry_after > 0


def test_refill_over_time() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(rate_per_minute=60, burst=1, clock=clock)
    assert limiter.allow("1.2.3.4")[0] is True
    assert limiter.allow("1.2.3.4")[0] is False
    clock.advance(1.0)  # 1 token/sec at 60/min
    assert limiter.allow("1.2.3.4")[0] is True


def test_buckets_are_independent_per_key() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(rate_per_minute=60, burst=1, clock=clock)
    assert limiter.allow("1.1.1.1")[0] is True
    assert limiter.allow("2.2.2.2")[0] is True
    assert limiter.allow("1.1.1.1")[0] is False


def _make_request(peer: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    scope = {
        "type": "http",
        "client": (peer, 12345),
        "headers": headers,
        "method": "GET",
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


def test_untrusted_forwarded_for_is_ignored() -> None:
    request = _make_request("203.0.113.1", forwarded_for="9.9.9.9")
    ip = resolve_client_ip(request, trusted_proxies=[])
    assert ip == "203.0.113.1"


def test_trusted_forwarded_for_is_honoured() -> None:
    request = _make_request("10.0.0.5", forwarded_for="9.9.9.9, 10.0.0.5")
    ip = resolve_client_ip(request, trusted_proxies=[IPv4Network("10.0.0.0/8")])
    assert ip == "9.9.9.9"


def test_peer_outside_trusted_range_is_not_overridden() -> None:
    request = _make_request("203.0.113.1", forwarded_for="9.9.9.9")
    ip = resolve_client_ip(request, trusted_proxies=[IPv4Network("10.0.0.0/8")])
    assert ip == "203.0.113.1"


def test_middleware_returns_429_with_retry_after() -> None:
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from cloudflare_dyndns.config import Settings
    from cloudflare_dyndns.ratelimit import RateLimitMiddleware

    async def home(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", home)])
    settings = Settings(rate_limit_enabled=True, rate_limit_per_minute=60, rate_limit_burst=1)
    app.add_middleware(RateLimitMiddleware, settings=settings)

    with TestClient(app) as tc:
        first = tc.get("/")
        assert first.status_code == 200
        second = tc.get("/")
        assert second.status_code == 429
        assert "Retry-After" in second.headers
