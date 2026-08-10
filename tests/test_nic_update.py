from __future__ import annotations

import base64

import httpx
import respx
from httpx import AsyncClient

from tests.conftest import TOKEN, envelope

ZONES_ENV = envelope([{"id": "zone123", "name": "example.com"}])
A_RECORD = {
    "id": "rec1",
    "name": "www.example.com",
    "type": "A",
    "content": "1.2.3.4",
    "ttl": 1,
    "proxied": False,
}


def _basic_auth_header(password: str) -> dict[str, str]:
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def test_nic_update_missing_auth_returns_badauth(client: AsyncClient) -> None:
    r = await client.get("/nic/update", params={"hostname": "www.example.com", "myip": "1.2.3.4"})
    assert r.status_code == 401
    assert r.text == "badauth"


async def test_nic_update_missing_hostname_returns_nohost(client: AsyncClient) -> None:
    r = await client.get(
        "/nic/update", params={"myip": "1.2.3.4"}, headers=_basic_auth_header(TOKEN)
    )
    assert r.status_code == 400
    assert r.text == "nohost"


async def test_nic_update_unknown_zone_returns_nohost(
    client: AsyncClient, cf_mock: respx.MockRouter
) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=envelope([])))
    r = await client.get(
        "/nic/update",
        params={"hostname": "www.example.com", "myip": "1.2.3.4"},
        headers=_basic_auth_header(TOKEN),
    )
    assert r.status_code == 200
    assert r.text == "nohost"


async def test_nic_update_good(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONES_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([A_RECORD]))
    )
    cf_mock.patch("/zones/zone123/dns_records/rec1").mock(
        return_value=httpx.Response(200, json=envelope({**A_RECORD, "content": "5.6.7.8"}))
    )
    r = await client.get(
        "/nic/update",
        params={"hostname": "www.example.com", "myip": "5.6.7.8"},
        headers=_basic_auth_header(TOKEN),
    )
    assert r.status_code == 200
    assert r.text == "good 5.6.7.8"


async def test_nic_update_nochg(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONES_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([A_RECORD]))
    )
    r = await client.get(
        "/nic/update",
        params={"hostname": "www.example.com", "myip": "1.2.3.4"},
        headers=_basic_auth_header(TOKEN),
    )
    assert r.status_code == 200
    assert r.text == "nochg 1.2.3.4"


async def test_nic_update_bearer_auth(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONES_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([A_RECORD]))
    )
    r = await client.get(
        "/nic/update",
        params={"hostname": "www.example.com", "myip": "1.2.3.4"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 200
    assert r.text == "nochg 1.2.3.4"


async def test_nic_update_multi_hostname(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONES_ENV))

    def dns_side_effect(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("name.exact") == "vpn.example.com":
            return httpx.Response(200, json=envelope([]))
        return httpx.Response(200, json=envelope([A_RECORD]))

    cf_mock.get("/zones/zone123/dns_records").mock(side_effect=dns_side_effect)

    r = await client.get(
        "/nic/update",
        params={"hostname": "www.example.com,vpn.example.com", "myip": "1.2.3.4"},
        headers=_basic_auth_header(TOKEN),
    )
    assert r.status_code == 200
    assert r.text == "nochg 1.2.3.4\nnohost"
