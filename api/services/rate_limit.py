"""Guest rate limiting via Redis.

Redis key schema (spec section 6):
    guest_quota:{YYYY-MM-DD}:{ip}   TTL 86400s, value = used-count

The day rolls over at 00:00 UTC; at that point a new key is born and the
old key expires naturally. First INCR plus EXPIRE NX fits in one
pipeline round trip.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

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


def _quota_key(ip: str) -> str:
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    return f"guest_quota:{today}:{ip}"


async def get_guest_remaining(ip: str) -> int:
    """Return queries remaining today for this IP without consuming one."""
    settings = get_settings()
    r = get_redis()
    used = int(await r.get(_quota_key(ip)) or 0)
    return max(0, settings.guest_daily_limit - used)


async def consume_guest(ip: str) -> int:
    """Consume one guest query; return NEW remaining (>= 0).

    Does NOT raise on over-limit — caller checks remaining < 0 and decides
    whether to 429. We intentionally let INCR go past the limit so the
    counter reflects real traffic and over-limit hits are still measurable.
    """
    settings = get_settings()
    r = get_redis()
    key = _quota_key(ip)
    pipe = r.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, 86400, nx=True)
    used_new, _ = await pipe.execute()
    return settings.guest_daily_limit - int(used_new)
