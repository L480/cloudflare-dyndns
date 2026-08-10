# Deployment

## Docker

```bash
docker run -d \
  --name cloudflare-dyndns \
  -p 8080:8080 \
  --read-only --cap-drop=ALL --security-opt no-new-privileges \
  --user 10001:10001 \
  ghcr.io/l480/cloudflare-dyndns:latest
```

The container listens on **port 8080** (not 80 — see `CHANGELOG.md` for the
breaking change), runs as uid/gid `10001`, and works with a read-only root
filesystem.

## Docker Compose

See [`compose.yaml`](../compose.yaml) for a copy-pasteable example with the
hardening flags and every `CFDD_*` setting documented as a comment.

```bash
docker compose up -d
curl -fsS http://localhost:8080/healthz
```

## Kubernetes / Helm

```bash
helm pull oci://ghcr.io/l480/charts/cloudflare-dyndns --version <chart-version>
helm install cloudflare-dyndns oci://ghcr.io/l480/charts/cloudflare-dyndns \
  --version <chart-version> \
  --set config.allowedZones="example.com"
```

See [`helm-chart/values.yaml`](../helm-chart/values.yaml) for the full set
of configurable values, or `helm show values oci://ghcr.io/l480/charts/cloudflare-dyndns`.

## Reverse proxy notes

If you put a reverse proxy or load balancer in front of the service:

- **Terminate TLS at the proxy.** The public token-in-URL contract means
  HTTPS is mandatory end-to-end; see `SECURITY.md`.
- **Set `CFDD_TRUSTED_PROXIES`** to the proxy's address/CIDR so
  `X-Forwarded-For` is honoured for per-client rate limiting. Without this,
  every request appears to originate from the proxy's IP and shares a
  single rate-limit bucket.
- Rate limiting is per-process (see `docs/configuration.md`); behind
  multiple replicas it's approximate. For a public multi-replica
  deployment, enforce the real limit at the proxy or at Cloudflare, not in
  this service.
