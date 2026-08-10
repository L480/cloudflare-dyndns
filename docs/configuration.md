# Configuration

All settings are environment variables with the prefix `CFDD_`, parsed by
`pydantic-settings`. Boolean values accept `true`/`false` (case-insensitive).
Comma-separated values are trimmed of surrounding whitespace.

| Env var | Type | Default | Meaning |
|---|---|---|---|
| `CFDD_HOST` | str | `0.0.0.0` | Bind address |
| `CFDD_PORT` | int | `8080` | Bind port |
| `CFDD_LOG_LEVEL` | enum | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `CFDD_LOG_FORMAT` | enum | `json` | `json` \| `console` |
| `CFDD_ALLOWED_ZONES` | comma-list | `` (= all) | Allowlist of zones this instance will touch, e.g. `example.com,example.org` |
| `CFDD_CREATE_MISSING_RECORDS` | bool | `false` | Create the record if absent instead of returning 404 |
| `CFDD_DEFAULT_TTL` | int | `1` | TTL for created records (`1` = Cloudflare "automatic"; otherwise `60`-`86400`) |
| `CFDD_DEFAULT_PROXIED` | bool | `false` | `proxied` for created records |
| `CFDD_ZONE_CACHE_TTL` | int (seconds) | `300` | Cache lifetime for zone-name → zone-id lookups |
| `CFDD_RECORD_CACHE_TTL` | int (seconds) | `60` | Cache lifetime for record lookups |
| `CFDD_CACHE_MAX_ENTRIES` | int | `1024` | Bound on the in-process cache (per cache) |
| `CFDD_CF_TIMEOUT` | float (seconds) | `10.0` | Per-request Cloudflare API timeout |
| `CFDD_CF_MAX_RETRIES` | int | `2` | Cloudflare SDK retry count |
| `CFDD_RATE_LIMIT_ENABLED` | bool | `true` | Per-client-IP token bucket |
| `CFDD_RATE_LIMIT_PER_MINUTE` | int | `30` | Sustained requests per minute per client IP |
| `CFDD_RATE_LIMIT_BURST` | int | `10` | Burst allowance per client IP |
| `CFDD_TRUSTED_PROXIES` | comma-list of CIDRs | `` (none) | CIDRs allowed to set `X-Forwarded-For`; empty means the header is always ignored |
| `CFDD_METRICS_ENABLED` | bool | `false` | Expose `GET /metrics` (Prometheus) |
| `CFDD_DOCS_ENABLED` | bool | `false` | Expose `GET /docs` and `GET /openapi.json` |

## Notes

- **Caching is per-process, not shared across replicas.** Behind multiple
  replicas, rate limiting is therefore approximate — for a public,
  multi-replica deployment, enforce the real limit at the ingress or
  Cloudflare layer, not `CFDD_RATE_LIMIT_*`.
- **Caching is safe across tenants.** Cache keys always include a hash of
  the caller's Cloudflare API token, never the token itself, so a zone id
  cached for one token can never be returned for a request using a
  different token.
- `CFDD_TRUSTED_PROXIES` must be set for `X-Forwarded-For` to have any
  effect. If your deployment sits behind a reverse proxy or load balancer,
  set this to that proxy's address/CIDR so per-client rate limiting sees
  the real client IP rather than the proxy's IP for every request. See
  `docs/deployment.md`.
- Reference: `src/cloudflare_dyndns/config.py` is the source of truth this
  document is kept in sync with.
