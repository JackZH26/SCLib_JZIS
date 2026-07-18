# syntax=docker/dockerfile:1.7
# Ingestion runner. Shares no code with api/ — imports only from its own
# package — so it can be built and run independently (e.g. as a one-shot
# cron job via `docker compose run --rm ingestion sclib-ingest --mode ...`).
FROM python:3.11-slim AS base

# uv 0.11.16 multi-platform image index, pinned by digest.
COPY --from=ghcr.io/astral-sh/uv@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the exact locked graph before copying frequently changing source.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY ingestion ./ingestion
# Ingestion runs exclusively from /opt/venv. Package managers are build-time
# tools and must not carry their vendored dependencies into production.
RUN uv sync --locked --no-dev --no-editable \
 && rm -rf \
      /root/.cache/uv \
      /usr/local/lib/python3.11/site-packages/pip* \
      /usr/local/lib/python3.11/site-packages/setuptools* \
      /usr/local/lib/python3.11/site-packages/wheel* \
 && rm -f /usr/local/bin/pip* /bin/uv /bin/uvx

# Non-root runtime. Shared UID 1001 matches the API image so the host identity
# agent can grant both workloads narrowly scoped token-file read access.
RUN groupadd --system --gid 1001 sclib \
 && useradd  --system --uid 1001 --gid sclib --home /app sclib \
 && chown -R sclib:sclib /app
USER sclib

# No ENTRYPOINT — callers pick the console script explicitly so the
# same image serves both `sclib-ingest` (nightly cron) and
# `sclib-import-nims` (one-shot NIMS CSV loader) without awkward
# --entrypoint overrides. Default CMD runs the Phase 2 smoke test.
CMD ["sclib-ingest", "--mode", "smoke", "--limit", "30"]
