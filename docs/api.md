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
| `ipv6` | no\*\* | IPv6 literal. Applied to every record that has no `ipv6suffix` entry. |
| `ipv6prefix` | no | IPv6 prefix, e.g. `2001:db8:1:2::/64` (the FRITZ!Box `<ip6lanprefix>` placeholder). A bare address without `/len` is treated as a `/64`; host bits are masked off. Required if `ipv6suffix` is given. |
| `ipv6suffix` | no\*\* | Per-record interface ID as `<record>:<interface-id>`, e.g. `host:9e6b:ff:fe50:179a`. Comma-separated or repeated for multiple records. Each listed record's AAAA is set to `ipv6prefix` + interface ID instead of `ipv6`. Requires `ipv6prefix`; every record named here must also appear in `record`. See below. |

\*\* at least one of `ipv4` / `ipv6` / `ipv6suffix` is required.

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
| `ipv6suffix` without `ipv6prefix` (or vice versa) | `400` | `{"status": "error", "message": "Missing ipv6prefix URL parameter."}` (or `ipv6suffix`) |
| Unparseable `ipv6prefix` | `400` | `{"status": "error", "message": "Invalid ipv6prefix URL parameter."}` |
| Malformed `ipv6suffix`, interface ID overlapping the prefix, or a record listed twice | `400` | `{"status": "error", "message": "Invalid ipv6suffix URL parameter."}` |
| `ipv6suffix` names a record not in `record` | `400` | `{"status": "error", "message": "Record {fqdn} in ipv6suffix is not in record URL parameter."}` |
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

### Per-record IPv6 interface IDs (`ipv6prefix` + `ipv6suffix`)

A FRITZ!Box knows its own WAN IPv6 address (`<ip6addr>`) and the prefix it
delegates to the LAN (`<ip6lanprefix>`), but not the addresses of the hosts
behind it. Hosts with a stable interface ID (EUI-64, a static token, or a
fixed DHCPv6 lease) can still be published: the server combines the LAN
prefix with a per-record interface ID.

```
/?token=...&zone=example.com&record=fritz,host
  &ipv4=<ipaddr>&ipv6=<ip6addr>
  &ipv6prefix=<ip6lanprefix>&ipv6suffix=host:9e6b:ff:fe50:179a
```

With `<ip6lanprefix>` = `2001:db8:1:2::/64` this single call writes:

| Record | `A` | `AAAA` |
|---|---|---|
| `fritz.example.com` | `<ipaddr>` | `<ip6addr>` (the box itself) |
| `host.example.com` | `<ipaddr>` | `2001:db8:1:2:9e6b:ff:fe50:179a` (prefix + interface ID) |

Rules:

- `ipv6suffix` entries are `<record>:<interface-id>`; the record part uses
  the same normalisation as `record` (`@` or the zone name for the apex).
  Repeat the parameter or separate entries with commas.
- The interface ID is parsed as the low bits of an IPv6 address
  (`9e6b:ff:fe50:179a` and `::9e6b:ff:fe50:179a` are equivalent) and must
  fit entirely inside the host part of `ipv6prefix`.
- `ipv6prefix` is masked to its prefix length before combining, so a value
  with host bits set (or a shorter prefix such as a `/56`) is accepted.
- Records with a suffix ignore `ipv6`; records without one use `ipv6` as
  before, and get no `AAAA` update if `ipv6` is absent. `ipv4` applies to
  every record either way.
- `ipv6prefix` and `ipv6suffix` must be supplied together.

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
