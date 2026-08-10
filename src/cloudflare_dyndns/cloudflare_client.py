from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar, cast

import cloudflare

from cloudflare_dyndns.config import Settings
from cloudflare_dyndns.errors import (
    AuthenticationError,
    AuthorizationError,
    DynDnsError,
    RateLimitedError,
    RecordNotFoundError,
    UpstreamError,
    UpstreamTimeoutError,
    ZoneNotFoundError,
)
from cloudflare_dyndns.logging import redact
from cloudflare_dyndns.models import RecordResult, RecordType

T = TypeVar("T")

_NOT_FOUND: Any = object()


@dataclass(frozen=True, slots=True)
class DnsRecord:
    id: str
    name: str
    type: RecordType
    content: str
    ttl: int
    proxied: bool | None


class _TTLCache(Generic[T]):
    """Small in-process TTL cache bounded by entry count, no external dependency."""

    def __init__(self, ttl_seconds: float, max_entries: int) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max(max_entries, 1)
        self._store: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | Any:
        entry = self._store.get(key)
        if entry is None:
            return _NOT_FOUND
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._store[key]
            return _NOT_FOUND
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: T) -> None:
        if self._ttl <= 0:
            return
        self._store[key] = (time.monotonic() + self._ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)


PageItem = TypeVar("PageItem")


class _PageLike(Protocol[PageItem]):
    result: list[PageItem]
    result_info: Any


