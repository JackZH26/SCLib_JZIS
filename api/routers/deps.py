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

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import logging
from uuid import UUID

from models import get_db
from models.db import ApiKey, User
from services import auth_service
from services.rate_limit import (
    consume_guest,
    consume_user,
    get_guest_remaining,
    get_user_remaining,
)

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Identity:
    """Who is making this request?

    Exactly one of ``user`` / ``guest_ip`` is set. The ``_remaining``
    field is the remaining daily quota **after** consuming this request
    — meaningful only for the matching auth path (guest or user).
    """

    user: User | None
    guest_ip: str | None
    guest_remaining: int | None
    user_remaining: int | None = None

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


async def _resolve_jwt_user(
    request: Request,
    db: AsyncSession,
) -> User | None:
    """Try to extract a valid JWT from the ``Authorization: Bearer`` header.

    Returns the ``User`` if the token is valid and the account is active,
    otherwise ``None`` (fall through to the next auth method).
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:]  # strip "Bearer "
    try:
        payload = auth_service.decode_access_token(token)
        user_id = UUID(payload["sub"])
    except Exception:
        # Malformed / expired JWT — don't hard-fail, fall through to
        # guest path so clients with a stale token still get guest access.
        log.debug("JWT decode failed, falling through to guest path")
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


async def _enforce_user_quota(user: User) -> int:
    """Consume one daily-quota slot for ``user`` and 429 if over cap.

    Returns the NEW remaining count (>= 0) for the caller to forward
    into the Identity. Shared by the API-key and JWT branches of
    ``require_identity`` so both enforce the same 999/day rule.
    """
    from config import get_settings

    remaining = await consume_user(user.id)
    if remaining < 0:
        limit = get_settings().registered_daily_limit
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "user_quota_exceeded",
                "message": f"Daily quota of {limit} queries exhausted. "
                           "Quota resets at 00:00 UTC.",
                "remaining": 0,
                "limit": limit,
            },
        )
    return remaining


async def require_identity(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Identity:
    """Resolve the caller to a ``User`` or a quota-checked guest.

    Priority order:
    1. ``X-API-Key`` header → look up API key
    2. ``Authorization: Bearer <jwt>`` → decode JWT
    3. No credentials → guest path (rate-limited by IP)

    Registered users (key OR JWT) are subject to
    ``registered_daily_limit`` (default 999/day, Redis-tracked).
    API-key requests additionally bump ``api_keys.last_used`` and
    ``api_keys.total_requests`` so the dashboard's Keys tab can show
    per-key activity.
    """
    # 1. API key
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
        remaining = await _enforce_user_quota(user)
        # Atomic UPDATE avoids a read-modify-write race when the same
        # key fires parallel requests.
        await db.execute(
            update(ApiKey)
            .where(ApiKey.id == ak.id)
            .values(
                last_used=datetime.now(timezone.utc),
                total_requests=ApiKey.total_requests + 1,
            )
        )
        await db.commit()
        return Identity(
            user=user, guest_ip=None, guest_remaining=None,
            user_remaining=remaining,
        )

    # 2. JWT Bearer token
    jwt_user = await _resolve_jwt_user(request, db)
    if jwt_user is not None:
        remaining = await _enforce_user_quota(jwt_user)
        return Identity(
            user=jwt_user, guest_ip=None, guest_remaining=None,
            user_remaining=remaining,
        )

    # 3. Guest path
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
    """Like ``require_identity`` but **does not consume** quota.

    Used by public read endpoints (materials / papers / timeline / stats)
    that the spec §7 lists as free. We still resolve the API key / JWT so
    responses can be personalized for logged-in users, and we still
    surface the current guest / user remaining so the UI can show the
    badge without spending a slot.
    """
    # 1. API key
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
                remaining = await get_user_remaining(user.id)
                return Identity(
                    user=user, guest_ip=None, guest_remaining=None,
                    user_remaining=remaining,
                )

    # 2. JWT Bearer token
    jwt_user = await _resolve_jwt_user(request, db)
    if jwt_user is not None:
        remaining = await get_user_remaining(jwt_user.id)
        return Identity(
            user=jwt_user, guest_ip=None, guest_remaining=None,
            user_remaining=remaining,
        )

    # 3. Guest
    ip = _client_ip(request)
    remaining = await get_guest_remaining(ip)
    return Identity(user=None, guest_ip=ip, guest_remaining=remaining)
