# Refactoring Plan: `cloudflare-dyndns`

> **Purpose of this document.** This is the complete, self-contained implementation
> plan for modernising this repository. It is written to be executed by an
> implementation agent (or a human) **one task at a time**, top to bottom.
> Every task has explicit file paths, concrete content sketches, and acceptance
> criteria. Do not skip ahead: later phases assume earlier ones are merged.

---

## 0. Context

### 0.1 What the project is

A tiny HTTP middleware that lets an AVM FRITZ!Box (or any DynDNS client) update
Cloudflare DNS records. The FRITZ!Box calls an "Update URL" whenever its WAN IP
changes; this service translates that call into Cloudflare API writes.

Public deployment: `https://dyndns.nicoo.org/` (multi-tenant — arbitrary users
send their **own** Cloudflare API token as a query parameter). This matters:
the service must never log or leak tokens, and must be hardened against abuse.

### 0.2 Current state (audited 2026-08-10, commit `6eb8cf5`)

```
.
├── .github/
│   ├── FUNDING.yml
│   └── workflows/
│       ├── docker-build-push.yml
│       └── helmchart-push.yml
├── helm-chart/            # stock `helm create` scaffold, lightly edited
├── images/
├── Dockerfile             # 10 lines, single stage, runs as root on port 80
├── LICENSE                # Apache-2.0
├── README.md
├── app.py                 # 64 lines, the entire application
└── requirements.txt       # cloudflare~=2.19.0, Flask~=2.0, waitress~=3.0
```

### 0.3 Problems found

**Application (`app.py`)**

| # | Problem | Impact |
|---|---|---|
| A1 | `cf = CloudFlare.CloudFlare(token=token)` is constructed *before* the `token` is validated (line 17 vs. line 19) | Client built with `None`; wasted work, confusing failure modes |
| A2 | `waitress.serve(...)` runs at **module import time** (line 64) | Impossible to import for tests; no ASGI/WSGI entrypoint; no graceful shutdown |
| A3 | `app.secret_key = os.urandom(24)` | Dead code — no sessions/flash are used |
| A4 | `record=''` (empty string, which is what a client sends for an empty field) is not `None`, so the FQDN becomes `".example.com"` | Root-of-zone updates silently 404 for a whole class of clients |
| A5 | `record='@'` is not handled | Same as A4 |
| A6 | No validation that `ipv4`/`ipv6` are actually valid addresses of the right family | Garbage is forwarded to Cloudflare; an IPv6 literal in `ipv4=` produces a confusing upstream error |
| A7 | Zone lookup + 2 record lookups on **every** request, no caching | 3–5 Cloudflare API calls per update; risks the 1200 req/5 min account limit |
| A8 | Uses `PUT` (`dns_records.put`) and manually re-sends `proxied`/`ttl` | `PATCH` exists and preserves all unspecified fields safely; the manual copy loses `comment`, `tags`, `settings` |
| A9 | If the A update succeeds and the AAAA update then raises, the request is left half-applied and returns 500 | Non-atomic, no partial-success reporting |
| A10 | No timeouts, no retries, no backoff on the Cloudflare client | A hung upstream hangs a worker thread indefinitely |
| A11 | No logging whatsoever | Issue #36 ("FritzBox not updating") is undebuggable — there is no way to tell whether the router even called the service |
| A12 | Errors return `str(e)` verbatim | Potential to echo request context back to the caller; no redaction guarantee |
| A13 | Responses are JSON only | The dyndns2 de-facto protocol (`good <ip>` / `nochg <ip>` / `badauth`) is what `ddclient`, `inadyn` and many routers expect |
| A14 | No rate limiting, no request-size limits, no abuse controls | The public instance is an open proxy to the Cloudflare API |
| A15 | Only one record can be updated per request | Open issue #35, open PR #20 |
| A16 | No "no change needed" short-circuit response distinguishable from a real update | Clients cannot tell; Cloudflare gets pointless writes avoided only implicitly |

**Dependencies**

| # | Problem |
|---|---|
| D1 | `cloudflare~=2.19.0` is the **legacy, unmaintained** `python-cloudflare` interface (`import CloudFlare`). The current package is **v5.x** (`from cloudflare import Cloudflare`), Stainless-generated, `httpx`-based, fully typed, with sync **and async** clients. |
| D2 | `Flask~=2.0` (Flask 3.x is current) |
| D3 | `requirements.txt` with fuzzy `~=` pins and **no lock file** → non-reproducible builds |
| D4 | No dependency-update automation configured in the repo (`dependabot.yml` / `renovate.json` absent) |

**Container**

| # | Problem |
|---|---|
| C1 | Single-stage build, no layer separation for dependency caching beyond the trivial case |
| C2 | Runs as **root** |
| C3 | Binds **port 80** (a privileged port — forces root, blocks `runAsNonRoot` in Kubernetes) |
| C4 | Base image `python:3-alpine` is an unpinned floating tag; builds are not reproducible and can break without a commit |
| C5 | No `HEALTHCHECK` |
| C6 | No OCI labels (`org.opencontainers.image.*`) |
| C7 | No SBOM, no build provenance, no image signing |
| C8 | Alpine/musl for a Python app — slower and a source of wheel-availability pain |

**CI/CD**

| # | Problem |
|---|---|
| P1 | `on: push` → both workflows run on **every branch push**, and both push `:latest` to the registry. A push to any branch overwrites the published `latest` image and re-publishes the chart. |
| P2 | Only `:latest` is ever tagged — no semver, no SHA, no immutable tags |
| P3 | No lint, no type-check, no tests in CI (there are none to run) |
| P4 | No vulnerability scanning, no CodeQL, no secret scanning gate |
| P5 | Helm chart version is hardcoded `0.1.0` and never bumped, so every chart push overwrites the same OCI tag |
| P6 | `helm push --kube-as-user/--kube-token` flags are meaningless for an OCI push (copy-paste artefact) |
| P7 | Workflow actions are pinned to mutable major tags, not commit SHAs |
| P8 | No release process, no `CHANGELOG.md`, no git tags |

**Helm chart**

