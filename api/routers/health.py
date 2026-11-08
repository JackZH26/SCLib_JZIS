"""Process, dependency, and data-health endpoints with separate semantics."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from models.health import DataComponentHealth, DataHealth, DependencyHealth, LiveHealth
from routers.discovery import get_discovery_feed_health
from services.health import collect_database_data_health, collect_dependency_health

router = APIRouter(tags=["health"])
_NO_STORE_HEADERS = {"Cache-Control": "no-store"}


def _model_response(model, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=model.model_dump(mode="json"),
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


@router.get("/livez", response_model=LiveHealth, include_in_schema=False)
async def livez() -> JSONResponse:
    """Process liveness only; never touch downstream services."""
    return _model_response(LiveHealth())


@router.get("/v1/health", response_model=LiveHealth)
async def legacy_health() -> JSONResponse:
    """Backward-compatible alias for the original liveness endpoint."""
    return _model_response(LiveHealth())


async def _dependency_response() -> JSONResponse:
    health = await collect_dependency_health()
    return _model_response(
        health,
        status_code=200 if health.status == "ok" else 503,
    )


@router.get(
    "/readyz",
    response_model=DependencyHealth,
    responses={503: {"description": "A required dependency is unavailable"}},
    include_in_schema=False,
)
async def readyz() -> JSONResponse:
    """Readiness gates traffic on bounded PostgreSQL and Redis probes."""
    return await _dependency_response()


@router.get(
    "/v1/health/dependencies",
    response_model=DependencyHealth,
    responses={503: {"description": "A required dependency is unavailable"}},
)
async def dependency_health() -> JSONResponse:
    return await _dependency_response()


@router.get(
    "/v1/health/data",
    response_model=DataHealth,
    responses={503: {"description": "Data health could not query PostgreSQL"}},
)
async def data_health() -> JSONResponse:
    database_result, discovery_result = await asyncio.gather(
        collect_database_data_health(),
        get_discovery_feed_health(),
        return_exceptions=True,
    )
    checked_at = datetime.now(UTC)
    components: dict[str, DataComponentHealth] = {}

    if isinstance(database_result, Exception):
        components["database"] = DataComponentHealth(status="unavailable")
        overall_status = "unavailable"
    else:
        components.update(database_result)
        overall_status = "ok"

    if isinstance(discovery_result, Exception):
        components["discovery"] = DataComponentHealth(status="invalid")
    else:
        components["discovery"] = DataComponentHealth(
            status=discovery_result["status"],
            updated_at=discovery_result["updated_at"],
            details={
                "candidate_count": discovery_result["candidate_count"],
                "size_bytes": discovery_result["size_bytes"],
                "cache": discovery_result["cache"],
            },
        )

    healthy_component_states = {"ready", "complete"}
    if overall_status != "unavailable" and any(
        component.status not in healthy_component_states
        for component in components.values()
    ):
        overall_status = "degraded"

    health = DataHealth(
        status=overall_status,
        checked_at=checked_at,
        components=components,
    )
    return _model_response(
        health,
        status_code=503 if overall_status == "unavailable" else 200,
    )
