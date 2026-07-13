"""Trusted request metadata shared by quotas, abuse controls, and audit."""

from __future__ import annotations

from starlette.requests import Request

from config import get_settings


def client_ip(request: Request) -> str:
    """Return the peer address, trusting XFF only behind the configured proxy."""
    peer = request.client.host if request.client else "0.0.0.0"
    if not get_settings().trust_forwarded_for:
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or peer
    return peer
