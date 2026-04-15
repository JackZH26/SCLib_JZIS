"""Shared FastAPI dependencies for the public Phase-3 routers.

Most SCLib endpoints accept *either* an authenticated user (via
``X-API-Key``) *or* an anonymous guest (rate-limited by client IP).
Rather than duplicate that logic across seven routers, we centralize
it here.

Usage in a route::

    @router.post("/search")
    async def search(
        body: SearchRequest,
        identity: Identity = Depends(require_identity),
    ):
        # identity.user is a User or None
        # identity.guest_remaining is an int when guest, else None
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import ApiKey, User
from services import auth_service
from services.rate_limit import consume_guest, get_guest_remaining


@dataclass(slots=True)
class Identity:
    """Who is making this request?

    Exactly one of ``user`` / ``guest_ip`` is set. ``guest_remaining`` is
    the remaining daily quota **after** consuming this request.
    """

    user: User | None
    guest_ip: str | None
    guest_remaining: int | None

    @property
    def is_guest(self) -> bool:
        return self.user is None


def _client_ip(request: Request) -> str:
    """Best-effort client IP.

    Nginx on VPS2 terminates TLS and forwards via ``X-Forwarded-For``.
    We only trust that header when ``settings.trust_forwarded_for`` is
    enabled (default True, matching the VPS2 deployment where the API
    container binds to 127.0.0.1:8000 and is only reachable through
    Nginx on the host). If the API is ever exposed directly, flip
    ``TRUST_FORWARDED_FOR=false`` in ``.env`` so clients cannot spoof
    arbitrary source IPs to bypass the guest daily quota.
    """
    from config import get_settings

    peer = request.client.host if request.client else "0.0.0.0"
    if not get_settings().trust_forwarded_for:
        return peer
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # first entry in the comma list = original client
        return xff.split(",", 1)[0].strip()
    return peer


async def require_identity(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Identity:
    """Resolve the caller to a ``User`` or a quota-checked guest.

    * Valid ``X-API-Key`` → ``Identity(user=..., guest_*=None)``. No
      quota check (registered users are unlimited per §6 of the spec).
    * Missing / invalid key → guest path. Increments Redis counter.
      Returns 429 when the new remaining count is negative.
    """
    if x_api_key:
        key_hash = auth_service.hash_api_key(x_api_key)
        q = await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.revoked.is_(False),
            )
        )
        ak = q.scalar_one_or_none()
        if ak is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        user = await db.get(User, ak.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inactive account")
        return Identity(user=user, guest_ip=None, guest_remaining=None)

    # Guest path
    ip = _client_ip(request)
    remaining = await consume_guest(ip)
    if remaining < 0:
        # Over limit — report the pre-consumption cap so clients can
        # show a useful "0/3" counter.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "guest_quota_exceeded",
                "message": "Daily guest quota exhausted. Register for unlimited access.",
                "remaining": 0,
            },
        )
    return Identity(user=None, guest_ip=ip, guest_remaining=remaining)


async def peek_identity(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Identity:
    """Like ``require_identity`` but **does not consume** guest quota.

    Used by public read endpoints (materials / papers / timeline / stats)
    that the spec §7 lists as free. We still resolve the API key so
    responses can be personalized for logged-in users, and we still
    surface the current guest remaining so the UI can show the badge.
    """
    if x_api_key:
        key_hash = auth_service.hash_api_key(x_api_key)
        q = await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.revoked.is_(False),
            )
        )
        ak = q.scalar_one_or_none()
        if ak is not None:
            user = await db.get(User, ak.user_id)
            if user is not None and user.is_active:
                return Identity(user=user, guest_ip=None, guest_remaining=None)

    ip = _client_ip(request)
    remaining = await get_guest_remaining(ip)
    return Identity(user=None, guest_ip=ip, guest_remaining=remaining)
