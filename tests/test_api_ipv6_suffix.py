"""HTTP-level tests for the ``ipv6prefix`` / ``ipv6suffix`` legacy-endpoint parameters."""

from __future__ import annotations

import json

import httpx
import respx
from httpx import AsyncClient

from tests.conftest import TOKEN, envelope

ZONE_ENV = envelope([{"id": "zone123", "name": "example.com"}])


def _record(name: str, rtype: str, content: str) -> dict[str, object]:
    return {
        "id": f"rec-{name}-{rtype}",
        "name": name,
        "type": rtype,
        "content": content,
        "ttl": 1,
        "proxied": False,
    }


async def test_fritzbox_url_updates_box_and_host(
    client: AsyncClient, cf_mock: respx.MockRouter
) -> None:
    """One FRITZ!Box Update URL: A for both records, the box's AAAA, and the host's AAAA."""
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))

    def lookup(request: httpx.Request) -> httpx.Response:
        name = str(request.url.params.get("name.exact"))
        rtype = str(request.url.params.get("type"))
        return httpx.Response(200, json=envelope([_record(name, rtype, "old")]))

    cf_mock.get("/zones/zone123/dns_records").mock(side_effect=lookup)
    patched: dict[str, str] = {}

    def patch(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        patched[request.url.path.rsplit("/", 1)[-1]] = body["content"]
        return httpx.Response(200, json=envelope({**body, "id": "x", "ttl": 1, "proxied": False}))

    cf_mock.patch(url__regex=r".*/dns_records/.*").mock(side_effect=patch)

    r = await client.get(
        f"/?token={TOKEN}&zone=example.com&record=fritz,host"
        "&ipv4=203.0.113.7&ipv6=2001:db8:1:2::1"
        "&ipv6prefix=2001:db8:1:2::/64&ipv6suffix=host:9e6b:ff:fe50:179a"
    )

    assert r.status_code == 200
    assert r.json()["status"] == "success"
    assert patched == {
        "rec-fritz.example.com-A": "203.0.113.7",
        "rec-fritz.example.com-AAAA": "2001:db8:1:2::1",
        "rec-host.example.com-A": "203.0.113.7",
        "rec-host.example.com-AAAA": "2001:db8:1:2:9e6b:ff:fe50:179a",
    }


async def test_ipv6suffix_may_be_repeated(client: AsyncClient, cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))

    def lookup(request: httpx.Request) -> httpx.Response:
        name = str(request.url.params.get("name.exact"))
        return httpx.Response(200, json=envelope([_record(name, "AAAA", "old")]))

    cf_mock.get("/zones/zone123/dns_records").mock(side_effect=lookup)
    patched: dict[str, str] = {}

    def patch(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        patched[body["name"]] = body["content"]
        return httpx.Response(200, json=envelope({**body, "id": "x", "ttl": 1, "proxied": False}))

    cf_mock.patch(url__regex=r".*/dns_records/.*").mock(side_effect=patch)

    r = await client.get(
        "/",
        params=[
            ("token", TOKEN),
            ("zone", "example.com"),
            ("record", "nas,cam"),
            ("ipv6prefix", "2001:db8:1:2::/64"),
            ("ipv6suffix", "nas:1"),
            ("ipv6suffix", "cam:2"),
        ],
    )

    assert r.status_code == 200
    assert patched == {"nas.example.com": "2001:db8:1:2::1", "cam.example.com": "2001:db8:1:2::2"}


async def test_ipv6suffix_without_prefix_is_400(client: AsyncClient) -> None:
    r = await client.get(
        "/",
        params={"token": TOKEN, "zone": "example.com", "record": "host", "ipv6suffix": "host:1"},
    )
    assert r.status_code == 400
    assert r.json() == {"status": "error", "message": "Missing ipv6prefix URL parameter."}


async def test_invalid_ipv6suffix_is_400(client: AsyncClient) -> None:
    r = await client.get(
        "/",
        params={
            "token": TOKEN,
            "zone": "example.com",
            "record": "host",
            "ipv6prefix": "2001:db8:1:2::/64",
            "ipv6suffix": "host:not-hex",
        },
    )
    assert r.status_code == 400
    assert r.json() == {"status": "error", "message": "Invalid ipv6suffix URL parameter."}
