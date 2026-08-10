from __future__ import annotations

import pytest

from cloudflare_dyndns.errors import InvalidParameterError, MissingParameterError
from cloudflare_dyndns.models import build_update_query, fqdn, normalise_record_labels


@pytest.mark.parametrize(
    ("raw", "zone", "expected"),
    [
        (None, "example.com", [None]),
        ("", "example.com", [None]),
        ("@", "example.com", [None]),
        ("www", "example.com", ["www"]),
        ("a.b", "example.com", ["a.b"]),
        ("www,vpn", "example.com", ["www", "vpn"]),
        ("www, vpn", "example.com", ["www", "vpn"]),
        ("example.com", "example.com", [None]),
        ("EXAMPLE.COM", "example.com", [None]),
        ("www,www", "example.com", ["www"]),
    ],
)
def test_normalise_record_labels(raw: str | None, zone: str, expected: list[str | None]) -> None:
    assert normalise_record_labels(raw, zone) == expected


def test_fqdn_apex() -> None:
    assert fqdn(None, "example.com") == "example.com"


def test_fqdn_subdomain() -> None:
    assert fqdn("www", "example.com") == "www.example.com"


def test_build_update_query_missing_zone() -> None:
    with pytest.raises(MissingParameterError) as exc_info:
        build_update_query(zone=None, record=None, ipv4="1.2.3.4", ipv6=None)
    assert exc_info.value.message == "Missing zone URL parameter."


def test_build_update_query_missing_ips() -> None:
    with pytest.raises(MissingParameterError) as exc_info:
        build_update_query(zone="example.com", record=None, ipv4=None, ipv6=None)
    assert exc_info.value.message == "Missing ipv4 or ipv6 URL parameter."


def test_build_update_query_invalid_ipv4() -> None:
    with pytest.raises(InvalidParameterError) as exc_info:
        build_update_query(zone="example.com", record=None, ipv4="not-an-ip", ipv6=None)
    assert exc_info.value.message == "Invalid ipv4 URL parameter."


def test_build_update_query_invalid_ipv6() -> None:
    with pytest.raises(InvalidParameterError) as exc_info:
        build_update_query(zone="example.com", record=None, ipv4=None, ipv6="not-an-ip")
    assert exc_info.value.message == "Invalid ipv6 URL parameter."


def test_build_update_query_ipv6_literal_in_ipv4_field_rejected() -> None:
    with pytest.raises(InvalidParameterError):
        build_update_query(zone="example.com", record=None, ipv4="2001:db8::1", ipv6=None)


def test_build_update_query_normalises_zone() -> None:
    query = build_update_query(zone="Example.com.", record="www", ipv4="1.2.3.4", ipv6=None)
    assert query.zone == "example.com"
    assert query.records == ["www"]
    assert str(query.ipv4) == "1.2.3.4"
    assert query.ipv6 is None
