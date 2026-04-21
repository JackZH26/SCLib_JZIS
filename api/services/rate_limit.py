"""Rate limiting via Redis for guests (by IP) and registered users (by ID).

Redis key schema:
    guest_quota:{YYYY-MM-DD}:{ip}        TTL 86400s, value = used-count
    user_quota:{YYYY-MM-DD}:{user_id}    TTL 86400s, value = used-count

The day rolls over at 00:00 UTC; at that point a new key is born and the
old key expires naturally. First INCR plus EXPIRE NX fits in one
pipeline round trip.

Registered quota was "unlimited" in the earlier spec. Phase A of the
dashboard redesign introduces a hard ``registered_daily_limit`` (default
999) so the Overview can render a real "X / 999 today" counter.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from uuid import UUID

import redis.asyncio as aioredis

from config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _guest_key(ip: str) -> str:
    return f"guest_quota:{_today()}:{ip}"


def _user_key(user_id: UUID, day: str | None = None) -> str:
    return f"user_quota:{day or _today()}:{user_id}"


# ---------------------------------------------------------------------------
# Guest quota (by IP)
# ---------------------------------------------------------------------------

async def get_guest_remaining(ip: str) -> int:
    """Return queries remaining today for this IP without consuming one."""
    settings = get_settings()
    r = get_redis()
    used = int(await r.get(_guest_key(ip)) or 0)
    return max(0, settings.guest_daily_limit - used)


async def consume_guest(ip: str) -> int:
    """Consume one guest query; return NEW remaining (>= 0).

    Does NOT raise on over-limit — caller checks remaining < 0 and decides
    whether to 429. We intentionally let INCR go past the limit so the
    counter reflects real traffic and over-limit hits are still measurable.
    """
    settings = get_settings()
    r = get_redis()
    key = _guest_key(ip)
    pipe = r.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, 86400, nx=True)
    used_new, _ = await pipe.execute()
    return settings.guest_daily_limit - int(used_new)


# ---------------------------------------------------------------------------
# Registered user quota (by user_id)
# ---------------------------------------------------------------------------

async def get_user_today_used(user_id: UUID) -> int:
    """How many queries the user has run today (UTC)."""
    r = get_redis()
    return int(await r.get(_user_key(user_id)) or 0)


async def get_user_remaining(user_id: UUID) -> int:
    """Queries remaining today for this user, not counting this one."""
    settings = get_settings()
    used = await get_user_today_used(user_id)
    return max(0, settings.registered_daily_limit - used)


async def consume_user(user_id: UUID) -> int:
    """Consume one user query; return NEW remaining.

    Negative return means the user is over quota — caller decides on 429.
    Same semantics as ``consume_guest``.
    """
    settings = get_settings()
    r = get_redis()
    key = _user_key(user_id)
    pipe = r.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, 86400, nx=True)
    used_new, _ = await pipe.execute()
    return settings.registered_daily_limit - int(used_new)


async def get_user_week_used(user_id: UUID) -> int:
    """Sum of the last 7 daily counters (today + previous 6) for this user.

    Any key that has already expired simply reads as 0. We do a single
    MGET so the whole 7-day window costs one round trip.
    """
    r = get_redis()
    today = dt.datetime.now(dt.timezone.utc).date()
    keys = [
        _user_key(user_id, (today - dt.timedelta(days=d)).strftime("%Y-%m-%d"))
        for d in range(7)
    ]
    values = await r.mget(keys)
    return sum(int(v) for v in values if v is not None)
