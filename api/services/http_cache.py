"""Shared HTTP validators for versioned public data representations."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime

from starlette.requests import Request
from starlette.responses import Response


def weak_etag(payload: str) -> str:
    return f'W/"{hashlib.sha256(payload.encode()).hexdigest()}"'


def data_version(namespace: str, payload: str, *, schema_version: str = "1") -> str:
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{namespace}-v{schema_version}-{digest}"


def conditional_json_response(
    request: Request,
    payload: str,
    *,
    cache_control: str,
    data_version_value: str,
    last_modified: datetime | None,
    cache_header: str,
    cache_status: str,
) -> Response:
    """Return JSON or a validator-complete 304 response.

    `If-None-Match` takes precedence over `If-Modified-Since`, matching HTTP
    semantics. Dates are normalized to whole UTC seconds for wire comparison.
    """
    etag = weak_etag(payload)
    normalized_modified = _normalize_datetime(last_modified)
    headers = {
        "Cache-Control": cache_control,
        "ETag": etag,
        "Vary": "Accept-Encoding",
        "X-Data-Version": data_version_value,
        cache_header: cache_status,
    }
    if normalized_modified is not None:
        headers["Last-Modified"] = format_datetime(normalized_modified, usegmt=True)

    if _is_not_modified(request, etag, normalized_modified):
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


def _is_not_modified(
    request: Request,
    etag: str,
    last_modified: datetime | None,
) -> bool:
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        return _etag_matches(if_none_match, etag)
    if last_modified is None:
        return False
    if_modified_since = request.headers.get("if-modified-since")
    if not if_modified_since:
        return False
    try:
        candidate = _normalize_datetime(parsedate_to_datetime(if_modified_since))
    except (TypeError, ValueError, OverflowError):
        return False
    return candidate is not None and last_modified <= candidate


def _etag_matches(if_none_match: str, etag: str) -> bool:
    def weak_value(value: str) -> str:
        value = value.strip()
        return value[2:] if value.startswith("W/") else value

    expected = weak_value(etag)
    return any(
        candidate.strip() == "*" or weak_value(candidate) == expected
        for candidate in if_none_match.split(",")
    )


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)
