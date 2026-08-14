# Changelog

All notable changes to this project are documented in this file, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. This
project does not yet follow strict semantic versioning pre-1.0.

## [Unreleased]

### Fixed

- Cast the TTL read back from Cloudflare's API to `int` before reusing it
  in a record update. The Cloudflare SDK can return the TTL as a float
  (e.g. `60.0`), which the `dns.records.edit` endpoint then rejects with
  `Failed to parse. ttl must be a number.` (closes #65).

## [1.0.0] - Unreleased

Complete rewrite of the service per `plan.md`.

### BREAKING CHANGES

- **Container port changed from `80` to `8080`.** Self-hosters must update
  their port mapping (`-p 8080:8080` instead of `-p 80:80`) and any
  firewall/ingress rules. The container also no longer runs as root.
- The Docker image `CMD` is replaced by an `ENTRYPOINT`
  (`cloudflare-dyndns`); custom `docker run` overrides that assumed
  `python ./app.py` will need updating.

### Added

- `GET /nic/update` — a dyndns2-compatible endpoint for `ddclient`,
  `inadyn`, and routers that expect plain-text replies.
- Multiple records per request via a comma-separated or repeated `record`
  parameter (closes #35, thanks to the PR #20 author for the original
  idea).
- Structured JSON request logging with token/`Authorization` redaction —
  every update request now produces a log line, addressing the
  "undebuggable" complaint in #36.
- `GET /readyz` for readiness (separate from the unchanged `GET /healthz`
  liveness check).
- Optional Prometheus metrics (`CFDD_METRICS_ENABLED`) and FastAPI
  interactive docs (`CFDD_DOCS_ENABLED`).
- Per-tenant, token-hashed in-process caching of zone/record lookups.
- In-process per-client-IP rate limiting.
- Full `CFDD_*` configuration surface — see `docs/configuration.md`.
- Hardened Helm chart: `serviceAccount` (fixes a latent template bug),
  `HorizontalPodAutoscaler`, `PodDisruptionBudget`, `NetworkPolicy` (all
  opt-in), hardened pod/container security contexts, `values.schema.json`.
- CI: lint, typecheck, test matrix (3.11-3.13), Docker build smoke test,
  `hadolint`, `helm lint`/`ct lint`, Trivy filesystem scan, CodeQL,
  scheduled image scan.
- Release automation that publishes multi-arch, cosign-signed, SBOM- and
  provenance-attested images and a signed Helm chart, but **only** on a
  push to `main` or a `v*` tag.

### Changed

- Rewrote the application from Flask + `waitress` + the legacy
  `python-cloudflare` v2 client onto FastAPI + `uvicorn` + the async
  Cloudflare SDK v5.
- Record updates now use `PATCH` (`dns.records.edit`) instead of `PUT`, so
  `proxied`, `ttl`, `comment`, `tags`, and `settings` survive an update
  untouched.
- `record=''`, `record='@'`, and `record` equal to `zone` are now all
  correctly treated as the zone apex (fixes issues where an empty/omitted
  record produced a malformed `.example.com` FQDN).
- Packaging moved to `uv` + `pyproject.toml` + `uv.lock` (`src/` layout).
- CI/CD publish triggers now fire only on `main` and `v*` tags — a push to
  any other branch can no longer overwrite the public `:latest` image or
  chart tag (this was previously possible on every branch push).

### Fixed

- The service no longer starts a server at module import time, making it
  importable/testable and giving it a graceful shutdown path.
- Upstream Cloudflare error messages are redacted before being echoed back
  to the caller.

## [0.x] - Pre-refactor history

See git history prior to this release for the original Flask-based
implementation's changelog (dependency bumps tracked via Dependabot PRs).
