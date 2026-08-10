# Security Policy

## Supported versions

Only the latest published release (image tags `latest` / `X.Y.Z` and the
`main`-tracking `edge` tag) is supported with security fixes. There is no
LTS branch.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.
Report privately using [GitHub Security Advisories](https://github.com/l480/cloudflare-dyndns/security/advisories/new).

You should expect an initial response within a few days.

## A note on API tokens in the URL

`cloudflare-dyndns` implements the DynDNS "Update URL" protocol, which by
convention passes credentials as a query parameter
(`?token=...`). This is a property of the protocol, not a bug in this
project, but it has real consequences:

- **Always use HTTPS.** A token sent over plain HTTP is trivially
  interceptable. The public hosted instance only accepts HTTPS.
- **Scope the token narrowly.** Create a dedicated Cloudflare API token
  with `Zone.DNS:Edit` and `Zone.Zone:Read` permissions, restricted to the
  specific zone(s) you intend to update. Never use your Cloudflare Global
  API Key.
- **Query strings can end up in logs.** This service redacts tokens from
  its own logs and never echoes them back in responses, but any reverse
  proxy, load balancer, or browser history in front of it may log the full
  URL. Prefer sending the token via `Authorization: Bearer` or HTTP Basic
  auth when your client supports it (see `docs/api.md`) if you control the
  network path and want to avoid the query string entirely.
- **Prefer self-hosting for sensitive zones.** The public hosted instance
  is convenient but is, by design, a third party with the ability to write
  DNS records for any zone you point it at with a valid token.
