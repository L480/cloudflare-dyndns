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


PREFIX = "2001:db8:1:2::/64"


def test_build_update_query_ipv6_suffix_combines_prefix_and_interface_id() -> None:
    query = build_update_query(
        zone="example.com",
        record="fritz,host",
        ipv4="1.2.3.4",
        ipv6="2001:db8:1:2::1",
        ipv6prefix=PREFIX,
        ipv6suffix=["host:9e6b:ff:fe50:179a"],
    )
    assert str(query.ipv6_for("fritz")) == "2001:db8:1:2::1"
    assert str(query.ipv6_for("host")) == "2001:db8:1:2:9e6b:ff:fe50:179a"


@pytest.mark.parametrize(
    "prefix",
    ["2001:db8:1:2::/64", "2001:db8:1:2::", "2001:db8:1:2::abcd/64", "2001:db8:1:2:ffff::/64"],
)
def test_build_update_query_ipv6_prefix_forms(prefix: str) -> None:
    query = build_update_query(
        zone="example.com",
        record="host",
        ipv4=None,
        ipv6=None,
        ipv6prefix=prefix,
        ipv6suffix=["host:1"],
    )
    assert str(query.ipv6_for("host")) == "2001:db8:1:2::1"


def test_build_update_query_ipv6_prefix_shorter_than_64() -> None:
    query = build_update_query(
        zone="example.com",
        record="host",
        ipv4=None,
        ipv6=None,
        ipv6prefix="2001:db8:1::/56",
        ipv6suffix=["host:2:9e6b:ff:fe50:179a"],
    )
    assert str(query.ipv6_for("host")) == "2001:db8:1:2:9e6b:ff:fe50:179a"


def test_build_update_query_ipv6_suffix_leading_double_colon() -> None:
    query = build_update_query(
        zone="example.com",
        record="host",
        ipv4=None,
        ipv6=None,
        ipv6prefix=PREFIX,
        ipv6suffix=["host:::9e6b:ff:fe50:179a"],
    )
    assert str(query.ipv6_for("host")) == "2001:db8:1:2:9e6b:ff:fe50:179a"


def test_build_update_query_ipv6_suffix_repeated_and_comma_separated() -> None:
    query = build_update_query(
        zone="example.com",
        record="a,b,c",
        ipv4=None,
        ipv6=None,
        ipv6prefix=PREFIX,
        ipv6suffix=["a:1, b:2", "c:3"],
    )
    assert str(query.ipv6_for("a")) == "2001:db8:1:2::1"
    assert str(query.ipv6_for("b")) == "2001:db8:1:2::2"
    assert str(query.ipv6_for("c")) == "2001:db8:1:2::3"


def test_build_update_query_ipv6_suffix_for_apex() -> None:
    query = build_update_query(
        zone="example.com",
        record="@,www",
        ipv4=None,
        ipv6="2001:db8::1",
        ipv6prefix=PREFIX,
        ipv6suffix=["@:1"],
    )
    assert str(query.ipv6_for(None)) == "2001:db8:1:2::1"
    assert str(query.ipv6_for("www")) == "2001:db8::1"


def test_build_update_query_ipv6_suffix_without_ipv4_or_ipv6_is_enough() -> None:
    query = build_update_query(
        zone="example.com",
        record="host",
        ipv4=None,
        ipv6=None,
        ipv6prefix=PREFIX,
        ipv6suffix=["host:1"],
    )
    assert query.ipv4 is None
    assert query.ipv6 is None
    assert str(query.ipv6_for("host")) == "2001:db8:1:2::1"


def test_build_update_query_ipv6_prefix_without_suffix() -> None:
    with pytest.raises(MissingParameterError) as exc_info:
        build_update_query(
            zone="example.com", record="host", ipv4="1.2.3.4", ipv6=None, ipv6prefix=PREFIX
        )
    assert exc_info.value.message == "Missing ipv6suffix URL parameter."


def test_build_update_query_ipv6_suffix_without_prefix() -> None:
    with pytest.raises(MissingParameterError) as exc_info:
        build_update_query(
            zone="example.com", record="host", ipv4="1.2.3.4", ipv6=None, ipv6suffix=["host:1"]
        )
    assert exc_info.value.message == "Missing ipv6prefix URL parameter."


def test_build_update_query_empty_ipv6_prefix_and_suffix_is_noop() -> None:
    query = build_update_query(
        zone="example.com",
        record="host",
        ipv4="1.2.3.4",
        ipv6=None,
        ipv6prefix="",
        ipv6suffix=[""],
    )
    assert query.ipv6_overrides == {}
    assert query.ipv6_for("host") is None


@pytest.mark.parametrize("prefix", ["not-a-prefix", "1.2.3.0/24", "2001:db8::/129"])
def test_build_update_query_invalid_ipv6_prefix(prefix: str) -> None:
    with pytest.raises(InvalidParameterError) as exc_info:
        build_update_query(
            zone="example.com",
            record="host",
            ipv4=None,
            ipv6=None,
            ipv6prefix=prefix,
            ipv6suffix=["host:1"],
        )
    assert exc_info.value.message == "Invalid ipv6prefix URL parameter."


@pytest.mark.parametrize(
    "suffix",
    [
        "host",  # no interface ID
        "host:",  # empty interface ID
        "host:zz",  # not hex
        "host:1:2:3:4:5",  # more than 64 bits
        "host:2001:db8:1:2:9e6b:ff:fe50:179a",  # full address overlaps prefix bits
        "host:1,host:2",  # duplicate record
    ],
)
def test_build_update_query_invalid_ipv6_suffix(suffix: str) -> None:
    with pytest.raises(InvalidParameterError) as exc_info:
        build_update_query(
            zone="example.com",
            record="host",
            ipv4=None,
            ipv6=None,
            ipv6prefix=PREFIX,
            ipv6suffix=[suffix],
        )
    assert exc_info.value.message == "Invalid ipv6suffix URL parameter."


def test_build_update_query_ipv6_suffix_record_not_listed() -> None:
    with pytest.raises(InvalidParameterError) as exc_info:
        build_update_query(
            zone="example.com",
            record="fritz",
            ipv4=None,
            ipv6=None,
            ipv6prefix=PREFIX,
            ipv6suffix=["host:1"],
        )
    assert exc_info.value.message == (
        "Record host.example.com in ipv6suffix is not in record URL parameter."
    )
