"""Discovery snapshot caching, pagination, details, and conditional reads."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from routers.discovery import (
    DiscoveryFeedStore,
    _store,
    discovery_candidate_detail,
    discovery_candidates,
    discovery_metadata,
)


def _request(path: str, if_none_match: str | None = None) -> Request:
    headers = []
    if if_none_match:
        headers.append((b"if-none-match", if_none_match.encode()))
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("api.jzis.org", 443),
        "scheme": "https",
    })


def _candidate(candidate_id: str, role: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "formula": candidate_id.upper(),
        "branch": "test-branch",
        "record_role": role,
        "evidence_level": "E3",
        "checker_status": "pass",
        "public_confidence": "DFT-screened lead",
        "review_summary": f"Detailed review for {candidate_id}",
        "risk_tags": ["test-risk"],
    }


def _write_feed(path: Path, candidates: list[dict]) -> None:
    path.write_text(
        json.dumps({
            "page_title": "Reviewed Leads",
            "intro": ["Reviewed feed"],
            "status": "active",
            "updated_at_utc": "2026-07-13T00:00:00Z",
            "source": "test",
            "filter_rules": [{"key": "reviewed", "label": "Review", "value": "Required"}],
            "candidates": candidates,
        }),
        encoding="utf-8",
    )


async def test_store_reuses_snapshot_until_file_signature_changes(tmp_path: Path):
    path = tmp_path / "feed.json"
    _write_feed(path, [_candidate("lead-1", "exploratory_candidate")])
    store = DiscoveryFeedStore()

    first, first_status = await store.get(path)
    second, second_status = await store.get(path)

    assert first_status == "MISS"
    assert second_status == "HIT"
    assert second is first
    assert first.metadata.total_candidates == 1

    _write_feed(path, [
        _candidate("lead-1", "exploratory_candidate"),
        _candidate("control-1", "benchmark_control"),
    ])
    third, third_status = await store.get(path)

    assert third_status == "MISS"
    assert third is not first
    assert third.metadata.total_candidates == 2
    assert third.metadata.role_counts == {
        "exploratory_candidate": 1,
        "benchmark_control": 1,
    }


async def test_additive_endpoints_page_filter_and_lazy_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = tmp_path / "feed.json"
    _write_feed(path, [
        _candidate("lead-1", "exploratory_candidate"),
        _candidate("lead-2", "exploratory_candidate"),
        _candidate("control-1", "benchmark_control"),
    ])
    monkeypatch.setenv("SCLIB_DISCOVERY_FEED_PATH", str(path))
    _store.clear()

    metadata_response = await discovery_metadata(_request("/v1/discovery/metadata"), None)  # type: ignore[arg-type]
    metadata = json.loads(metadata_response.body)
    assert metadata_response.headers["x-discovery-cache"] == "MISS"
    assert metadata["total_candidates"] == 3

    page_response = await discovery_candidates(
        _request("/v1/discovery/candidates"),
        offset=0,
        limit=1,
        record_role="exploratory_candidate",
        identity=None,  # type: ignore[arg-type]
    )
    page = json.loads(page_response.body)
    assert page_response.headers["x-discovery-cache"] == "HIT"
    assert page["total"] == 2
    assert page["has_more"] is True
    assert page["items"][0]["candidate_id"] == "lead-1"
    assert "review_summary" not in page["items"][0]

    detail_response = await discovery_candidate_detail(
        _request("/v1/discovery/candidates/lead-1"),
        candidate_id="lead-1",
        identity=None,  # type: ignore[arg-type]
    )
    detail = json.loads(detail_response.body)
    assert detail["review_summary"] == "Detailed review for lead-1"
    assert detail["risk_tags"] == ["test-risk"]

    etag_response = await discovery_metadata(
        _request("/v1/discovery/metadata", metadata_response.headers["etag"]),
        None,  # type: ignore[arg-type]
    )
    assert etag_response.status_code == 304
    assert etag_response.body == b""

    with pytest.raises(HTTPException) as exc_info:
        await discovery_candidate_detail(
            _request("/v1/discovery/candidates/missing"),
            candidate_id="missing",
            identity=None,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404
    _store.clear()
