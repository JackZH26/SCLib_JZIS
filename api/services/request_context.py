"""Trusted request metadata shared by quotas, abuse controls, and audit."""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from uuid import uuid4

from starlette.requests import Request

from config import get_settings

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_request_id: ContextVar[str | None] = ContextVar("sclib_request_id", default=None)


def resolve_request_id(request: Request) -> str:
    """Accept a safe caller correlation ID or generate an opaque UUID."""
    supplied = request.headers.get("x-request-id", "").strip()
    if supplied and _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid4().hex


def bind_request_id(value: str) -> Token[str | None]:
    """Bind a request ID for logs emitted below the HTTP boundary."""
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


def client_ip(request: Request) -> str:
    """Return the peer address, trusting XFF only behind the configured proxy."""
    peer = request.client.host if request.client else "0.0.0.0"
    if not get_settings().trust_forwarded_for:
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or peer
    return peer
