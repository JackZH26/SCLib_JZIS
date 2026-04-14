# syntax=docker/dockerfile:1.7
# Ingestion runner. Shares no code with api/ — imports only from its own
# package — so it can be built and run independently (e.g. as a one-shot
# cron job via `docker compose run --rm ingestion sclib-ingest --mode ...`).
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

WORKDIR /app

# Install third-party deps first (cache-friendly), then copy the package
# source and install the project itself non-editable. We avoid -e because
# uv + hatch editable installs don't always wire up the top-level
# `ingestion` package on sys.path inside a container.
COPY pyproject.toml ./
COPY ingestion ./ingestion
RUN uv pip install --system .

# Default: no-op. Compose / CI override this with an explicit `sclib-ingest`
# invocation.
ENTRYPOINT ["sclib-ingest"]
CMD ["--mode", "smoke", "--limit", "30"]
