from __future__ import annotations

import base64
import binascii

import cloudflare
from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, PlainTextResponse

from cloudflare_dyndns.cloudflare_client import CloudflareClient
from cloudflare_dyndns.config import Settings
from cloudflare_dyndns.errors import (
    AuthenticationError,
    AuthorizationError,
    DynDnsError,
    MissingParameterError,
)
from cloudflare_dyndns.models import HealthResponse, RecordType, build_update_query
from cloudflare_dyndns.service import perform_update

legacy_router = APIRouter()
dyndns2_router = APIRouter()


def resolve_token(request: Request, query_token: str | None) -> str | None:
    """Resolve the Cloudflare token: query param wins, then Bearer, then Basic auth password."""
    if query_token:
        return query_token

    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    value = value.strip()
    if not value:
        return None

    if scheme.lower() == "bearer":
        return value

    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(value).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
        _, _, password = decoded.partition(":")
        return password or None

    return None


def get_cf_client(request: Request) -> CloudflareClient:
    return request.app.state.cf_client  # type: ignore[no-any-return]


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


@legacy_router.get("/")
async def legacy_update(
    request: Request,
    token: str | None = None,
    zone: str | None = None,
    record: str | None = None,
    ipv4: str | None = None,
    ipv6: str | None = None,
    settings: Settings = Depends(get_app_settings),
    cf_client: CloudflareClient = Depends(get_cf_client),
) -> JSONResponse:
    resolved_token = resolve_token(request, token)
    if not resolved_token:
        raise MissingParameterError("Missing token URL parameter.")

    query = build_update_query(zone=zone, record=record, ipv4=ipv4, ipv6=ipv6)
    response, status_code = await perform_update(query, resolved_token, settings, cf_client)
    return JSONResponse(response.model_dump(exclude_none=True), status_code=status_code)


@legacy_router.get("/healthz")
async def healthz() -> HealthResponse:
    return HealthResponse(status="success", message="OK")


@legacy_router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    if getattr(request.app.state, "shutting_down", False):
        return JSONResponse({"status": "error", "message": "Shutting down."}, status_code=503)
    return JSONResponse({"status": "success", "message": "Ready."}, status_code=200)


@dyndns2_router.get("/nic/update")
async def nic_update(
    request: Request,
    hostname: str | None = None,
    myip: str | None = None,
    myipv6: str | None = None,
    settings: Settings = Depends(get_app_settings),
    cf_client: CloudflareClient = Depends(get_cf_client),
) -> PlainTextResponse:
    token = resolve_token(request, None)
    if not token:
        return PlainTextResponse("badauth", status_code=401)
    if not hostname:
        return PlainTextResponse("nohost", status_code=400)

    if not myip and not myipv6 and request.client:
        myip = request.client.host

    hosts = [h.strip() for h in hostname.split(",") if h.strip()]
    if not hosts:
        return PlainTextResponse("nohost", status_code=400)

    lines: list[str] = []
    async with cf_client.client_for(token) as client:
        for host in hosts:
            lines.append(
                await _update_one_host(cf_client, client, token, host, myip, myipv6, settings)
            )

    return PlainTextResponse("\n".join(lines), status_code=200)


async def _update_one_host(
    cf_client: CloudflareClient,
    client: cloudflare.AsyncCloudflare,
    token: str,
    host: str,
    myip: str | None,
    myipv6: str | None,
    settings: Settings,
) -> str:
    match = await cf_client.find_zone_for_hostname(client, host)
    if match is None:
        return "nohost"
    zone_id, _zone_name = match

    actions: list[tuple[str, str]] = []
    requested: list[tuple[RecordType, str | None]] = [("A", myip), ("AAAA", myipv6)]
    try:
        for rtype, content in requested:
            if not content:
                continue
            existing = await cf_client.get_record(client, token, zone_id, host, rtype)
            if existing is None and not settings.create_missing_records:
                return "nohost"
            result = await cf_client.upsert_record(
                client, token, zone_id, host, rtype, content, existing
            )
            actions.append((result.action, content))
    except AuthenticationError:
        return "badauth"
    except AuthorizationError:
        return "!yours"
    except DynDnsError:
        return "911"

    if not actions:
        return "nohost"
    if any(action in ("updated", "created") for action, _ in actions):
        return f"good {actions[-1][1]}"
    return f"nochg {actions[-1][1]}"