| # | Problem |
|---|---|
| H1 | `_helpers.tpl` defines `cloudflare-dyndns.serviceAccountName` referencing `.Values.serviceAccount.create`, but `values.yaml` has **no `serviceAccount` key** → the template errors if ever used (latent bug) |
| H2 | No `serviceaccount.yaml` template at all |
| H3 | `podSecurityContext: {}` / `securityContext: {}` — no hardened defaults |
| H4 | No `resources` defaults |
| H5 | No `startupProbe`; liveness/readiness have no `initialDelaySeconds`/`timeoutSeconds` |
| H6 | No HPA, no PodDisruptionBudget, no NetworkPolicy |
| H7 | No `values.schema.json`, no chart README, no chart tests |
| H8 | `appVersion: "latest"` and `image.tag: "latest"` with `pullPolicy: Always` — not pinnable, not reproducible |
| H9 | Ingress template still carries `extensions/v1beta1` / `networking.k8s.io/v1beta1` branches for Kubernetes < 1.19 (EOL since 2020) |

**Repository hygiene**

| # | Problem |
|---|---|
| R1 | No `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue/PR templates |
| R2 | No `CHANGELOG.md`, no releases |
| R3 | No `.editorconfig`, no `pre-commit` |
| R4 | README does not document self-hosting configuration, the API contract, or non-FRITZ!Box clients |
| R5 | Open issues #29, #32, #35, #36 and PR #20 are unaddressed |

### 0.4 Design decisions (already made — do not re-litigate)

| Decision | Choice | Rationale |
|---|---|---|
| Web framework | **FastAPI** (ASGI) + **uvicorn** | Native async pairs with the async Cloudflare SDK; Pydantic gives free, correct input validation (`IPvAnyAddress`); OpenAPI docs come for free; it is the current mainstream choice. Flask 3 + waitress would also work but buys nothing here. |
| Cloudflare SDK | **`cloudflare>=5,<6`** (`AsyncCloudflare`) | The v2 interface is dead. v5 is typed, async-capable, has built-in retries/timeouts. |
| Packaging | **`uv` + `pyproject.toml` + `uv.lock`**, `src/` layout | Reproducible, fast, single tool for env + lock + run. |
| Lint/format | **Ruff** (lint **and** format) | Replaces flake8/black/isort/pyupgrade. |
| Types | **mypy `--strict`** | The codebase is small enough that strict is free. |
| Tests | **pytest** + `pytest-asyncio` + `respx` (httpx mocking) + `coverage` | `respx` mocks at the HTTP layer, so tests exercise the real SDK. |
| Python baseline | `requires-python = ">=3.11"`, CI matrix 3.11/3.12/3.13, container 3.13 | Wide compatibility, modern syntax. |
| Config | **`pydantic-settings`**, env prefix `CFDD_` | Typed, validated, documented configuration. |
| Container port | **8080** (non-privileged) | Enables `runAsNonRoot` + `readOnlyRootFilesystem`. |
| Backwards compatibility | **`GET /` with `token`/`zone`/`record`/`ipv4`/`ipv6` must keep working byte-compatibly** | The public instance has live users with configured routers. Breaking it breaks their DNS. |

### 0.5 Non-goals

- No database, no persistence, no user accounts. The caller's token stays the unit of auth.
- No web UI.
- No rewrite in another language.
- Cloudflare Access support (issue #32) is **out of scope** for this refactor; it is recorded in the backlog only.

---

## 1. Target repository layout

```
.
├── .editorconfig
├── .github/
│   ├── CODEOWNERS
│   ├── FUNDING.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml
│   │   ├── config.yml
│   │   └── feature_request.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── dependabot.yml
│   └── workflows/
│       ├── ci.yml                  # lint, typecheck, test, build (PR + main)
│       ├── codeql.yml
│       ├── release.yml             # tag -> image + chart + GitHub Release
│       └── scan.yml                # scheduled Trivy scan of published image
├── .pre-commit-config.yaml
├── CHANGELOG.md
├── CONTRIBUTING.md
├── Dockerfile
├── LICENSE
├── README.md
├── SECURITY.md
├── compose.yaml
├── docs/
│   ├── api.md
│   ├── clients.md                  # FRITZ!Box, ddclient, inadyn, curl
│   ├── configuration.md
│   └── deployment.md
├── helm-chart/
│   ├── Chart.yaml
│   ├── README.md                   # generated by helm-docs
│   ├── values.schema.json
│   ├── values.yaml
│   ├── ci/
│   │   ├── default-values.yaml
│   │   └── full-values.yaml
│   └── templates/
│       ├── NOTES.txt
│       ├── _helpers.tpl
│       ├── deployment.yaml
│       ├── hpa.yaml
│       ├── ingress.yaml
│       ├── networkpolicy.yaml
│       ├── pdb.yaml
│       ├── service.yaml
│       ├── serviceaccount.yaml
│       └── tests/
│           └── test-connection.yaml
├── images/
├── plan.md                         # this file (delete when the plan is done)
├── pyproject.toml
├── src/
│   └── cloudflare_dyndns/
│       ├── __init__.py
│       ├── __main__.py             # `python -m cloudflare_dyndns`
│       ├── api.py                  # FastAPI routers / endpoints
│       ├── app.py                  # app factory, lifespan, middleware
│       ├── cloudflare_client.py    # thin async wrapper + caching + errors
│       ├── config.py               # pydantic-settings Settings
│       ├── errors.py               # domain exceptions + handlers
│       ├── logging.py              # structured JSON logging + redaction
│       ├── models.py               # request/response Pydantic models
│       ├── py.typed
│       ├── ratelimit.py
│       └── service.py              # update orchestration (pure-ish logic)
├── tests/
│   ├── conftest.py
│   ├── test_api_compat.py          # legacy contract must not break
│   ├── test_api_errors.py
│   ├── test_cloudflare_client.py
│   ├── test_config.py
│   ├── test_logging_redaction.py
│   ├── test_ratelimit.py
│   └── test_service.py
└── uv.lock
```

`app.py` at the repo root is **deleted**; `requirements.txt` is **deleted**.

---

## 2. API contract (the specification to implement)

### 2.1 `GET /` — legacy-compatible update endpoint (**must not break**)

Query parameters:

| Name | Required | Type | Notes |
|---|---|---|---|
| `token` | yes | string | Cloudflare API token. Also accepted via `Authorization: Bearer <token>` **or** HTTP Basic password. Query parameter wins if both are present. |
| `zone` | yes | string | Zone apex, e.g. `example.com`. Case-insensitive, trailing dot stripped. |
| `record` | no | string | Subdomain label(s), e.g. `www` or `home.iot`. Empty string, missing, `@` and a value equal to `zone` all mean **zone apex**. May be repeated or comma-separated (see §2.2). |
| `ipv4` | no* | IPv4 | |
| `ipv6` | no* | IPv6 | |

\* at least one of `ipv4` / `ipv6` is required.

Responses (JSON, `Content-Type: application/json`) — **these exact shapes must be
preserved for the success and legacy error paths**:

| Situation | Status | Body |
|---|---|---|
| Update applied, or nothing to change | `200` | `{"status": "success", "message": "Update successful."}` |
| Missing `token` | `400` | `{"status": "error", "message": "Missing token URL parameter."}` |
| Missing `zone` | `400` | `{"status": "error", "message": "Missing zone URL parameter."}` |
| Missing both IPs | `400` | `{"status": "error", "message": "Missing ipv4 or ipv6 URL parameter."}` |
| Zone not found | `404` | `{"status": "error", "message": "Zone {zone} does not exist."}` |
| A record missing | `404` | `{"status": "error", "message": "A record for {fqdn} does not exist."}` |
| AAAA record missing | `404` | `{"status": "error", "message": "AAAA record for {fqdn} does not exist."}` |
| Upstream Cloudflare error | `500` | `{"status": "error", "message": "<redacted upstream message>"}` |

**New**, additive-only fields — allowed because clients ignore unknown JSON keys:

```jsonc
{
  "status": "success",
  "message": "Update successful.",
  "results": [                       // NEW
    {"fqdn": "www.example.com", "type": "A",    "content": "203.0.113.7", "action": "updated"},
    {"fqdn": "www.example.com", "type": "AAAA", "content": "2001:db8::1", "action": "unchanged"}
  ]
}
```

`action` ∈ `updated` | `unchanged` | `created`.

New failure modes get new status codes:

| Situation | Status | `message` |
|---|---|---|
| Invalid IP literal | `400` | `Invalid ipv4 URL parameter.` / `Invalid ipv6 URL parameter.` |
| Bad/expired token | `401` | `Cloudflare authentication failed.` |
| Token lacks permission on the zone | `403` | `Cloudflare authorization failed.` |
| Zone not in `CFDD_ALLOWED_ZONES` | `403` | `Zone {zone} is not allowed on this instance.` |
| Local rate limit hit | `429` | `Too many requests.` + `Retry-After` header |
| Cloudflare rate limit hit | `429` | `Cloudflare rate limit exceeded.` + `Retry-After` |
| Upstream timeout / connection error | `504` | `Cloudflare API unreachable.` |

### 2.2 Multiple records per request (issues #35, PR #20)

`record` accepts a comma-separated list **and** repetition:

```
/?token=…&zone=example.com&record=www,vpn&ipv4=203.0.113.7
/?token=…&zone=example.com&record=www&record=vpn&ipv4=203.0.113.7
```

Semantics: all records are updated for all supplied families. The response
`results` array has one entry per (fqdn, type) pair. If **some** succeed and
**some** fail, return `207 Multi-Status` with `status: "partial"` and per-entry
`"action": "error"` plus `"message"`. A single-record request never returns
`207` — it keeps the legacy single status code, so existing clients are
unaffected.

### 2.3 `GET /nic/update` — dyndns2-compatible endpoint (new)

Standard dyndns2 semantics for `ddclient`, `inadyn`, and routers that expect
plain-text replies. Parameters: `hostname` (FQDN, comma-separated allowed),
`myip`, `myipv6`. Auth via HTTP Basic (`password` = Cloudflare token) or
`Authorization: Bearer`. Response body is `text/plain`:

| Result | Body |
|---|---|
| Updated | `good <ip>` |
| No change | `nochg <ip>` |
| Bad token | `badauth` |
| Unknown host | `nohost` |
| Not allowed | `!yours` |
| Rate limited | `abuse` |
| Server error | `911` |

The zone is derived from the hostname by querying Cloudflare for the longest
matching zone the token can see.

### 2.4 Health & ops endpoints

| Path | Purpose |
|---|---|
| `GET /healthz` | Liveness. Always `200 {"status":"success","message":"OK"}` (**unchanged** — the Helm chart probes it). |
| `GET /readyz` | Readiness. `200` when the process can serve; `503` during shutdown drain. Does **not** call Cloudflare. |
| `GET /metrics` | Prometheus metrics. Disabled unless `CFDD_METRICS_ENABLED=true`. |
| `GET /docs`, `GET /openapi.json` | FastAPI docs. Disabled unless `CFDD_DOCS_ENABLED=true` (default `false` for the public instance). |

---

## 3. Configuration surface

All settings are environment variables with the prefix `CFDD_`, parsed by
`pydantic-settings`. Every one must appear in `docs/configuration.md` **and** in
the Helm chart values.

| Env var | Type | Default | Meaning |
|---|---|---|---|
| `CFDD_HOST` | str | `0.0.0.0` | Bind address |
| `CFDD_PORT` | int | `8080` | Bind port |
| `CFDD_LOG_LEVEL` | enum | `INFO` | `DEBUG`…`CRITICAL` |
| `CFDD_LOG_FORMAT` | enum | `json` | `json` \| `console` |
| `CFDD_ALLOWED_ZONES` | list[str] | `[]` (= all) | Comma-separated allowlist of zones this instance will touch |
| `CFDD_CREATE_MISSING_RECORDS` | bool | `false` | Create the record if absent instead of 404 |
| `CFDD_DEFAULT_TTL` | int | `1` | TTL for created records (`1` = Cloudflare "automatic") |
| `CFDD_DEFAULT_PROXIED` | bool | `false` | `proxied` for created records |
| `CFDD_ZONE_CACHE_TTL` | int (s) | `300` | Cache lifetime for zone-name → zone-id |
| `CFDD_RECORD_CACHE_TTL` | int (s) | `60` | Cache lifetime for record lookups |
| `CFDD_CACHE_MAX_ENTRIES` | int | `1024` | Bound on the in-process cache |
| `CFDD_CF_TIMEOUT` | float (s) | `10.0` | Per-request Cloudflare timeout |
| `CFDD_CF_MAX_RETRIES` | int | `2` | SDK retry count |
| `CFDD_RATE_LIMIT_ENABLED` | bool | `true` | Per-client-IP token bucket |
| `CFDD_RATE_LIMIT_PER_MINUTE` | int | `30` | |
| `CFDD_RATE_LIMIT_BURST` | int | `10` | |
| `CFDD_TRUSTED_PROXIES` | list[str] | `[]` | CIDRs allowed to set `X-Forwarded-For`; empty = ignore the header entirely |
| `CFDD_METRICS_ENABLED` | bool | `false` | Expose `/metrics` |
| `CFDD_DOCS_ENABLED` | bool | `false` | Expose `/docs` + `/openapi.json` |

**Caching rule (security-critical):** cache keys **must** include a hash of the
API token (`sha256(token)[:16]`), never the token itself. A cache shared across
tenants without the token in the key would leak one tenant's zone IDs to
another. Write a test for this.

---

## 4. Phased task list

Each task is sized for a single commit. Conventional Commits are required
(`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`, `ci:`, `build:`).

---

### Phase 0 — Tooling & scaffolding (no behaviour change)

#### T0.1 — Introduce `pyproject.toml` + `uv`

**Files:** `pyproject.toml` (new), `uv.lock` (generated), delete `requirements.txt` **in T1.9, not here**.

```toml
[project]
name = "cloudflare-dyndns"
version = "0.0.0"                      # managed by the release workflow
description = "Cloudflare DynDNS middleware for AVM FRITZ!Box and other DynDNS clients"
readme = "README.md"
license = "Apache-2.0"
authors = [{ name = "Nico Struck", email = "mail@nico-struck.de" }]
requires-python = ">=3.11"
classifiers = [
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Internet :: Name Service (DNS)",
]
dependencies = [
  "cloudflare>=5,<6",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
]

