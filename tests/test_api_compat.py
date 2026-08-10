"""Guard rail for the live public instance.

This file pins the exact status codes and JSON bodies of the legacy ``GET /``
contract (see docs/api.md and plan.md section 2.1). A failure here is a
release blocker: real FRITZ!Box routers are pointed at the public instance
and depend on these responses staying byte-identical.
"""

from __future__ import annotations

import httpx
import respx
from httpx import AsyncClient

from tests.conftest import TOKEN, envelope

ZONE_ENV = envelope([{"id": "zone123", "name": "example.com"}])
A_RECORD = {
    "id": "rec1",
    "name": "www.example.com",
    "type": "A",
    "content": "1.2.3.4",
    "ttl": 1,
    "proxied": False,
}


async def test_success_response_shape(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([A_RECORD]))
    )
    cf_mock.patch("/zones/zone123/dns_records/rec1").mock(
        return_value=httpx.Response(200, json=envelope({**A_RECORD, "content": "5.6.7.8"}))
    )

    r = await client.get(
        "/", params={"token": TOKEN, "zone": "example.com", "record": "www", "ipv4": "5.6.7.8"}
    )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["message"] == "Update successful."


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


async def test_zone_not_found(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=envelope([])))
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv4": "1.2.3.4"})
    assert r.status_code == 404
    assert r.json() == {"status": "error", "message": "Zone example.com does not exist."}


async def test_a_record_missing_apex(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv4": "1.2.3.4"})
    assert r.status_code == 404
    assert r.json() == {"status": "error", "message": "A record for example.com does not exist."}


async def test_aaaa_record_missing_named(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    r = await client.get(
        "/", params={"token": TOKEN, "zone": "example.com", "record": "www", "ipv6": "2001:db8::1"}
    )
    assert r.status_code == 404
    assert r.json() == {
        "status": "error",
        "message": "AAAA record for www.example.com does not exist.",
    }


async def test_upstream_cloudflare_error_returns_500(
    client: AsyncClient, cf_mock: respx.MockRouter
) -> None:
    cf_mock.get("/zones").mock(
        return_value=httpx.Response(
            502,
            json={
                "success": False,
                "errors": [{"code": 502, "message": "bad gateway"}],
                "result": None,
            },
        )
    )
    r = await client.get("/", params={"token": TOKEN, "zone": "example.com", "ipv4": "1.2.3.4"})
    assert r.status_code == 500
    assert r.json()["status"] == "error"
    assert isinstance(r.json()["message"], str)


async def test_healthz_unchanged(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "success", "message": "OK"}


async def test_empty_record_means_apex(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    """record='' must mean the zone apex, not literally '.example.com' (issue A4)."""
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )

    r = await client.get(
        "/", params={"token": TOKEN, "zone": "example.com", "record": "", "ipv4": "1.2.3.4"}
    )

    assert r.status_code == 404
    assert r.json() == {"status": "error", "message": "A record for example.com does not exist."}


async def test_at_sign_record_means_apex(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    """record='@' must mean the zone apex (issue A5)."""
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )

    r = await client.get(
        "/", params={"token": TOKEN, "zone": "example.com", "record": "@", "ipv4": "1.2.3.4"}
    )

    assert r.status_code == 404
    assert r.json() == {"status": "error", "message": "A record for example.com does not exist."}
