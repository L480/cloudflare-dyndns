from __future__ import annotations

import httpx
import pytest
import respx

from cloudflare_dyndns.cloudflare_client import CloudflareClient
from cloudflare_dyndns.config import Settings
from cloudflare_dyndns.errors import (
    AuthenticationError,
    AuthorizationError,
    RateLimitedError,
    RecordNotFoundError,
    UpstreamTimeoutError,
    ZoneNotFoundError,
)
from tests.conftest import TOKEN, envelope

pytestmark = pytest.mark.usefixtures("cf_mock")

A_RECORD = {
    "id": "rec1",
    "name": "www.example.com",
    "type": "A",
    "content": "1.2.3.4",
    "ttl": 1,
    "proxied": False,
}


def _client() -> CloudflareClient:
    return CloudflareClient(Settings(rate_limit_enabled=False))


async def test_get_zone_id_found(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(
        return_value=httpx.Response(200, json=envelope([{"id": "zone123", "name": "example.com"}]))
    )
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        zone_id = await cf.get_zone_id(client, TOKEN, "example.com")
    assert zone_id == "zone123"


async def test_get_zone_id_not_found(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(return_value=httpx.Response(200, json=envelope([])))
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        with pytest.raises(ZoneNotFoundError) as exc_info:
            await cf.get_zone_id(client, TOKEN, "example.com")
    assert exc_info.value.message == "Zone example.com does not exist."


async def test_get_zone_id_cache_hit_issues_no_request(cf_mock: respx.MockRouter) -> None:
    route = cf_mock.get("/zones").mock(
        return_value=httpx.Response(200, json=envelope([{"id": "zone123", "name": "example.com"}]))
    )
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        await cf.get_zone_id(client, TOKEN, "example.com")
        await cf.get_zone_id(client, TOKEN, "example.com")
    assert route.call_count == 1


async def test_zone_cache_isolated_between_tokens(cf_mock: respx.MockRouter) -> None:
    route = cf_mock.get("/zones").mock(
        return_value=httpx.Response(200, json=envelope([{"id": "zone123", "name": "example.com"}]))
    )
    cf = _client()
    other_token = "b" * 40
    async with cf.client_for(TOKEN) as client:
        await cf.get_zone_id(client, TOKEN, "example.com")
    async with cf.client_for(other_token) as client:
        await cf.get_zone_id(client, other_token, "example.com")
    assert route.call_count == 2


async def test_get_record_found(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([A_RECORD]))
    )
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        record = await cf.get_record(client, TOKEN, "zone123", "www.example.com", "A")
    assert record is not None
    assert record.content == "1.2.3.4"


async def test_get_record_missing_returns_none(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([]))
    )
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        record = await cf.get_record(client, TOKEN, "zone123", "www.example.com", "A")
    assert record is None


async def test_get_record_cache_hit_issues_no_request(cf_mock: respx.MockRouter) -> None:
    route = cf_mock.get("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope([A_RECORD]))
    )
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        await cf.get_record(client, TOKEN, "zone123", "www.example.com", "A")
        await cf.get_record(client, TOKEN, "zone123", "www.example.com", "A")
    assert route.call_count == 1


async def test_upsert_unchanged_issues_no_patch(cf_mock: respx.MockRouter) -> None:
    patch_route = cf_mock.patch("/zones/zone123/dns_records/rec1").mock(
        return_value=httpx.Response(200, json=envelope(A_RECORD))
    )
    from cloudflare_dyndns.cloudflare_client import DnsRecord

    existing = DnsRecord(
        id="rec1", name="www.example.com", type="A", content="1.2.3.4", ttl=1, proxied=False
    )
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        result = await cf.upsert_record(
            client, TOKEN, "zone123", "www.example.com", "A", "1.2.3.4", existing
        )
    assert result.action == "unchanged"
    assert patch_route.call_count == 0


async def test_upsert_changed_issues_patch(cf_mock: respx.MockRouter) -> None:
    patch_route = cf_mock.patch("/zones/zone123/dns_records/rec1").mock(
        return_value=httpx.Response(200, json=envelope({**A_RECORD, "content": "5.6.7.8"}))
    )
    from cloudflare_dyndns.cloudflare_client import DnsRecord

    existing = DnsRecord(
        id="rec1", name="www.example.com", type="A", content="1.2.3.4", ttl=1, proxied=False
    )
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        result = await cf.upsert_record(
            client, TOKEN, "zone123", "www.example.com", "A", "5.6.7.8", existing
        )
    assert result.action == "updated"
    assert patch_route.call_count == 1


async def test_upsert_creates_when_enabled(cf_mock: respx.MockRouter) -> None:
    create_route = cf_mock.post("/zones/zone123/dns_records").mock(
        return_value=httpx.Response(200, json=envelope(A_RECORD))
    )
    cf = CloudflareClient(Settings(rate_limit_enabled=False, create_missing_records=True))
    async with cf.client_for(TOKEN) as client:
        result = await cf.upsert_record(
            client, TOKEN, "zone123", "www.example.com", "A", "1.2.3.4", None
        )
    assert result.action == "created"
    assert create_route.call_count == 1


async def test_upsert_missing_and_not_creating_raises(cf_mock: respx.MockRouter) -> None:
    cf = _client()
    async with cf.client_for(TOKEN) as client:
        with pytest.raises(RecordNotFoundError) as exc_info:
            await cf.upsert_record(
                client, TOKEN, "zone123", "www.example.com", "A", "1.2.3.4", None
            )
    assert exc_info.value.message == "A record for www.example.com does not exist."


@pytest.mark.parametrize(
    ("status_code", "expected_exception"),
    [
        (401, AuthenticationError),
        (403, AuthorizationError),
        (429, RateLimitedError),
    ],
)
async def test_error_mapping(
    cf_mock: respx.MockRouter, status_code: int, expected_exception: type[Exception]
) -> None:
    cf_mock.get("/zones").mock(
        return_value=httpx.Response(
            status_code,
            json={
                "success": False,
                "errors": [{"code": status_code, "message": "boom"}],
                "result": None,
            },
        )
    )
    cf = CloudflareClient(Settings(rate_limit_enabled=False, cf_max_retries=0))
    async with cf.client_for(TOKEN) as client:
        with pytest.raises(expected_exception):
            await cf.get_zone_id(client, TOKEN, "example.com")


async def test_timeout_maps_to_upstream_timeout(cf_mock: respx.MockRouter) -> None:
    cf_mock.get("/zones").mock(side_effect=httpx.ConnectTimeout("boom"))
    cf = CloudflareClient(Settings(rate_limit_enabled=False, cf_max_retries=0))
    async with cf.client_for(TOKEN) as client:
        with pytest.raises(UpstreamTimeoutError):
            await cf.get_zone_id(client, TOKEN, "example.com")