async def _collect_all_pages(
    fetch_page: Callable[[int], Awaitable[_PageLike[PageItem]]],
) -> list[PageItem]:
    """Manually walk a V4 paginated list using ``result_info.total_pages``.

    The SDK's own async iterator instead keeps requesting pages until one
    comes back empty, which is one request too many for our exact-match
    lookups and pathological against handwritten test doubles. Reading
    ``total_pages`` from the envelope gets the same data in exactly the
    number of requests required.
    """
    items: list[PageItem] = []
    page_number = 1
    while True:
        page = await fetch_page(page_number)
        items.extend(page.result)
        total_pages = getattr(page.result_info, "total_pages", None) or 1
        if page_number >= total_pages:
            return items
        page_number += 1


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _extract_retry_after(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    header = response.headers.get("Retry-After")
    if header and header.isdigit():
        return int(header)
    return None


def _map_error(
    exc: Exception, *, fqdn: str | None = None, rtype: RecordType | None = None
) -> DynDnsError:
    if isinstance(exc, cloudflare.AuthenticationError):
        return AuthenticationError("Cloudflare authentication failed.")
    if isinstance(exc, cloudflare.PermissionDeniedError):
        return AuthorizationError("Cloudflare authorization failed.")
    if isinstance(exc, cloudflare.RateLimitError):
        return RateLimitedError(
            "Cloudflare rate limit exceeded.", retry_after=_extract_retry_after(exc)
        )
    if isinstance(exc, cloudflare.NotFoundError):
        if fqdn and rtype:
            return RecordNotFoundError(f"{rtype} record for {fqdn} does not exist.")
        return RecordNotFoundError("Record does not exist.")
    if isinstance(exc, cloudflare.APITimeoutError | cloudflare.APIConnectionError):
        return UpstreamTimeoutError("Cloudflare API unreachable.")
    return UpstreamError(redact(str(exc)))


def _to_dns_record(raw: object) -> DnsRecord:
    obj = cast(Any, raw)
    return DnsRecord(
        id=obj.id,
        name=obj.name,
        type=obj.type,
        content=obj.content or "",
        ttl=obj.ttl,
        proxied=obj.proxied,
    )


class CloudflareClient:
    """Async wrapper around the Cloudflare SDK with per-tenant caching.

    Cache keys always include a hash of the API token, never the token
    itself, so a cache shared across tenants cannot leak one tenant's
    zone/record ids to another.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._zone_cache: _TTLCache[str] = _TTLCache(
            settings.zone_cache_ttl, settings.cache_max_entries
        )
        self._record_cache: _TTLCache[DnsRecord | None] = _TTLCache(
            settings.record_cache_ttl, settings.cache_max_entries
        )

    def client_for(self, token: str) -> cloudflare.AsyncCloudflare:
        return cloudflare.AsyncCloudflare(
            api_token=token,
            timeout=self._settings.cf_timeout,
            max_retries=self._settings.cf_max_retries,
        )

    async def get_zone_id(self, client: cloudflare.AsyncCloudflare, token: str, zone: str) -> str:
        cache_key = f"{_token_key(token)}:{zone}"
        cached = self._zone_cache.get(cache_key)
        if cached is not _NOT_FOUND:
            return cast("str", cached)

        try:
            zones = await _collect_all_pages(
                lambda page_number: client.zones.list(name=zone, page=page_number)
            )
        except cloudflare.CloudflareError as exc:
            raise _map_error(exc) from exc

        if not zones:
            raise ZoneNotFoundError(f"Zone {zone} does not exist.")

        zone_id = zones[0].id
        self._zone_cache.set(cache_key, zone_id)
        return zone_id

    async def get_record(
        self,
        client: cloudflare.AsyncCloudflare,
        token: str,
        zone_id: str,
        fqdn: str,
        rtype: RecordType,
    ) -> DnsRecord | None:
        cache_key = f"{_token_key(token)}:{zone_id}:{fqdn}:{rtype}"
        cached = self._record_cache.get(cache_key)
        if cached is not _NOT_FOUND:
            return cast("DnsRecord | None", cached)

        try:
            records = await _collect_all_pages(
                lambda page_number: client.dns.records.list(
                    zone_id=zone_id, name={"exact": fqdn}, type=rtype, page=page_number
                )
            )
        except cloudflare.CloudflareError as exc:
            raise _map_error(exc, fqdn=fqdn, rtype=rtype) from exc

        record = _to_dns_record(records[0]) if records else None
        self._record_cache.set(cache_key, record)
        return record

    def invalidate_record(self, token: str, zone_id: str, fqdn: str, rtype: RecordType) -> None:
        self._record_cache.invalidate(f"{_token_key(token)}:{zone_id}:{fqdn}:{rtype}")

    async def upsert_record(
        self,
        client: cloudflare.AsyncCloudflare,
        token: str,
        zone_id: str,
        fqdn: str,
        rtype: RecordType,
        content: str,
        existing: DnsRecord | None,
    ) -> RecordResult:
        if existing is not None:
            if existing.content == content:
                return RecordResult(fqdn=fqdn, type=rtype, content=content, action="unchanged")

            proxied_arg: bool | cloudflare.Omit = (
                existing.proxied if existing.proxied is not None else cloudflare.Omit()
            )
            try:
                # dns.records.edit() is overloaded per literal `type`; branching
                # on rtype (rather than passing the RecordType variable straight
                # through) is what lets mypy pick a concrete overload.
                if rtype == "A":
                    await client.dns.records.edit(
                        existing.id,
                        zone_id=zone_id,
                        name=existing.name,
                        ttl=existing.ttl,
                        type="A",
                        content=content,
                        proxied=proxied_arg,
                    )
                else:
                    await client.dns.records.edit(
                        existing.id,
                        zone_id=zone_id,
                        name=existing.name,
                        ttl=existing.ttl,
                        type="AAAA",
                        content=content,
                        proxied=proxied_arg,
                    )
            except cloudflare.CloudflareError as exc:
                raise _map_error(exc, fqdn=fqdn, rtype=rtype) from exc
            self.invalidate_record(token, zone_id, fqdn, rtype)
            return RecordResult(fqdn=fqdn, type=rtype, content=content, action="updated")

        if not self._settings.create_missing_records:
            raise RecordNotFoundError(f"{rtype} record for {fqdn} does not exist.")

        try:
            await client.dns.records.create(
                zone_id=zone_id,
                name=fqdn,
                ttl=self._settings.default_ttl,
                type=rtype,
                content=content,
                proxied=self._settings.default_proxied,
            )
        except cloudflare.CloudflareError as exc:
            raise _map_error(exc, fqdn=fqdn, rtype=rtype) from exc
        self.invalidate_record(token, zone_id, fqdn, rtype)
        return RecordResult(fqdn=fqdn, type=rtype, content=content, action="created")

    async def find_zone_for_hostname(
        self, client: cloudflare.AsyncCloudflare, hostname: str
    ) -> tuple[str, str] | None:
        """Return ``(zone_id, zone_name)`` for the longest zone the token can see
        that is a suffix of ``hostname``, or ``None`` if none matches."""
        try:
            zones = await _collect_all_pages(
                lambda page_number: client.zones.list(page=page_number)
            )
        except cloudflare.CloudflareError as exc:
            raise _map_error(exc) from exc

        hostname_lower = hostname.lower().rstrip(".")
        best: tuple[str, str] | None = None
        for z in zones:
            name = z.name.lower()
            is_match = hostname_lower == name or hostname_lower.endswith("." + name)
            if is_match and (best is None or len(name) > len(best[1])):
                best = (z.id, name)
        return best
