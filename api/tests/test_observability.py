"""Metrics exposure and privacy-minimized browser telemetry contracts."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from main import app


@pytest.mark.asyncio
async def test_metrics_endpoint_is_internal_no_store_and_low_cardinality(client) -> None:
    await client.get("/livez")
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/plain; version=")
    assert "sclib_http_requests_total" in response.text
    assert 'route="/livez"' in response.text
    assert "/metrics" not in app.openapi()["paths"]


@pytest.mark.asyncio
async def test_client_telemetry_accepts_only_bounded_aggregate_events(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "routers.observability._within_budget",
        AsyncMock(return_value=True),
    )
    response = await client.post(
        "/v1/telemetry/client",
        json={
            "event_type": "web_vital",
            "name": "LCP",
            "value": 1240.5,
            "rating": "good",
        },
    )

    assert response.status_code == 202
    assert response.headers["x-api-version"] == "1"
    metrics = (await client.get("/metrics")).text
    assert (
        'sclib_client_events_total{event_type="web_vital",name="LCP",rating="good"}'
        in metrics
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"event_type": "web_vital", "name": "LCP"},
        {"event_type": "js_error", "name": "LCP"},
        {"event_type": "js_error", "name": "error", "value": 1},
        {
            "event_type": "unhandled_rejection",
            "name": "rejection",
            "message": "must never be accepted",
        },
    ],
)
async def test_client_telemetry_rejects_identifying_or_mismatched_fields(
    client,
    payload,
) -> None:
    response = await client.post("/v1/telemetry/client", json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_client_telemetry_fails_closed_when_rate_budget_is_unavailable(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "routers.observability._within_budget",
        AsyncMock(return_value=False),
    )
    response = await client.post(
        "/v1/telemetry/client",
        json={"event_type": "js_error", "name": "error"},
    )

    assert response.status_code == 202


def test_openapi_documents_bounded_client_telemetry_only() -> None:
    schema = app.openapi()
    model = schema["components"]["schemas"]["ClientTelemetryEvent"]

    assert model["additionalProperties"] is False
    assert set(model["properties"]) == {"event_type", "name", "value", "rating"}
    assert "/v1/telemetry/client" in schema["paths"]
