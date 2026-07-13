"""Liveness, readiness, dependency, and non-gating data health."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from models.db import StatsCache, TimelineProjectionState
from models.health import DataComponentHealth, DependencyCheck, DependencyHealth
from routers import health as health_router
from services import health


async def test_timed_probe_bounds_failures_and_hides_exception_details():
    async def ok():
        return None

    async def broken():
        raise RuntimeError("secret internal topology")

    async def slow():
        await asyncio.sleep(0.05)

    assert (await health._timed_probe(ok)).status == "ok"
    assert (await health._timed_probe(broken)).status == "error"
    assert (
        await health._timed_probe(slow, timeout_seconds=0.001)
    ).status == "error"


async def test_required_dependency_failure_makes_readiness_unavailable(monkeypatch):
    async def ok():
        return None

    async def broken():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(health, "_check_postgres", ok)
    monkeypatch.setattr(health, "_check_redis", broken)

    result = await health.collect_dependency_health()

    assert result.status == "unavailable"
    assert result.dependencies["postgres"].status == "ok"
    assert result.dependencies["redis"].status == "error"
    assert "redis unavailable" not in result.model_dump_json()


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):  # noqa: ARG002
        return False

    async def get(self, model, key):
        if model is StatsCache and key == "dashboard":
            return SimpleNamespace(
                value={
                    "last_ingest_at": "2026-07-12T10:00:00+00:00",
                    "dataset_version": "v2026.07.12",
                    "total_papers": 100,
                    "total_materials": 20,
                    "total_chunks": 1000,
                },
                updated_at=datetime(2026, 7, 13, 1, tzinfo=UTC),
            )
        if model is StatsCache and key == "data_pipeline":
            return SimpleNamespace(value={
                "status": "complete",
                "last_run_at": "2026-07-13T00:30:00Z",
                "stages": {
                    "aggregate": {"status": "complete", "exit_code": 0},
                },
            })
        if model is TimelineProjectionState and key == 1:
            return SimpleNamespace(
                schema_version=1,
                source_year=datetime.now(UTC).year,
                refreshed_at=datetime(2026, 7, 13, 1, 30, tzinfo=UTC),
                material_count=20,
                active_point_count=200,
            )
        return None


class _FakeFactory:
    def __call__(self):
        return _FakeSession()


async def test_data_health_reports_metadata_without_age_thresholds(monkeypatch):
    monkeypatch.setattr(health, "get_session_factory", lambda: _FakeFactory())

    components = await health.collect_database_data_health()

    assert components["stats"].status == "ready"
    assert components["dataset"].status == "ready"
    assert components["dataset"].details["dataset_version"] == "v2026.07.12"
    assert components["pipeline"].status == "complete"
    assert components["timeline_projection"].status == "ready"
    assert "age" not in components["dataset"].details


async def test_health_routes_use_distinct_status_codes(monkeypatch):
    live_response = await health_router.livez()
    assert live_response.status_code == 200
    assert json.loads(live_response.body)["status"] == "ok"

    unavailable = DependencyHealth(
        status="unavailable",
        checked_at=datetime.now(UTC),
        dependencies={
            "postgres": DependencyCheck(status="error", latency_ms=2),
            "redis": DependencyCheck(status="ok", latency_ms=1),
        },
    )

    async def dependency_failure():
        return unavailable

    monkeypatch.setattr(health_router, "collect_dependency_health", dependency_failure)
    ready_response = await health_router.readyz()
    assert ready_response.status_code == 503
    assert ready_response.headers["cache-control"] == "no-store"


async def test_data_health_is_degraded_not_unready_for_missing_data(monkeypatch):
    async def database_components():
        return {
            "stats": DataComponentHealth(status="ready"),
            "dataset": DataComponentHealth(status="missing"),
            "pipeline": DataComponentHealth(status="unknown"),
        }

    async def discovery_component():
        return {
            "status": "ready",
            "updated_at": None,
            "candidate_count": 0,
            "size_bytes": 100,
            "cache": "HIT",
        }

    monkeypatch.setattr(
        health_router,
        "collect_database_data_health",
        database_components,
    )
    monkeypatch.setattr(
        health_router,
        "get_discovery_feed_health",
        discovery_component,
    )

    response = await health_router.data_health()
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["status"] == "degraded"


async def test_http_health_contracts_are_reachable(monkeypatch):
    ready = DependencyHealth(
        status="ok",
        checked_at=datetime.now(UTC),
        dependencies={
            "postgres": DependencyCheck(status="ok", latency_ms=1),
            "redis": DependencyCheck(status="ok", latency_ms=1),
        },
    )

    async def dependency_success():
        return ready

    monkeypatch.setattr(health_router, "collect_dependency_health", dependency_success)
    app = FastAPI()
    app.include_router(health_router.router)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        live_response = await client.get("/livez")
        ready_response = await client.get("/readyz")
        detail_response = await client.get("/v1/health/dependencies")

    assert live_response.status_code == 200
    assert ready_response.status_code == 200
    assert detail_response.status_code == 200
    assert ready_response.json()["dependencies"]["postgres"]["status"] == "ok"
