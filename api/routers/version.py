"""GET /version — site code revision + data snapshot version.

Mirrors how Materials Project exposes both a website hash and a
database calver, so SCLib clients (the footer, third-party scripts,
the upcoming jzis-sclib Python client) can fingerprint the running
deployment without scraping HTML.

`site_version` is the short Git SHA baked into the API image at
`docker compose build` time via the GIT_SHA build arg (see
docker-compose.yml + api/Dockerfile). `dataset_version` is read from
the same `stats_cache['dashboard']` row that powers GET /stats, so
it always agrees with whatever the dashboard shows.

Public, unauthenticated, cheap (single PK lookup). No rate limit
applied — operators and uptime monitors should be able to poll.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import StatsCache

router = APIRouter(tags=["version"])


# Read once at import time. The GIT_SHA env var is set by the
# Dockerfile's `ENV GIT_SHA=$GIT_SHA` line; missing in dev shells →
# falls back to "dev" so /version still answers.
SITE_VERSION = os.environ.get("GIT_SHA", "dev")
# Bumped whenever the public REST contract changes in a non-additive
# way. Distinct from the API package version reported by FastAPI's
# OpenAPI doc — that one tracks the codebase, this one tracks the
# wire format clients depend on.
API_VERSION = "1"


class VersionResponse(BaseModel):
    site_version: str
    dataset_version: str | None
    api_version: str


@router.get("/version", response_model=VersionResponse)
async def version(db: AsyncSession = Depends(get_db)) -> VersionResponse:
    cached = await db.get(StatsCache, "dashboard")
    dataset_version: str | None = None
    if cached is not None and isinstance(cached.value, dict):
        v = cached.value.get("dataset_version")
        if isinstance(v, str):
            dataset_version = v

    return VersionResponse(
        site_version=SITE_VERSION,
        dataset_version=dataset_version,
        api_version=API_VERSION,
    )
