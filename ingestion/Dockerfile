# syntax=docker/dockerfile:1.7
# Ingestion runner. Shares no code with api/ — imports only from its own
# package — so it can be built and run independently (e.g. as a one-shot
# cron job via `docker compose run --rm ingestion sclib-ingest --mode ...`).
# Keep the tested Python 3.11.16/trixie index fixed; install OS fixes below.
FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e AS base

# uv 0.11.16 multi-platform image index, pinned by digest.
COPY --from=ghcr.io/astral-sh/uv@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    PATH="/opt/venv/bin:$PATH"

# Refresh base PCRE2 and fail if mirrors lack the CVE-2026-103111 fix.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpcre2-8-0 \
        libpq-dev \
        curl \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libpcre2-8-0)" ge '10.46-1~deb13u3' \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the exact locked graph before copying frequently changing source.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# Install the hash-verified tokenizer ranks before the non-root offline check.
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

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
RUN --network=none python -c "import tiktoken; assert tiktoken.get_encoding('cl100k_base').encode('SCLib')"

# No ENTRYPOINT — callers pick the console script explicitly so the
# same image serves both `sclib-ingest` (nightly cron) and
# `sclib-import-nims` (one-shot NIMS CSV loader) without awkward
# --entrypoint overrides. Default CMD runs the Phase 2 smoke test.
CMD ["sclib-ingest", "--mode", "smoke", "--limit", "30"]
