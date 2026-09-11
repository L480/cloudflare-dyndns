from __future__ import annotations

import json

import httpx
import pytest
import respx

from cloudflare_dyndns.cloudflare_client import CloudflareClient
from cloudflare_dyndns.config import Settings
from cloudflare_dyndns.errors import RecordNotFoundError, ZoneNotAllowedError
from cloudflare_dyndns.models import build_update_query
from cloudflare_dyndns.service import perform_update
from tests.conftest import TOKEN, envelope

ZONE_ENV = envelope([{"id": "zone123", "name": "example.com"}])


def _a_record(fqdn: str, content: str = "1.2.3.4") -> dict[str, object]:
    return {
        "id": f"rec-{fqdn}-A",
        "name": fqdn,
        "type": "A",
        "content": content,
        "ttl": 1,
        "proxied": False,
    }


async def test_single_record_legacy_success(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([_a_record("www.example.com")]))
    )
    cf_mock.patch("/zones/zone123/dns_records/rec-www.example.com-A").mock(
        return_value=httpx.Response(200, json=envelope(_a_record("www.example.com", "5.6.7.8")))
    )
    settings = Settings(rate_limit_enabled=False)
    cf_client = CloudflareClient(settings)
    query = build_update_query(zone="example.com", record="www", ipv4="5.6.7.8", ipv6=None)

    response, status_code = await perform_update(query, TOKEN, settings, cf_client)

    assert status_code == 200
    assert response.status == "success"
    assert response.results[0].action == "updated"


async def test_single_record_missing_aaaa_writes_nothing(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))

    def dns_records_side_effect(request: httpx.Request) -> httpx.Response:
        if "type=A" in str(request.url) and "AAAA" not in str(request.url):
            return httpx.Response(200, json=envelope([_a_record("www.example.com")]))
        return httpx.Response(200, json=envelope([]))

    dns_route = cf_mock.get("/zones/zone123/dns_records").mock(side_effect=dns_records_side_effect)
    patch_route = cf_mock.patch(url__regex=r".*/dns_records/.*").mock(
        return_value=httpx.Response(200, json=envelope(_a_record("www.example.com")))
    )

    settings = Settings(rate_limit_enabled=False)
    cf_client = CloudflareClient(settings)
    query = build_update_query(zone="example.com", record="www", ipv4="5.6.7.8", ipv6="2001:db8::1")

    with pytest.raises(RecordNotFoundError) as exc_info:
        await perform_update(query, TOKEN, settings, cf_client)

    assert exc_info.value.message == "AAAA record for www.example.com does not exist."
    assert dns_route.call_count == 2
    assert patch_route.call_count == 0


async def test_multi_record_all_success(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))

    def dns_records_side_effect(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("name.exact") == "www.example.com":
            return httpx.Response(200, json=envelope([_a_record("www.example.com")]))
        return httpx.Response(200, json=envelope([_a_record("vpn.example.com")]))

    cf_mock.get("/zones/zone123/dns_records").mock(side_effect=dns_records_side_effect)
    cf_mock.patch(url__regex=r".*/dns_records/.*").mock(
        return_value=httpx.Response(200, json=envelope(_a_record("www.example.com", "5.6.7.8")))
    )

    settings = Settings(rate_limit_enabled=False)
    cf_client = CloudflareClient(settings)
    query = build_update_query(zone="example.com", record="www,vpn", ipv4="5.6.7.8", ipv6=None)

    response, status_code = await perform_update(query, TOKEN, settings, cf_client)

    assert status_code == 200
    assert response.status == "success"
    assert len(response.results) == 2


async def test_multi_record_partial_failure_returns_207(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))

    def dns_records_side_effect(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("name.exact") == "www.example.com":
            return httpx.Response(200, json=envelope([_a_record("www.example.com")]))
        return httpx.Response(200, json=envelope([]))  # vpn record missing

    cf_mock.get("/zones/zone123/dns_records").mock(side_effect=dns_records_side_effect)
    cf_mock.patch(url__regex=r".*/dns_records/.*").mock(
        return_value=httpx.Response(200, json=envelope(_a_record("www.example.com", "5.6.7.8")))
    )

    settings = Settings(rate_limit_enabled=False)
    cf_client = CloudflareClient(settings)
    query = build_update_query(zone="example.com", record="www,vpn", ipv4="5.6.7.8", ipv6=None)

    response, status_code = await perform_update(query, TOKEN, settings, cf_client)

    assert status_code == 207
    assert response.status == "partial"
    actions = {r.fqdn: r.action for r in response.results}
    assert actions["www.example.com"] == "updated"
    assert actions["vpn.example.com"] == "error"


async def test_allowlist_rejects_disallowed_zone(cf_mock: respx.MockRouter) -> None:
    settings = Settings(rate_limit_enabled=False, allowed_zones=["other.com"])
    cf_client = CloudflareClient(settings)
    query = build_update_query(zone="example.com", record="www", ipv4="1.2.3.4", ipv6=None)

    with pytest.raises(ZoneNotAllowedError) as exc_info:
        await perform_update(query, TOKEN, settings, cf_client)

    assert exc_info.value.message == "Zone example.com is not allowed on this instance."


async def test_ipv6_suffix_gives_each_record_its_own_aaaa(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    created: list[dict[str, object]] = []

    def create_side_effect(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = json.loads(request.content)
        created.append(body)
        record = {**body, "id": f"rec-{body['name']}-{body['type']}"}
        return httpx.Response(200, json=envelope(record))

    cf_mock.post("/zones/zone123/dns_records").mock(side_effect=create_side_effect)

    settings = Settings(rate_limit_enabled=False, create_missing_records=True)
    cf_client = CloudflareClient(settings)
    query = build_update_query(
        zone="example.com",
        record="fritz,host",
        ipv4="5.6.7.8",
        ipv6="2001:db8:1:2::1",
        ipv6prefix="2001:db8:1:2::/64",
        ipv6suffix=["host:9e6b:ff:fe50:179a"],
    )

    response, status_code = await perform_update(query, TOKEN, settings, cf_client)

    assert status_code == 200
    assert response.status == "success"
    assert {(b["name"], b["type"]): b["content"] for b in created} == {
        ("fritz.example.com", "A"): "5.6.7.8",
        ("fritz.example.com", "AAAA"): "2001:db8:1:2::1",
        ("host.example.com", "A"): "5.6.7.8",
        ("host.example.com", "AAAA"): "2001:db8:1:2:9e6b:ff:fe50:179a",
    }


async def test_ipv6_suffix_only_skips_records_without_an_address(
    cf_mock: respx.MockRouter,
) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=ZONE_ENV))
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    created: list[dict[str, object]] = []

    def create_side_effect(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = json.loads(request.content)
        created.append(body)
        return httpx.Response(200, json=envelope({**body, "id": "rec-new"}))

    cf_mock.post("/zones/zone123/dns_records").mock(side_effect=create_side_effect)

    settings = Settings(rate_limit_enabled=False, create_missing_records=True)
    cf_client = CloudflareClient(settings)
    query = build_update_query(
        zone="example.com",
        record="fritz,host",
        ipv4=None,
        ipv6=None,
        ipv6prefix="2001:db8:1:2::/64",
        ipv6suffix=["host:1"],
    )

    response, _ = await perform_update(query, TOKEN, settings, cf_client)

    assert [(r.fqdn, r.type, r.content) for r in response.results] == [
        ("host.example.com", "AAAA", "2001:db8:1:2::1")
    ]
    assert len(created) == 1
