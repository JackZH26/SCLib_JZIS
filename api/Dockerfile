# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: build tools for psycopg2, curl for healthchecks, tini for PID 1
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reproducible installs
RUN pip install uv

WORKDIR /app

# Install dependencies first for better layer caching
COPY pyproject.toml ./
RUN uv pip install --system -e .

# GIT_SHA is the short commit hash surfaced on /version so operators
# (and the frontend Footer) can confirm what code is running. Falls
# back to "dev" for local builds; production deploys export the real
# SHA via docker-compose's args block.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

# Copy application code
COPY . .
RUN chmod +x /app/entrypoint.sh

# Drop privileges. The API has no reason to run as root — it only
# needs to read /app, write logs to stdout, and read the mounted
# ADC credential at /credentials/gcp-sa.json (mode 0644 on the host
# side). Creating a fixed UID lets the host mount honour ownership
# checks without a chown step.
RUN groupadd --system --gid 1001 sclib \
 && useradd  --system --uid 1001 --gid sclib --home /app sclib \
 && chown -R sclib:sclib /app
USER sclib

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
