"""Public v1 request correlation, errors, quota, and OpenAPI contract."""
from __future__ import annotations

import re

import pytest

from main import app


@pytest.mark.asyncio
async def test_success_response_echoes_safe_request_id_and_api_version(client) -> None:
    response = await client.get("/livez", headers={"X-Request-ID": "client.trace-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "client.trace-123"
    assert response.headers["x-api-version"] == "1"


@pytest.mark.asyncio
async def test_unsafe_request_id_is_replaced(client) -> None:
    response = await client.get("/livez", headers={"X-Request-ID": "../../bad id"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "../../bad id"
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


@pytest.mark.asyncio
async def test_http_error_preserves_detail_and_adds_correlation(client) -> None:
    response = await client.get("/v1/paper/arxiv:missing-contract-test")
    body = response.json()

    assert response.status_code == 404
    assert body["detail"] == "Paper 'arxiv:missing-contract-test' not found"
    assert body["error_code"] == "not_found"
    assert body["request_id"] == response.headers["x-request-id"]
    assert response.headers["x-api-version"] == "1"


@pytest.mark.asyncio
async def test_validation_error_uses_stable_envelope_without_echoing_input(client) -> None:
    response = await client.post(
        "/v1/search",
        json={"query": "x", "filters": {"year_min": 1800}},
    )
    body = response.json()

    assert response.status_code == 422
    assert body["error_code"] == "validation_error"
    assert body["request_id"] == response.headers["x-request-id"]
    assert isinstance(body["detail"], list)
    assert all("input" not in error and "ctx" not in error for error in body["detail"])


@pytest.mark.asyncio
async def test_public_data_endpoints_reject_unknown_schema_versions(client) -> None:
    for path in (
        "/v1/timeline?schema_version=2",
        "/v1/discovery/candidates?schema_version=2",
    ):
        response = await client.get(path)
        assert response.status_code == 422
        assert response.json()["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_timeline_accepts_documented_point_budget_from_query_string(client) -> None:
    response = await client.get(
        "/v1/timeline?schema_version=1&max_points=5000&compact=true&limit=5000"
    )

    assert response.status_code == 200
    assert response.json()["limit"] == 5000


def test_openapi_v1_publishes_error_and_quota_contract() -> None:
    schema = app.openapi()

    assert schema["info"]["version"] == "1.0.0"
    error_schema = schema["components"]["schemas"]["ApiErrorResponse"]
    assert set(error_schema["required"]) == {"detail", "error_code", "request_id"}
    search_schema = schema["components"]["schemas"]["SearchResponse"]
    ask_schema = schema["components"]["schemas"]["AskResponse"]
    assert "remaining" in search_schema["properties"]
    assert "remaining" in ask_schema["properties"]
    assert schema["paths"]["/v1/search"]["post"]["responses"]["422"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiErrorResponse"
    }
    timeline_params = {
        parameter["name"]
        for parameter in schema["paths"]["/v1/timeline"]["get"]["parameters"]
    }
    discovery_params = {
        parameter["name"]
        for parameter in schema["paths"]["/v1/discovery/candidates"]["get"][
            "parameters"
        ]
    }
    assert {"offset", "limit", "schema_version"} <= timeline_params
    assert {"offset", "limit", "schema_version"} <= discovery_params
