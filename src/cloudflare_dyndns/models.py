from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv6Address, IPv6Network
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


def _parse_ipv6_prefix(value: str) -> IPv6Network:
    """Parse an ``ipv6prefix`` value such as ``2001:db8:1:2::/64``.

    The FRITZ!Box ``<ip6lanprefix>`` placeholder expands to the LAN prefix
    with its length; a bare address without ``/len`` is treated as a /64.
    Host bits are masked off, so the suffix always ORs into a clean prefix.
    """
    try:
        return IPv6Network(value if "/" in value else f"{value}/64", strict=False)
    except ValueError as exc:
        raise InvalidParameterError("Invalid ipv6prefix URL parameter.") from exc


def _split_suffix_entries(raw: list[str]) -> list[tuple[str, str]]:
    """Split ``record:interface-id`` entries (comma-separated or repeated)."""
    entries: list[tuple[str, str]] = []
    for value in raw:
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            label, sep, iid = part.partition(":")
            if not sep or not iid:
                raise InvalidParameterError("Invalid ipv6suffix URL parameter.")
            entries.append((label, iid))
    return entries


def _parse_interface_id(iid: str, prefix: IPv6Network) -> IPv6Address:
    """Parse an interface ID like ``9e6b:ff:fe50:179a`` and combine it with ``prefix``."""
    try:
        suffix = IPv6Address(iid if iid.startswith("::") else f"::{iid}")
    except ValueError as exc:
        raise InvalidParameterError("Invalid ipv6suffix URL parameter.") from exc
    if int(suffix) & int(prefix.netmask):
        raise InvalidParameterError("Invalid ipv6suffix URL parameter.")
    return IPv6Address(int(prefix.network_address) | int(suffix))


def parse_ipv6_suffixes(
    prefix: str | None, suffixes: list[str] | None, zone: str
) -> dict[str | None, IPv6Address]:
    """Build the per-record AAAA overrides from ``ipv6prefix`` + ``ipv6suffix``.

    Returns a mapping of normalised record label -> full IPv6 address. Both
    parameters must be given together; an empty mapping means neither was.
    """
    entries = _split_suffix_entries(suffixes or [])
    if not prefix and not entries:
        return {}
    if not prefix:
        raise MissingParameterError("Missing ipv6prefix URL parameter.")
    if not entries:
        raise MissingParameterError("Missing ipv6suffix URL parameter.")

    network = _parse_ipv6_prefix(prefix)
    overrides: dict[str | None, IPv6Address] = {}
    for raw_label, iid in entries:
        label = normalise_record_labels(raw_label, zone)[0]
        if label in overrides:
            raise InvalidParameterError("Invalid ipv6suffix URL parameter.")
        overrides[label] = _parse_interface_id(iid, network)
    return overrides


@dataclass(frozen=True, slots=True)
class UpdateQuery:
    zone: str
    records: list[str | None]
    ipv4: IPv4Address | None
    ipv6: IPv6Address | None
    ipv6_overrides: dict[str | None, IPv6Address] = field(default_factory=dict)

    def ipv6_for(self, record: str | None) -> IPv6Address | None:
        """Return the AAAA content for ``record``: its prefix+suffix address, else ``ipv6``."""
        return self.ipv6_overrides.get(record, self.ipv6)


def build_update_query(
    *,
    zone: str | None,
    record: str | None,
    ipv4: str | None,
    ipv6: str | None,
    ipv6prefix: str | None = None,
    ipv6suffix: list[str] | None = None,
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
    overrides = parse_ipv6_suffixes(ipv6prefix, ipv6suffix, zone_normalised)

    if ipv4_addr is None and ipv6_addr is None and not overrides:
        raise MissingParameterError("Missing ipv4 or ipv6 URL parameter.")

    records = normalise_record_labels(record, zone_normalised)
    for label in overrides:
        if label not in records:
            name = fqdn(label, zone_normalised)
            raise InvalidParameterError(
                f"Record {name} in ipv6suffix is not in record URL parameter."
            )
    return UpdateQuery(
        zone=zone_normalised,
        records=records,
        ipv4=ipv4_addr,
        ipv6=ipv6_addr,
        ipv6_overrides=overrides,
    )


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
