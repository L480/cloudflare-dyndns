# syntax=docker/dockerfile:1

# python:3.13-slim-bookworm, pinned by digest for reproducible builds.
# Bump by re-resolving the tag and updating both the digest and this comment.
ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8

# DL3006 is a false positive here: hadolint can't resolve the digest
# through the ARG substitution above, but PYTHON_IMAGE is pinned by digest.
# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE} AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PIP_NO_CACHE_DIR=1

# build-essential is needed here (but not in the runtime stage) because
# uvicorn[standard]'s C-extension deps (httptools, uvloop) have no
# prebuilt wheels for linux/arm/v7 (and sometimes linux/arm64 depending on
# the Python version), so `uv sync` falls back to compiling them from
# source under QEMU emulation during the multi-arch release build.
# DL3008 is intentionally not followed: build-essential is a metapackage
# discarded with this stage, never shipped in the runtime image, so
# pinning it to a Debian point-release buys no meaningful reproducibility.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.8.17

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra metrics

COPY src/ src/
COPY README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra metrics

# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE} AS runtime

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=0.0.0

LABEL org.opencontainers.image.title="cloudflare-dyndns" \
      org.opencontainers.image.description="Cloudflare DynDNS middleware for AVM FRITZ!Box and other DynDNS clients" \
      org.opencontainers.image.source="https://github.com/l480/cloudflare-dyndns" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.url="https://github.com/l480/cloudflare-dyndns" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"

RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/src /app/src

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CFDD_PORT=8080

EXPOSE 8080
USER 10001:10001

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]

ENTRYPOINT ["cloudflare-dyndns"]
