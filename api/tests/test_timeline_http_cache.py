"""Timeline cache keys and HTTP conditional response behavior."""
from __future__ import annotations

from starlette.requests import Request

from routers.timeline import _cache_key, _http_response, _weak_etag


def _request(if_none_match: str | None = None) -> Request:
    headers = []
    if if_none_match:
        headers.append((b"if-none-match", if_none_match.encode()))
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
    baseline = _cache_key(None, False, False, False)

    assert baseline == _cache_key(None, False, False, False)
    assert baseline != _cache_key("cuprate", False, False, False)
    assert baseline != _cache_key(None, True, False, False)
    assert baseline != _cache_key(None, False, True, False)
    assert baseline != _cache_key(None, False, False, True)


def test_timeline_response_has_public_cache_headers_and_etag():
    payload = '{"family":null,"points":[],"coverage":null}'

    response = _http_response(_request(), payload, cache_status="MISS")

    assert response.status_code == 200
    assert response.body == payload.encode()
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"].startswith("public, max-age=60")
    assert response.headers["etag"] == _weak_etag(payload)
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["x-timeline-cache"] == "MISS"


def test_matching_if_none_match_returns_empty_304_with_required_headers():
    payload = '{"family":null,"points":[],"coverage":null}'
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


def test_if_none_match_uses_weak_comparison():
    payload = '{"points":[1]}'
    strong_form = _weak_etag(payload).removeprefix("W/")

    response = _http_response(
        _request(strong_form),
        payload,
        cache_status="HIT",
    )

    assert response.status_code == 304
