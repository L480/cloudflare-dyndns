from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

import cloudflare

from cloudflare_dyndns.cloudflare_client import CloudflareClient, DnsRecord
from cloudflare_dyndns.config import Settings
from cloudflare_dyndns.errors import DynDnsError, RecordNotFoundError, ZoneNotAllowedError
from cloudflare_dyndns.models import RecordResult, RecordType, UpdateQuery, UpdateResponse
from cloudflare_dyndns.models import fqdn as build_fqdn

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 5

WorkItem = tuple[str, RecordType, str]


async def perform_update(
    query: UpdateQuery, token: str, settings: Settings, cf_client: CloudflareClient
) -> tuple[UpdateResponse, int]:
    start = time.monotonic()
    zone = query.zone

    if settings.allowed_zones and zone not in settings.allowed_zones:
        raise ZoneNotAllowedError(f"Zone {zone} is not allowed on this instance.")

    families: list[RecordType] = []
    if query.ipv4 is not None:
        families.append("A")
    if query.ipv6 is not None:
        families.append("AAAA")

    work_items: list[WorkItem] = [
        (build_fqdn(record, zone), rtype, str(query.ipv4) if rtype == "A" else str(query.ipv6))
        for record in query.records
        for rtype in families
    ]

    async with cf_client.client_for(token) as client:
        zone_id = await cf_client.get_zone_id(client, token, zone)

        if len(query.records) == 1:
            results = await _run_legacy_single(
                cf_client, client, token, zone_id, work_items, settings
            )
            status: Literal["success", "partial"] = "success"
        else:
            results = await _run_concurrent(cf_client, client, token, zone_id, work_items)
            status = "partial" if any(r.action == "error" for r in results) else "success"

    duration_ms = round((time.monotonic() - start) * 1000, 2)
    logger.info(
        "dyndns update processed",
        extra={
            "extra_fields": {
                "zone": zone,
                "fqdns": sorted({r.fqdn for r in results}),
                "families": families,
                "actions": [r.action for r in results],
                "duration_ms": duration_ms,
                "status": status,
            }
        },
    )

    response = UpdateResponse(status=status, message="Update successful.", results=results)
    http_status = 200 if status == "success" else 207
    return response, http_status


async def _run_legacy_single(
    cf_client: CloudflareClient,
    client: cloudflare.AsyncCloudflare,
    token: str,
    zone_id: str,
    work_items: list[WorkItem],
    settings: Settings,
) -> list[RecordResult]:
    """Validate that every required record exists before writing any of them.

    This mirrors the pre-refactor behaviour: a request updating both A and
    AAAA for one hostname must not half-apply if only one type is missing.
    """
    existing: dict[tuple[str, RecordType], DnsRecord | None] = {}
    for record_fqdn, rtype, _content in work_items:
        record = await cf_client.get_record(client, token, zone_id, record_fqdn, rtype)
        if record is None and not settings.create_missing_records:
            raise RecordNotFoundError(f"{rtype} record for {record_fqdn} does not exist.")
        existing[(record_fqdn, rtype)] = record

    results: list[RecordResult] = []
    for record_fqdn, rtype, content in work_items:
        result = await cf_client.upsert_record(
            client,
            token,
            zone_id,
            record_fqdn,
            rtype,
            content,
            existing[(record_fqdn, rtype)],
        )
        results.append(result)
    return results


async def _run_concurrent(
    cf_client: CloudflareClient,
    client: cloudflare.AsyncCloudflare,
    token: str,
    zone_id: str,
    work_items: list[WorkItem],
) -> list[RecordResult]:
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _process(record_fqdn: str, rtype: RecordType, content: str) -> RecordResult:
        async with semaphore:
            try:
                existing = await cf_client.get_record(client, token, zone_id, record_fqdn, rtype)
                return await cf_client.upsert_record(
                    client, token, zone_id, record_fqdn, rtype, content, existing
                )
            except DynDnsError as exc:
                return RecordResult(
                    fqdn=record_fqdn,
                    type=rtype,
                    content=content,
                    action="error",
                    message=exc.message,
                )

    return list(await asyncio.gather(*(_process(f, t, c) for f, t, c in work_items)))
