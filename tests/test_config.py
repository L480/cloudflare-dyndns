from __future__ import annotations

from ipaddress import IPv4Network

import pytest
from pydantic import ValidationError

from cloudflare_dyndns.config import Settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.host == "0.0.0.0"  # noqa: S104
    assert settings.port == 8080
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    assert settings.allowed_zones == []
    assert settings.create_missing_records is False
    assert settings.default_ttl == 1
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_per_minute == 30
    assert settings.rate_limit_burst == 10
    assert settings.trusted_proxies == []
    assert settings.metrics_enabled is False
    assert settings.docs_enabled is False


def test_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CFDD_PORT", "9090")
    monkeypatch.setenv("CFDD_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CFDD_CREATE_MISSING_RECORDS", "true")
    settings = Settings()
    assert settings.port == 9090
    assert settings.log_level == "DEBUG"
    assert settings.create_missing_records is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", ["example.com"]),
        ("Example.com.", ["example.com"]),
        ("a.com,b.com", ["a.com", "b.com"]),
        ("a.com, b.com", ["a.com", "b.com"]),
        ("", []),
    ],
)
def test_allowed_zones_comma_parsing(raw: str, expected: list[str]) -> None:
    settings = Settings(allowed_zones=raw)  # type: ignore[arg-type]
    assert settings.allowed_zones == expected


def test_trusted_proxies_comma_parsing() -> None:
    settings = Settings(trusted_proxies="10.0.0.0/8,192.168.0.0/16")  # type: ignore[arg-type]
    assert IPv4Network("10.0.0.0/8") in settings.trusted_proxies
    assert IPv4Network("192.168.0.0/16") in settings.trusted_proxies


@pytest.mark.parametrize("value", [0, 59, 86401, -1])
def test_default_ttl_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(default_ttl=value)


@pytest.mark.parametrize("value", [1, 60, 3600, 86400])
def test_default_ttl_accepts_valid_values(value: int) -> None:
    assert Settings(default_ttl=value).default_ttl == value


@pytest.mark.parametrize("value", [0, -1, 65536, 100000])
def test_port_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(port=value)


@pytest.mark.parametrize("value", [1, 80, 8080, 65535])
def test_port_accepts_valid_values(value: int) -> None:
    assert Settings(port=value).port == value