[project.optional-dependencies]
metrics = ["prometheus-client>=0.21"]

[project.scripts]
cloudflare-dyndns = "cloudflare_dyndns.__main__:main"

[project.urls]
Homepage = "https://github.com/l480/cloudflare-dyndns"
Issues = "https://github.com/l480/cloudflare-dyndns/issues"

[dependency-groups]
dev = [
  "mypy>=1.13",
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "pytest-cov>=6.0",
  "respx>=0.21",
  "httpx>=0.27",
  "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/cloudflare_dyndns"]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = [
  "E", "F", "W",        # pycodestyle / pyflakes
  "I",                  # isort
  "N",                  # pep8-naming
  "UP",                 # pyupgrade
  "B",                  # bugbear
  "A",                  # builtins shadowing
  "C4",                 # comprehensions
  "S",                  # bandit
  "T20",                # no print
  "SIM",                # simplify
  "PTH",                # pathlib
  "RUF",
  "ASYNC",
  "ANN",                # annotations
]
ignore = ["ANN401"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101", "ANN201", "ANN001"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_unreachable = true
files = ["src", "tests"]

[tool.pytest.ini_options]
addopts = "-q --strict-markers --cov=cloudflare_dyndns --cov-report=term-missing --cov-fail-under=90"
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.report]
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError"]
```

**Do:** `uv lock` then `uv sync --all-extras --dev`, commit `uv.lock`.

**Acceptance:** `uv run python -c "import fastapi, cloudflare"` succeeds; `uv.lock` is committed.

> **Note on version floors:** the floors above were correct when this plan was
> written. Run `uv lock --upgrade` once at the start and let the lock file be
> the source of truth. Do not pin exact versions in `pyproject.toml`.

#### T0.2 — Repo hygiene files

**Files:** `.editorconfig`, `.pre-commit-config.yaml`, `.gitignore` (add `.venv/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage*`, `*.tgz`).

`.pre-commit-config.yaml` hooks: `ruff` (with `--fix`), `ruff-format`,
`check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`,
`detect-private-key`.

**Acceptance:** `uvx pre-commit run --all-files` passes (after the formatter's own fixes are committed).

#### T0.3 — Community health files

**Files:** `CONTRIBUTING.md`, `SECURITY.md`, `.github/CODEOWNERS`,
`.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/{bug_report.yml,feature_request.yml,config.yml}`.

`SECURITY.md` must state: supported versions, private reporting via GitHub
Security Advisories, and an explicit warning that **API tokens travel in the
URL query string** by protocol necessity — therefore users must use HTTPS and
scope tokens to `Zone.DNS:Edit` + `Zone.Zone:Read` on specific zones only.

The bug report template must ask for: deployment method, image tag, client
(FRITZ!Box model + FRITZ!OS version), the Update URL **with the token
redacted**, and the service log lines for the failing request.

**Acceptance:** files render on GitHub; the issue form validates.

#### T0.4 — Dependency automation

**File:** `.github/dependabot.yml` covering ecosystems `uv` (or `pip`),
`github-actions`, and `docker`, weekly, grouped minor/patch updates, with
`open-pull-requests-limit: 10`.

**Acceptance:** Dependabot config validates in the repo Insights tab.

---

### Phase 1 — Application rewrite

> Implement in this order. Each module is small; keep it that way.

#### T1.1 — `src/cloudflare_dyndns/config.py`

`Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_prefix="CFDD_", env_file=".env", extra="ignore")` and every field from §3, correctly typed
(`list[str]` fields parse comma-separated values; `CFDD_TRUSTED_PROXIES` parses
into `list[IPv4Network | IPv6Network]`). Expose a module-level
`@lru_cache def get_settings() -> Settings`.

Validators: `allowed_zones` are lower-cased and stripped of trailing dots;
`default_ttl` is `1` or in `[60, 86400]`; `port` in `[1, 65535]`.

**Acceptance:** `tests/test_config.py` covers defaults, env parsing, comma-list
parsing, and each validator's rejection path.

#### T1.2 — `src/cloudflare_dyndns/logging.py`

- `configure_logging(settings)` installs either a JSON formatter (stdlib
  `logging` + a small `JsonFormatter`; no extra dependency needed) or a human
  console formatter.
- A `RedactingFilter` that scrubs anything token-shaped from log records:
  the `token=` query parameter, `Authorization` header values, and any value
  that matches a Cloudflare token pattern (`[A-Za-z0-9_-]{30,}`) → replaced with
  `***redacted***`.
- A `request_id` `ContextVar`, populated by middleware from the incoming
  `X-Request-ID` header or a fresh `uuid4`, and echoed on the response.
- Uvicorn's `access` logger must be **disabled** (`--no-access-log`) and replaced
  by the app's own middleware, so query strings are never written raw.

**Acceptance:** `tests/test_logging_redaction.py` asserts that a log record
containing a realistic token, a full request URL with `token=`, and an
`Authorization: Bearer` header emits **no** substring of the token.

#### T1.3 — `src/cloudflare_dyndns/errors.py`

Domain exceptions, each carrying `status_code` and the exact legacy `message`
string from §2.1:

```
DynDnsError(Exception)
├── MissingParameterError      -> 400
├── InvalidParameterError      -> 400
├── ZoneNotFoundError          -> 404
├── RecordNotFoundError        -> 404
├── ZoneNotAllowedError        -> 403
├── AuthenticationError        -> 401
├── AuthorizationError         -> 403
├── RateLimitedError           -> 429  (carries retry_after)
├── UpstreamTimeoutError       -> 504
└── UpstreamError              -> 500
```

Plus `install_exception_handlers(app)` which renders the JSON envelope
`{"status": "error", "message": ...}` for the `/` router and the plain-text
dyndns2 codes for the `/nic/update` router, and a catch-all handler that logs
the traceback and returns a generic 500 without leaking internals.

**Acceptance:** `tests/test_api_errors.py` asserts every row of the §2.1 tables.

#### T1.4 — `src/cloudflare_dyndns/models.py`

Pydantic models:

- `UpdateQuery` — validates and normalises the `/` query parameters. Key logic:
  - `record`: split on `,`, strip whitespace, drop empties; `''`, `'@'`, and a
    value equal to `zone` all normalise to the apex (represented as `None`).
  - `zone`: lower-cased, trailing dot stripped, validated as a plausible domain.
  - `ipv4: IPv4Address | None`, `ipv6: IPv6Address | None` — Pydantic rejects a
    v6 literal in `ipv4` automatically.
  - Model validator: at least one of `ipv4`/`ipv6` present.
  - **Order matters:** the missing-parameter checks must fire in the legacy
    order (token → zone → ip) so the legacy messages match. Implement this by
    checking presence explicitly in the route **before** Pydantic parsing, or
    by ordering validators and mapping `RequestValidationError` accordingly.
- `RecordResult` — `fqdn`, `type`, `content`, `action`, optional `message`.
- `UpdateResponse` — `status`, `message`, `results`.
- `HealthResponse` — `status`, `message`.

Add a helper `fqdn(record: str | None, zone: str) -> str` returning `zone` when
`record is None`, else `f"{record}.{zone}"`.

**Acceptance:** parametrised tests for `record` normalisation covering
`None`, `''`, `'@'`, `'www'`, `'a.b'`, `'www,vpn'`, `'www, vpn'`,
`'example.com'` (== zone), and a token-length record list.

#### T1.5 — `src/cloudflare_dyndns/cloudflare_client.py`

An async wrapper around `AsyncCloudflare`. Responsibilities:

- Build a client **per request token**: `AsyncCloudflare(api_token=token, timeout=settings.cf_timeout, max_retries=settings.cf_max_retries)`, used as an
  async context manager so connections are released. (If profiling later shows
  client construction is hot, add a small keyed pool — do not do it now.)
- `async def get_zone_id(token, zone) -> str` — cached (see §3 caching rule),
  raising `ZoneNotFoundError`.
- `async def get_record(token, zone_id, fqdn, rtype) -> Record | None` — cached.
- `async def upsert_record(...) -> RecordResult` — returns `unchanged` without
  writing when `content` already matches; otherwise `PATCH` (`records.edit`),
  which preserves `proxied`, `ttl`, `comment`, `tags` and `settings` without
  having to re-send them. Creates via `records.create` only when
  `settings.create_missing_records` is true.
- Map SDK exceptions → domain exceptions:
  `cloudflare.AuthenticationError` → `AuthenticationError`;
  `cloudflare.PermissionDeniedError` → `AuthorizationError`;
  `cloudflare.NotFoundError` → `RecordNotFoundError`;
  `cloudflare.RateLimitError` → `RateLimitedError`;
  `cloudflare.APITimeoutError` / `APIConnectionError` → `UpstreamTimeoutError`;
  `cloudflare.APIStatusError` / `APIError` → `UpstreamError`.

> **Verify against the installed SDK.** The v5 filter argument shape has moved
> between releases (`name="x"` vs. `name={"exact": "x"}`). Before writing this
> module, run:
> ```
> uv run python -c "import cloudflare, inspect; print(inspect.signature(cloudflare.Cloudflare(api_token='x').dns.records.list))"
> uv run python -c "import cloudflare; print([n for n in dir(cloudflare) if n.endswith('Error')])"
> ```
> and use what the installed version actually exposes. If the exact-name filter
> is unavailable, list by `type` + `name` prefix and filter client-side.

Cache: a tiny TTL dict (`dict[str, tuple[float, T]]`) with size bounding — no
external dependency. Key format: `f"{sha256(token)[:16]}:{zone}"`.

**Acceptance:** `tests/test_cloudflare_client.py` uses `respx` to stub
`api.cloudflare.com` and covers: zone found/not found, record found/missing,
unchanged short-circuit (asserts **no** PATCH is issued), successful PATCH,
creation when enabled, each exception mapping, cache hit (asserts a second call
issues no HTTP request), and cache isolation between two different tokens.

#### T1.6 — `src/cloudflare_dyndns/service.py`

`async def perform_update(query: UpdateQuery, token: str, settings: Settings) -> UpdateResponse`.

- Enforce `allowed_zones`.
- Resolve the zone id once.
- Build the work list: for each record × each supplied family.
- Run the per-record work **concurrently** with `asyncio.gather(..., return_exceptions=True)`, bounded by a semaphore of 5.
- **Preserve legacy semantics for the single-record case:** validate that all
  required records exist *before* writing any of them, so a missing AAAA still
  produces a 404 with nothing written (this is the current behaviour and issue
  A9's partial-write hazard).
- Aggregate into `UpdateResponse`; decide `200` vs `207` per §2.2.
- Log one structured line per request: `request_id`, `zone`, `fqdn` list,
  families, per-record action, duration, and outcome. **Never** the token.

**Acceptance:** `tests/test_service.py` covers single-record legacy paths,
multi-record all-success, multi-record partial failure (→ `207`), the
allowlist rejection, and the "validate before write" ordering (a request with a
valid A and a missing AAAA must issue zero PATCH calls).

#### T1.7 — `src/cloudflare_dyndns/ratelimit.py`

In-process token bucket keyed by client IP. Client IP resolution honours
`X-Forwarded-For` **only** when the immediate peer is inside
`CFDD_TRUSTED_PROXIES`; otherwise the peer address is used. Expose an ASGI
middleware. Emit `Retry-After` and `X-RateLimit-*` headers.

Document clearly in `docs/configuration.md` that this is **per-process** and
therefore approximate behind multiple replicas — for the public instance the
real limit belongs at the ingress/Cloudflare layer.

**Acceptance:** `tests/test_ratelimit.py` covers burst allowance, refill over
time (inject a clock), the untrusted-`X-Forwarded-For` case (header ignored),
and the trusted case (header honoured).

#### T1.8 — `src/cloudflare_dyndns/api.py` + `app.py` + `__main__.py`

- `api.py`: two routers — the legacy/JSON router (`GET /`, `GET /healthz`,
  `GET /readyz`) and the dyndns2 router (`GET /nic/update`). Dependencies inject
  `Settings` and the resolved token (query param → `Authorization: Bearer` →
  HTTP Basic password).
- `app.py`: `create_app(settings: Settings | None = None) -> FastAPI` with
  `lifespan` (configure logging, warm nothing, close the shared `httpx` limits
  on shutdown), middleware stack (request-id → logging → rate limit), exception
  handlers, and `docs_url`/`openapi_url` gated on `CFDD_DOCS_ENABLED`.
  Optional `/metrics` mounted when `CFDD_METRICS_ENABLED`.
- `__main__.py`: `main()` reads `Settings`, calls
  `uvicorn.run(create_app(), host=..., port=..., access_log=False, log_config=None)`.
  **No server call at import time** — this fixes A2.

**Acceptance:** `uv run cloudflare-dyndns` serves on `:8080`;
`curl -s localhost:8080/healthz` returns the exact legacy body.

#### T1.9 — Remove the old entry point

Delete root `app.py` and `requirements.txt` in the same commit that makes the
new entry point work, so the tree is never broken.

**Acceptance:** `rg -n "^import CloudFlare|waitress"` returns nothing.

#### T1.10 — Compatibility test suite

`tests/test_api_compat.py` is the guard rail for the live public instance. It
must assert, for the legacy `GET /` endpoint, the **exact** status codes and
**exact** JSON bodies of every row in the §2.1 legacy table, using `respx` to
simulate Cloudflare. Treat a failure here as a release blocker.

**Acceptance:** the file exists, is referenced in `CONTRIBUTING.md` as the
compatibility contract, and passes.

---

### Phase 2 — Container

#### T2.1 — Rewrite `Dockerfile`

Requirements:

- Multi-stage: a `uv` builder stage installing from `uv.lock` with
  `--frozen --no-dev` into `/app/.venv`, then a slim runtime stage that copies
  only the venv and `src/`.
- Base: `python:3.13-slim-bookworm` **pinned by digest** (`@sha256:...`), with a
  comment naming the tag it corresponds to so Dependabot/Renovate can bump it.
- Non-root: create `appuser` (uid/gid `10001`), `USER 10001:10001`.
- `EXPOSE 8080`; `ENV CFDD_PORT=8080 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1`.
- `HEALTHCHECK` hitting `/healthz` (use `python -c` with `urllib`, not `curl` —
  slim has no curl).
- OCI labels: `org.opencontainers.image.{title,description,source,licenses,url,revision,version}` fed by build args.
- `ENTRYPOINT ["cloudflare-dyndns"]`.
- Must run correctly with `--read-only --cap-drop=ALL --security-opt no-new-privileges`.
- Add `.dockerignore` (`.git`, `tests`, `docs`, `helm-chart`, `images`, caches, `*.md` except `README.md`).

**Acceptance:**
```bash
docker build -t cfdd:test .
docker run --rm -d -p 8080:8080 --read-only --cap-drop=ALL --user 10001:10001 --name cfdd cfdd:test
curl -fsS localhost:8080/healthz
docker exec cfdd id -u   # -> 10001
```

#### T2.2 — `compose.yaml`

A minimal, copy-pasteable self-hosting example with the port mapping, the
hardening flags, a `healthcheck`, and commented-out env vars for every setting.

**Acceptance:** `docker compose up -d && curl -fsS localhost:8080/healthz`.

---

### Phase 3 — Helm chart

#### T3.1 — Fix the latent `serviceAccount` bug

Add a `serviceAccount` block to `values.yaml` (`create: true`,
`automount: false`, `annotations: {}`, `name: ""`) and a
`templates/serviceaccount.yaml`; wire `serviceAccountName` into the Deployment.
This closes H1/H2.

#### T3.2 — Harden the Deployment

- Container port `8080`, probes target the named port.
- Defaults:
  ```yaml
  podSecurityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile: { type: RuntimeDefault }
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities: { drop: ["ALL"] }
  resources:
    requests: { cpu: 10m, memory: 64Mi }
    limits:   { memory: 128Mi }        # no CPU limit on purpose
  ```
- `startupProbe` (fast, 30 × 1s) plus tuned liveness/readiness (`readyz` for
  readiness, `healthz` for liveness).
- `topologySpreadConstraints`, `priorityClassName`, `extraEnv`, `envFrom`,
  `extraVolumes`/`extraVolumeMounts` passthroughs.
- `podAnnotations` **and** `podLabels`; a checksum annotation is unnecessary
  (no ConfigMap yet — if one is added for settings, add the checksum too).
- Every `CFDD_*` setting from §3 exposed under a `config:` block in
  `values.yaml`, rendered into container env.

#### T3.3 — Add `hpa.yaml`, `pdb.yaml`, `networkpolicy.yaml`

All gated behind `.enabled` flags, default `false` (except a PDB default of
`false` since `replicaCount` is 1). The NetworkPolicy default-denies egress
except DNS and HTTPS to `0.0.0.0/0` (needed to reach the Cloudflare API), and
ingress only from the ingress controller namespace when configured.

#### T3.4 — Modernise `ingress.yaml`

Drop the `extensions/v1beta1` and `networking.k8s.io/v1beta1` branches; require
Kubernetes ≥ 1.19 via `kubeVersion: ">=1.23.0-0"` in `Chart.yaml`.

#### T3.5 — Chart metadata, schema, docs, tests

- `Chart.yaml`: real `description`, `home`, `sources`, `maintainers`, `icon`,
  `keywords`, `kubeVersion`, and `appVersion` **pinned to the released app
  version** (set by CI at release time, not `latest`).
- `values.schema.json` covering every key with types and enums.
- `templates/NOTES.txt` printing the Update URL the user should paste into their
  FRITZ!Box.
- `helm-chart/ci/*.yaml` fixtures for `ct lint`.
- `templates/tests/test-connection.yaml` — a `helm test` hook that curls
  `/healthz`.
- `helm-chart/README.md` generated by `helm-docs`.

**Acceptance:**
```bash
helm lint helm-chart
helm template t helm-chart -f helm-chart/ci/full-values.yaml | kubectl apply --dry-run=client -f -
ct lint --charts helm-chart
```

---

### Phase 4 — CI/CD and supply chain

> **Pin every action to a full commit SHA** with a trailing `# vX.Y.Z` comment.
> Dependabot's `github-actions` ecosystem will keep them current.

#### T4.1 — `.github/workflows/ci.yml`

Triggers: `pull_request`, `push` to `main`. Jobs:

1. **lint** — `uv run ruff check .` + `uv run ruff format --check .`
2. **typecheck** — `uv run mypy`
3. **test** — matrix `python-version: ["3.11", "3.12", "3.13"]`, `uv run pytest`,
   upload coverage; **fail under 90 %** (already enforced in `pyproject.toml`)
4. **docker** — build **without** pushing (`push: false`, `load: true`), then
   run the smoke test from T2.1
5. **helm** — `helm lint` + `ct lint` + `helm template | kubectl apply --dry-run`
6. **hadolint** on the `Dockerfile`
7. **trivy** filesystem scan, `exit-code: 1` on HIGH/CRITICAL

Use `astral-sh/setup-uv` with caching keyed on `uv.lock`.
Set `permissions: contents: read` at the workflow level.
Add `concurrency: group: ci-${{ github.ref }}, cancel-in-progress: true`.

#### T4.2 — Fix the publish triggers (**highest-value CI fix**)

Delete `docker-build-push.yml` and `helmchart-push.yml` in their current form.
Publishing must happen **only** on:

- push to `main` → tags `edge` and `sha-<short-sha>`
- git tag `v*` → tags `X.Y.Z`, `X.Y`, `X`, `latest`

This ends the current situation where any branch push overwrites `:latest`.

#### T4.3 — `.github/workflows/release.yml`

Triggered by `v*` tags (and a `workflow_dispatch`). Steps:

1. Derive the version from the tag; write it into `pyproject.toml`'s `version`
   at build time (or use `hatch-vcs`).
2. Build and push the multi-arch image (`linux/amd64`, `linux/arm64`,
   `linux/arm/v7`) via `docker/build-push-action` with:
   - `provenance: mode=max`, `sbom: true`
   - tags from `docker/metadata-action`
   - build args feeding the OCI labels
   - GHA layer cache
3. Sign the image with **cosign keyless** (OIDC), and attest the SBOM.
4. Package and push the Helm chart with `version` = tag version and
   `appVersion` = tag version. Remove the bogus `--kube-as-user/--kube-token`
   flags (P6). Sign the chart with cosign too.
5. Create the GitHub Release with notes generated by `release-drafter` or
   `git-cliff` from Conventional Commits, and attach the chart `.tgz`.

> **Decision to confirm with the maintainer:** whether to adopt fully automated
> semantic-release (tag created by CI from commit messages) or keep tagging
> manual. This plan assumes **manual tagging, automated everything else** — the
> safer default for a project with live users. If automated releases are wanted
> later, add `release-please` in a follow-up.

#### T4.4 — `.github/workflows/codeql.yml` and `scan.yml`

- CodeQL for `python` on PR, `main`, and a weekly schedule.
- `scan.yml`: nightly Trivy **image** scan of `ghcr.io/l480/cloudflare-dyndns:latest`,
  uploading SARIF to code scanning, so a newly-disclosed base-image CVE opens an
  alert without needing a commit.
- Enable in repo settings (manual, note it in the PR description): private
  vulnerability reporting, secret scanning + push protection, Dependabot alerts,
  and required status checks on `main`.

#### T4.5 — `CHANGELOG.md`

Seed with a `## [Unreleased]` section and an entry for `1.0.0` describing this
refactor, in Keep-a-Changelog format. Add a `BREAKING CHANGES` subsection
listing the container port change `80 → 8080` — **this is the one change that
affects existing self-hosters** and must be prominent in the release notes and
the README.

---

### Phase 5 — Documentation

#### T5.1 — Rewrite `README.md`

Sections, in order: badges (CI, image, chart, licence) → what it is → quick
start (Docker one-liner, compose, Helm) → the free hosted instance → Cloudflare
token creation (keep the existing screenshot) → FRITZ!Box configuration table
(keep, it is the main audience) → **security notes** (token in URL, use HTTPS,
scope the token narrowly, prefer self-hosting for sensitive zones) → link out to
`docs/`.

Keep the existing FRITZ!Box table content — it is correct and is what users
copy from.

#### T5.2 — `docs/`

- `configuration.md` — the full §3 table, generated-by-hand but kept in sync;
  add a test that every `Settings` field appears in the doc (cheap `rg` check in CI).
- `api.md` — the full §2 contract, including the dyndns2 endpoint.
- `clients.md` — FRITZ!Box (with a troubleshooting section for issue #36:
  check that the router actually fires — the service now logs every request, so
  "no log line" proves the router never called; also cover the FRITZ!Box
  "Domain Name" field needing to resolve, and proxied/orange-cloud records
  confusing the router's own IP check), plus `ddclient`, `inadyn`, `curl`, and a
  cron one-liner.
- `deployment.md` — Docker, compose, Kubernetes/Helm, reverse-proxy notes
  (TLS termination, `X-Forwarded-For`, `CFDD_TRUSTED_PROXIES`).

#### T5.3 — Delete `plan.md`

Once every phase is merged, remove this file in the final commit.

---

### Phase 6 — Backlog (issue-driven, after the refactor lands)

| Task | Issue | Notes |
|---|---|---|
| B1 — Multiple records per request | #35, PR #20 | Already specified in §2.2 and delivered in T1.6. Close #35; thank the PR author on #20 and note the feature shipped. |
| B2 — Troubleshooting docs + logging | #36 | Delivered by T1.2 + T5.2. Ask the reporter to re-test on the new image and share log lines. |
| B3 — IPv6 prefix-only updates | #29 | **Design needed.** Accept `ipv6prefix` (e.g. `2001:db8:1234:5600::/56`), and for each configured record recombine the stored suffix (host bits) with the new prefix. Requires storing or deriving the interface identifier from the record's current value. Implement as a separate `records[]` config or a `suffix=` parameter. Ship after 1.0. |
| B4 — Cloudflare Access IP allowlisting | #32 | Out of scope. Would need a different token scope and a different API surface. Keep open with a `wontfix-for-now`/`help wanted` label and an explanation. |
| B5 — Optional Redis-backed rate limiting | — | Only if the public instance actually needs cross-replica limits. |
| B6 — Prometheus metrics dashboard | — | Ship a Grafana dashboard JSON once `/metrics` has real traffic. |

---

## 5. Execution order & PR strategy

Land these as separate PRs, in order. Each must be green in CI before the next
starts.

| PR | Contents | Risk |
|---|---|---|
| 1 | T0.1 – T0.4 (tooling, hygiene, dependabot) | none — no runtime change |
| 2 | T4.1 (`ci.yml`) + T4.2 (fix publish triggers) | **do this early**; it stops branch pushes from clobbering `:latest` |
| 3 | T1.1 – T1.4 (config, logging, errors, models) + their tests | none — not yet wired |
| 4 | T1.5 – T1.7 (cloudflare client, service, ratelimit) + tests | none — not yet wired |
| 5 | T1.8 – T1.10 (app wiring, delete old entry point, compat tests) | **high** — this is the cutover |
| 6 | T2.1 – T2.2 (container) | **medium** — port 80 → 8080 is user-visible |
| 7 | T3.1 – T3.5 (Helm chart) | medium |
| 8 | T4.3 – T4.5 (release, scanning, changelog) | low |
| 9 | T5.1 – T5.3 (docs, delete this file) | none |
| 10 | Tag `v1.0.0`, verify the published image and chart, close #35, comment on #20, #36, #29, #32 | — |

**Before PR 5 is merged**, deploy the new image to a staging host and point a
throwaway FRITZ!Box (or a `curl` loop reproducing its exact request) at it for
at least one real IP change.

---

## 6. Definition of done

- [ ] `uv run ruff check . && uv run ruff format --check .` clean
- [ ] `uv run mypy` clean under `strict`
- [ ] `uv run pytest` green, coverage ≥ 90 %
- [ ] `tests/test_api_compat.py` proves every legacy response is byte-identical
- [ ] No token, in any form, appears in any log line (test-enforced)
- [ ] `docker build` produces a multi-arch image that runs as uid 10001 with a read-only root filesystem
- [ ] `helm lint`, `ct lint`, and a `--dry-run` apply all pass for both CI values files
- [ ] Images are published **only** from `main` and tags, are signed, and carry an SBOM + provenance
- [ ] `README.md` documents self-hosting configuration and the port change
- [ ] `CHANGELOG.md` records the `80 → 8080` breaking change prominently
- [ ] Open issues #35 and #36 are resolved or answered; #29 and #32 carry a decision
- [ ] `plan.md` is deleted

---

## 7. Notes for the implementing agent

1. **Do not change the legacy `GET /` JSON strings.** Real routers are pointed
   at the public instance right now. `tests/test_api_compat.py` is the contract.
2. **Verify SDK call shapes against the installed version** before writing
   `cloudflare_client.py` (see the box in T1.5). Do not copy signatures from
   this document without checking — they were written against the docs, not
   against a pinned build.
3. **Never log the token**, never put it in a cache key un-hashed, never echo an
   upstream error body without passing it through the redaction filter.
4. **Prefer `PATCH` (`records.edit`) over `PUT` (`records.update`)** so
   `proxied`, `ttl`, `comment`, `tags` and `settings` survive an update
   untouched. This also fixes A8.
5. Keep modules small and each function's responsibility single. If a module
   passes ~200 lines, split it.
6. Write the test in the same commit as the code it covers.
7. If a task turns out to be wrong or blocked, **stop and report** rather than
   improvising a different architecture — the phases depend on each other.
