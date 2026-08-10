# API

## `GET /` — legacy-compatible update endpoint

The original endpoint. **Byte-compatible with the pre-refactor service** for
every documented status/body combination below — this is enforced by
`tests/test_api_compat.py`.

### Query parameters

| Name | Required | Notes |
|---|---|---|
| `token` | yes\* | Cloudflare API token. \*Also accepted via `Authorization: Bearer <token>` or HTTP Basic password. The query parameter wins if more than one is present. |
| `zone` | yes | Zone apex, e.g. `example.com`. Case-insensitive; trailing dot stripped. |
| `record` | no | Subdomain label(s), e.g. `www` or `home.iot`. Empty string, missing, `@`, and a value equal to `zone` all mean the **zone apex**. Comma-separated or repeated for multiple records (see below). |
| `ipv4` | no\*\* | IPv4 literal. |
| `ipv6` | no\*\* | IPv6 literal. |

\*\* at least one of `ipv4` / `ipv6` is required.

### Responses

All `Content-Type: application/json`.

| Situation | Status | Body |
|---|---|---|
| Update applied, or nothing to change | `200` | `{"status": "success", "message": "Update successful.", "results": [...]}` |
| Multiple records, some succeeded and some failed | `207` | `{"status": "partial", "message": "Update successful.", "results": [...]}` |
| Missing `token` | `400` | `{"status": "error", "message": "Missing token URL parameter."}` |
| Missing `zone` | `400` | `{"status": "error", "message": "Missing zone URL parameter."}` |
| Missing both IPs | `400` | `{"status": "error", "message": "Missing ipv4 or ipv6 URL parameter."}` |
| Invalid IP literal | `400` | `{"status": "error", "message": "Invalid ipv4 URL parameter."}` (or `ipv6`) |
| Bad/expired token | `401` | `{"status": "error", "message": "Cloudflare authentication failed."}` |
| Token lacks permission on the zone | `403` | `{"status": "error", "message": "Cloudflare authorization failed."}` |
| Zone not in `CFDD_ALLOWED_ZONES` | `403` | `{"status": "error", "message": "Zone {zone} is not allowed on this instance."}` |
| Zone not found | `404` | `{"status": "error", "message": "Zone {zone} does not exist."}` |
| A record missing (and `CFDD_CREATE_MISSING_RECORDS=false`) | `404` | `{"status": "error", "message": "A record for {fqdn} does not exist."}` |
| AAAA record missing | `404` | `{"status": "error", "message": "AAAA record for {fqdn} does not exist."}` |
| Local rate limit hit | `429` | `{"status": "error", "message": "Too many requests."}` + `Retry-After` header |
| Cloudflare rate limit hit | `429` | `{"status": "error", "message": "Cloudflare rate limit exceeded."}` + `Retry-After` |
| Upstream timeout / connection error | `504` | `{"status": "error", "message": "Cloudflare API unreachable."}` |
| Unexpected upstream error | `500` | `{"status": "error", "message": "<redacted upstream message>"}` |

`results` is additive (existing clients ignore unknown JSON keys) and looks
like:

```jsonc
{
  "status": "success",
  "message": "Update successful.",
  "results": [
    {"fqdn": "www.example.com", "type": "A", "content": "203.0.113.7", "action": "updated"},
    {"fqdn": "www.example.com", "type": "AAAA", "content": "2001:db8::1", "action": "unchanged"}
  ]
}
```

`action` is one of `updated`, `unchanged`, `created`, `error`.

### Multiple records per request

`record` accepts a comma-separated list, or repetition:

```
/?token=...&zone=example.com&record=www,vpn&ipv4=203.0.113.7
/?token=...&zone=example.com&record=www&record=vpn&ipv4=203.0.113.7
```

All records are updated for all supplied IP families. A single-record
request always keeps the legacy single-status behaviour (200 or a single
error code); only a multi-record request can return `207`.

## `GET /nic/update` — dyndns2-compatible endpoint

Standard [dyndns2](https://help.dyn.com/remote-access-api/perform-update/)
semantics, for `ddclient`, `inadyn`, and routers that expect a plain-text
reply.

| Parameter | Notes |
|---|---|
| `hostname` | FQDN(s) to update. Comma-separated for multiple. |
| `myip` | IPv4 to set. If omitted (and `myipv6` also omitted), defaults to the requester's apparent IP. |
| `myipv6` | IPv6 to set. |

Auth via HTTP Basic (`password` = Cloudflare token) or
`Authorization: Bearer <token>`.

`Content-Type: text/plain`. One line per `hostname`:

| Result | Body |
|---|---|
| Updated | `good <ip>` |
| No change | `nochg <ip>` |
| Bad token | `badauth` |
| Unknown host (no zone on this token contains it) | `nohost` |
| Zone not permitted / token lacks access | `!yours` |
| Rate limited | `abuse` |
| Server error | `911` |

The zone is derived by listing the zones visible to the token and picking
the longest zone name that is a suffix of `hostname`.

## Health & ops endpoints

| Path | Purpose |
|---|---|
| `GET /healthz` | Liveness. Always `200 {"status":"success","message":"OK"}` — unchanged from the legacy service; the Helm chart's liveness probe targets this. |
| `GET /readyz` | Readiness. `200` when the process can serve; `503` during shutdown drain. Does **not** call Cloudflare. |
| `GET /metrics` | Prometheus metrics. Only mounted when `CFDD_METRICS_ENABLED=true`. |
| `GET /docs`, `GET /openapi.json` | FastAPI interactive docs. Only mounted when `CFDD_DOCS_ENABLED=true` (default `false`). |
