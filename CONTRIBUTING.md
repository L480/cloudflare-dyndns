# Contributing

Thanks for considering a contribution to `cloudflare-dyndns`.

## Development setup

This project uses [`uv`](https://docs.astral.sh/uv/) for environment,
dependency and lock-file management.

```bash
uv sync --all-extras --dev
uv run pre-commit install   # optional but recommended
```

Run the app locally:

```bash
uv run cloudflare-dyndns
# or
uv run python -m cloudflare_dyndns
```

## Before opening a PR

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

All four must pass; CI enforces the same checks plus a Docker build smoke
test, `helm lint`, `hadolint`, and a Trivy filesystem scan.

## The compatibility contract

`tests/test_api_compat.py` pins the exact status codes and JSON bodies of
the legacy `GET /` endpoint. The public instance
(`https://dyndns.nicoo.org/`) has real FRITZ!Box routers pointed at it
today — **a failing compat test is a release blocker, not something to
adjust the test for.** If you need to change legacy behaviour, that's a
deliberate, called-out breaking change, not a passive test update.

## Conventional Commits

Commit messages should follow
[Conventional Commits](https://www.conventionalcommits.org/) (`feat:`,
`fix:`, `refactor:`, `chore:`, `docs:`, `test:`, `ci:`, `build:`) — this
feeds the auto-generated release notes.

## Code style

- Keep modules small; if one passes ~200 lines, consider splitting it.
- Ruff (lint + format) and `mypy --strict` are both non-negotiable in CI.
- Write the test in the same commit as the code it covers.
