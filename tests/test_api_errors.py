from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient

from tests.conftest import TOKEN, envelope

ZONE_ENV = envelope([{"id": "zone123", "name": "example.com"}])


async def test_missing_token(client: AsyncClient) -> None:
    r = await client.get("/", params={"zone": "example.com", "ipv4": "1.2.3.4"})
    assert r.status_code == 400
    assert r.json() == {"status": "error", "message": "Missing token URL parameter."}


async def test_missing_zone(client: AsyncClient) -> None:
    r = await client.get("/", params={"token": TOKEN, "ipv4": "1.2.3.4"})
    assert r.status_code == 400
    assert r.json() == {"status": "error", "message": "Missing zone URL parameter."}


async def test_missing_ips(client: AsyncClient) -> None:
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com"})
    assert r.status_code == 400
    assert r.json() == {"status": "error", "message": "Missing ipv4 or ipv6 URL parameter."}


async def test_invalid_ipv4(client: AsyncClient) -> None:
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv4": "nope"})
    assert r.status_code == 400
    assert r.json() == {"status": "error", "message": "Invalid ipv4 URL parameter."}


async def test_invalid_ipv6(client: AsyncClient) -> None:
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv6": "nope"})
    assert r.status_code == 400
    assert r.json() == {"status": "error", "message": "Invalid ipv6 URL parameter."}


async def test_zone_not_found(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=envelope([])))
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv4": "1.2.3.4"})
    assert r.status_code == 404
    assert r.json() == {"status": "error", "message": "Zone example.com does not exist."}


async def test_a_record_missing(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv4": "1.2.3.4"})
    assert r.status_code == 404
    assert r.json() == {
        "status": "error",
        "message": "A record for example.com does not exist.",
    }


async def test_aaaa_record_missing(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv6": "2001:db8::1"})
    assert r.status_code == 404
    assert r.json() == {
        "status": "error",
        "message": "AAAA record for example.com does not exist.",
    }


async def test_upstream_error_returns_500(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(
        return_value=httpx.Response(
            503,
            json={"success": False, "errors": [{"code": 503, "message": "down"}], "result": None},
        )
    )
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv4": "1.2.3.4"})
    assert r.status_code == 500
    assert r.json()["status"] == "error"


async def test_bad_token_returns_401(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(
        return_value=httpx.Response(
            401,
            json={"success": False, "errors": [{"code": 401, "message": "bad"}], "result": None},
        )
    )
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv4": "1.2.3.4"})
    assert r.status_code == 401
    assert r.json() == {"status": "error", "message": "Cloudflare authentication failed."}


async def test_zone_not_allowed_returns_403(app_settings_zone_allowlist: AsyncClient) -> None:
    r = await app_settings_zone_allowlist.get(
        "/", params={"token": TOKEN, "zone": "example.com", "ipv4": "1.2.3.4"}
    )
    assert r.status_code == 403
    assert r.json() == {
        "status": "error",
        "message": "Zone example.com is not allowed on this instance.",
    }


@pytest.fixture
async def app_settings_zone_allowlist(settings_factory):  # type: ignore[no-untyped-def]
    from httpx import ASGITransport

    from cloudflare_dyndns.app import create_app

    settings = settings_factory(allowed_zones=["other.com"])
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_healthz_body_unchanged(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "success", "message": "OK"}
