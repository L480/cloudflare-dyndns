from __future__ import annotations

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
        url = str(request.url)
        if "www.example.com" in url:
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
        url = str(request.url)
        if "www.example.com" in url:
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
