from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import Literal

from pydantic import BaseModel, Field

from cloudflare_dyndns.errors import InvalidParameterError, MissingParameterError

RecordAction = Literal["updated", "unchanged", "created", "error"]
RecordType = Literal["A", "AAAA"]


def fqdn(record: str | None, zone: str) -> str:
    """Return the fully-qualified domain name for a normalised record label."""
    return zone if record is None else f"{record}.{zone}"


def normalise_record_labels(raw: str | None, zone: str) -> list[str | None]:
    """Split a raw ``record`` query value into normalised, de-duplicated labels.

    Each element is either a subdomain label (e.g. "www") or ``None`` for the
    zone apex. An empty string, missing value, "@", and a value equal to the
    zone all mean the apex.
    """
    if raw is None or raw == "":
        return [None]

    labels: list[str | None] = []
    for part in raw.split(","):
        label = part.strip()
        if label in ("", "@") or label.lower() == zone.lower():
            labels.append(None)
        else:
            labels.append(label)

    seen: set[str | None] = set()
    result: list[str | None] = []
    for normalised_label in labels:
        if normalised_label not in seen:
            seen.add(normalised_label)
            result.append(normalised_label)
    return result


def _parse_ipv4(value: str | None) -> IPv4Address | None:
    if value is None or value == "":
        return None
    try:
        return IPv4Address(value)
    except ValueError as exc:
        raise InvalidParameterError("Invalid ipv4 URL parameter.") from exc


def _parse_ipv6(value: str | None) -> IPv6Address | None:
    if value is None or value == "":
        return None
    try:
        return IPv6Address(value)
    except ValueError as exc:
        raise InvalidParameterError("Invalid ipv6 URL parameter.") from exc


@dataclass(frozen=True, slots=True)
class UpdateQuery:
    zone: str
    records: list[str | None]
    ipv4: IPv4Address | None
    ipv6: IPv6Address | None


def build_update_query(
    *, zone: str | None, record: str | None, ipv4: str | None, ipv6: str | None
) -> UpdateQuery:
    """Validate and normalise the legacy ``/`` query parameters.

    Checks fire in the legacy order (zone, then IPs) so error messages match
    the pre-refactor contract byte-for-byte.
    """
    if not zone:
        raise MissingParameterError("Missing zone URL parameter.")

    zone_normalised = zone.strip().lower().rstrip(".")
    ipv4_addr = _parse_ipv4(ipv4)
    ipv6_addr = _parse_ipv6(ipv6)

    if ipv4_addr is None and ipv6_addr is None:
        raise MissingParameterError("Missing ipv4 or ipv6 URL parameter.")

    records = normalise_record_labels(record, zone_normalised)
    return UpdateQuery(zone=zone_normalised, records=records, ipv4=ipv4_addr, ipv6=ipv6_addr)


class RecordResult(BaseModel):
    fqdn: str
    type: RecordType
    content: str
    action: RecordAction
    message: str | None = None


class UpdateResponse(BaseModel):
    status: Literal["success", "partial", "error"]
    message: str
    results: list[RecordResult] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["success"]
    message: str
