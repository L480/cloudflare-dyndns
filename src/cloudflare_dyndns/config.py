from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "console"]


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CFDD_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8080
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"
    allowed_zones: list[str] = []
    create_missing_records: bool = False
    default_ttl: int = 1
    default_proxied: bool = False
    zone_cache_ttl: int = 300
    record_cache_ttl: int = 60
    cache_max_entries: int = 1024
    cf_timeout: float = 10.0
    cf_max_retries: int = 2
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 30
    rate_limit_burst: int = 10
    trusted_proxies: list[IPv4Network | IPv6Network] = []
    metrics_enabled: bool = False
    docs_enabled: bool = False

    @field_validator("allowed_zones", mode="before")
    @classmethod
    def _parse_allowed_zones(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("allowed_zones")
    @classmethod
    def _normalise_allowed_zones(cls, value: list[str]) -> list[str]:
        return [zone.strip().lower().rstrip(".") for zone in value]

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _parse_trusted_proxies(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("default_ttl")
    @classmethod
    def _validate_default_ttl(cls, value: int) -> int:
        if value != 1 and not (60 <= value <= 86400):
            raise ValueError("default_ttl must be 1 (automatic) or between 60 and 86400")
        return value

    @field_validator("port")
    @classmethod
    def _validate_port(cls, value: int) -> int:
        if not (1 <= value <= 65535):
            raise ValueError("port must be between 1 and 65535")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
