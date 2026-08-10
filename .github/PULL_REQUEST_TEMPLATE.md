## Summary

<!-- What does this PR change, and why? -->

## Test plan

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest`
- [ ] `tests/test_api_compat.py` still passes unmodified (or the legacy
      contract change is deliberate and called out below)
- [ ] `docker build` succeeds, if the Dockerfile changed
- [ ] `helm lint helm-chart`, if the chart changed

## Breaking changes

<!-- Anything that changes the legacy `GET /` contract, the container port,
     or default configuration must be called out explicitly here. -->
