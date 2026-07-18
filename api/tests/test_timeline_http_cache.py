"""Timeline cache keys and HTTP conditional response behavior."""
from __future__ import annotations

from datetime import UTC, datetime

from starlette.requests import Request

from models.search import TimelineCoverage, TimelinePoint, TimelineResponse
from routers.timeline import (
    _cache_key,
    _evenly_sample,
    _http_response,
    _serialize_timeline,
    _timeline_response,
    _weak_etag,
)


def _request(
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> Request:
    headers = []
    if if_none_match:
        headers.append((b"if-none-match", if_none_match.encode()))
    if if_modified_since:
        headers.append((b"if-modified-since", if_modified_since.encode()))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/v1/timeline",
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("api.jzis.org", 443),
        "scheme": "https",
    })


def test_cache_key_is_stable_and_varies_with_every_filter():
    baseline = _cache_key(None, False, False, False, None, False)

    assert baseline == _cache_key(None, False, False, False, None, False)
    assert baseline != _cache_key("cuprate", False, False, False, None, False)
    assert baseline != _cache_key(None, True, False, False, None, False)
    assert baseline != _cache_key(None, False, True, False, None, False)
    assert baseline != _cache_key(None, False, False, True, None, False)
    assert baseline != _cache_key(None, False, False, False, 10000, False)
    assert baseline != _cache_key(None, False, False, False, None, True)
    assert baseline != _cache_key(None, False, False, False, None, False, 10, 100)
    assert baseline != _cache_key(
        None, False, False, False, None, False, 0, None, "2"
    )


def test_timeline_response_has_public_cache_headers_and_etag():
    payload = (
        '{"schema_version":"1","data_version":"timeline-v1-20260713T120000Z",'
        '"data_updated_at":"2026-07-13T12:00:00Z","family":null,'
        '"points":[],"coverage":null}'
    )

    response = _http_response(_request(), payload, cache_status="MISS")

    assert response.status_code == 200
    assert response.body == payload.encode()
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"].startswith("public, max-age=60")
    assert response.headers["etag"] == _weak_etag(payload)
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["x-timeline-cache"] == "MISS"
    assert response.headers["x-data-version"] == "timeline-v1-20260713T120000Z"
    assert response.headers["last-modified"] == "Mon, 13 Jul 2026 12:00:00 GMT"


def test_matching_if_none_match_returns_empty_304_with_required_headers():
    payload = (
        '{"data_version":"timeline-v1-20260713T120000Z",'
        '"data_updated_at":"2026-07-13T12:00:00Z","points":[]}'
    )
    etag = _weak_etag(payload)

    response = _http_response(
        _request(f'"other", {etag}'),
        payload,
        cache_status="HIT",
    )

    assert response.status_code == 304
    assert response.body == b""
    assert response.headers["etag"] == etag
    assert response.headers["cache-control"].startswith("public")
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["x-timeline-cache"] == "HIT"
    assert response.headers["x-data-version"] == "timeline-v1-20260713T120000Z"
    assert "last-modified" in response.headers


def test_if_none_match_uses_weak_comparison():
    payload = '{"points":[1]}'
    strong_form = _weak_etag(payload).removeprefix("W/")

    response = _http_response(
        _request(strong_form),
        payload,
        cache_status="HIT",
    )

    assert response.status_code == 304


def test_if_modified_since_returns_304_without_an_etag_condition():
    payload = (
        '{"data_version":"timeline-v1-20260713T120000Z",'
        '"data_updated_at":"2026-07-13T12:00:00Z","points":[]}'
    )

    response = _http_response(
        _request(if_modified_since="Mon, 13 Jul 2026 12:00:00 GMT"),
        payload,
        cache_status="HIT",
    )

    assert response.status_code == 304


def _point(index: int) -> TimelinePoint:
    return TimelinePoint(
        material=f"M{index}",
        formula_latex=f"M_{{{index}}}",
        family="test",
        tc_kelvin=float(index + 1),
        year=2000 + index,
        pressure_gpa=None,
        paper_id=f"paper:{index}",
    )


def test_even_sampling_is_bounded_deterministic_and_keeps_order():
    points = [_point(index) for index in range(10)]

    sampled = _evenly_sample(points, 4)

    assert [point.material for point in sampled] == ["M0", "M3", "M6", "M9"]
    assert _evenly_sample(points, 4) == sampled
    assert _evenly_sample(points, None) is points
    assert _evenly_sample(points, 10) is points


def test_compact_serialization_only_omits_unused_formula_latex():
    data = TimelineResponse(
        family=None,
        points=[_point(0)],
        coverage=TimelineCoverage(
            total_points=1,
            total_materials=1,
            year_min=2000,
            year_max=2000,
            returned_points=1,
        ),
    )

    full = _serialize_timeline(data, compact=False)
    compact = _serialize_timeline(data, compact=True)

    assert '"formula_latex"' in full
    assert '"formula_latex"' not in compact
    assert '"paper_id":"paper:0"' in compact
    assert '"returned_points":1' in compact


def test_timeline_pagination_is_stable_after_optional_sampling():
    points = [_point(index) for index in range(10)]

    page = _timeline_response(
        family=None,
        points=points,
        max_points=None,
        offset=3,
        limit=4,
        data_updated_at=datetime(2026, 7, 13, 12, tzinfo=UTC),
    )

    assert [point.material for point in page.points] == ["M3", "M4", "M5", "M6"]
    assert page.schema_version == "1"
    assert page.data_version == "timeline-v1-20260713T120000Z"
    assert page.offset == 3
    assert page.limit == 4
    assert page.has_more is True
    assert page.coverage is not None
    assert page.coverage.total_points == 10
    assert page.coverage.available_points == 10
    assert page.coverage.returned_points == 4
