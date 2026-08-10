from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest
import respx
from httpx import ASGITransport
from starlette.applications import Starlette

from cloudflare_dyndns.app import create_app
from cloudflare_dyndns.config import Settings

CF_BASE_URL = "https://api.cloudflare.com/client/v4"


def envelope(
    result: list[object] | object, *, page: int = 1, per_page: int = 20
) -> dict[str, object]:
    if isinstance(result, list):
        return {
            "result": result,
            "result_info": {
                "page": page,
                "per_page": per_page,
                "count": len(result),
                "total_count": len(result),
                "total_pages": 1,
            },
            "success": True,
            "errors": [],
            "messages": [],
        }
    return {"result": result, "success": True, "errors": [], "messages": []}


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    def _make(**overrides: object) -> Settings:
        defaults: dict[str, object] = {"rate_limit_enabled": False}
        defaults.update(overrides)
        return Settings(**defaults)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def settings(settings_factory: Callable[..., Settings]) -> Settings:
    return settings_factory()


@pytest.fixture
def app(settings: Settings) -> Starlette:
    return create_app(settings)


@pytest.fixture
async def client(app: Starlette) -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def cf_mock() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=CF_BASE_URL, assert_all_called=False) as mock:
        yield mock


TOKEN = "a" * 40
