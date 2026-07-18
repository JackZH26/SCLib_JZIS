"""Authentication-specific rate limits and exponential login backoff.

Public identifiers are HMACed before becoming Redis keys. Limits are applied
to both the source IP and normalized account identifier, preventing attackers
from bypassing protection by rotating only one dimension.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

from redis.exceptions import RedisError

from config import Settings, get_settings
from services.rate_limit import get_redis

log = logging.getLogger(__name__)


class AuthRateLimited(Exception):
    def __init__(self, retry_after: int, scope: str) -> None:
        super().__init__(f"authentication rate limit exceeded ({scope})")
        self.retry_after = max(1, retry_after)
        self.scope = scope


class AuthSecurityUnavailable(Exception):
    """Raised when Redis cannot safely enforce authentication controls."""


@dataclass(frozen=True, slots=True)
class _Policy:
    window: int
    ip_limit: int
    account_limit: int


def normalize_account(account: str) -> str:
    return account.strip().casefold()


def privacy_hash(kind: str, value: str) -> str:
    """Stable keyed digest for rate-limit keys and privacy-safe audit fields."""
    secret = get_settings().jwt_secret.encode("utf-8")
    message = f"{kind}\0{value}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _policy(action: str, settings: Settings) -> _Policy:
    if action == "login":
        return _Policy(
            settings.auth_login_window_seconds,
            settings.auth_login_ip_limit,
            settings.auth_login_account_limit,
        )
    if action == "register":
        return _Policy(
            settings.auth_register_window_seconds,
            settings.auth_register_ip_limit,
            settings.auth_register_account_limit,
        )
    if action == "password_reset":
        return _Policy(
            settings.auth_reset_window_seconds,
            settings.auth_reset_ip_limit,
            settings.auth_reset_account_limit,
        )
    raise ValueError(f"unsupported auth rate-limit action: {action}")


def _subject_keys(action: str, ip: str, account: str) -> dict[str, str]:
    return {
        "ip": f"auth:limit:{action}:ip:{privacy_hash('ip', ip)}",
        "account": (
            f"auth:limit:{action}:account:{privacy_hash('account', normalize_account(account))}"
        ),
    }


def _backoff_keys(ip: str, account: str) -> dict[str, tuple[str, str]]:
    subjects = {
        "ip": privacy_hash("ip", ip),
        "account": privacy_hash("account", normalize_account(account)),
    }
    return {
        scope: (
            f"auth:login:failures:{scope}:{digest}",
            f"auth:login:blocked:{scope}:{digest}",
        )
        for scope, digest in subjects.items()
    }


async def enforce_auth_attempt(action: str, ip: str, account: str) -> None:
    """Consume both fixed-window budgets and enforce any login backoff."""
    settings = get_settings()
    policy = _policy(action, settings)
    redis = get_redis()
    try:
        if action == "login":
            backoff = _backoff_keys(ip, account)
            pipe = redis.pipeline(transaction=False)
            for _, blocked_key in backoff.values():
                pipe.ttl(blocked_key)
            blocked_ttls = [int(value) for value in await pipe.execute()]
            if max(blocked_ttls, default=-1) > 0:
                index = blocked_ttls.index(max(blocked_ttls))
                raise AuthRateLimited(max(blocked_ttls), ("ip", "account")[index])

        keys = _subject_keys(action, ip, account)
        pipe = redis.pipeline(transaction=True)
        for key in keys.values():
            pipe.incr(key)
            pipe.expire(key, policy.window, nx=True)
            pipe.ttl(key)
        values = await pipe.execute()
    except AuthRateLimited:
        raise
    except RedisError as exc:
        log.exception("auth security Redis failure action=%s", action)
        raise AuthSecurityUnavailable from exc

    limits = {"ip": policy.ip_limit, "account": policy.account_limit}
    for index, scope in enumerate(keys):
        count = int(values[index * 3])
        ttl = int(values[index * 3 + 2])
        if count > limits[scope]:
            raise AuthRateLimited(ttl if ttl > 0 else policy.window, scope)


async def record_login_failure(ip: str, account: str) -> int:
    """Increase failure counters, set exponential blocks, and return wait time."""
    settings = get_settings()
    redis = get_redis()
    keys = _backoff_keys(ip, account)
    try:
        pipe = redis.pipeline(transaction=True)
        for failure_key, _ in keys.values():
            pipe.incr(failure_key)
            pipe.expire(failure_key, settings.auth_login_window_seconds, nx=True)
        values = await pipe.execute()
        counts = {scope: int(values[index * 2]) for index, scope in enumerate(keys)}

        thresholds = {
            "ip": settings.auth_backoff_ip_threshold,
            "account": settings.auth_backoff_account_threshold,
        }
        delays: dict[str, int] = {}
        for scope, count in counts.items():
            if count < thresholds[scope]:
                delays[scope] = 0
                continue
            exponent = count - thresholds[scope]
            delays[scope] = min(
                settings.auth_backoff_max_seconds,
                settings.auth_backoff_base_seconds * (2**exponent),
            )

        pipe = redis.pipeline(transaction=True)
        for scope, (_, blocked_key) in keys.items():
            if delays[scope] > 0:
                pipe.set(blocked_key, "1", ex=delays[scope])
        if pipe.command_stack:
            await pipe.execute()
        return max(delays.values(), default=0)
    except RedisError as exc:
        log.exception("auth security Redis failure recording login failure")
        raise AuthSecurityUnavailable from exc


async def clear_login_failures(ip: str, account: str) -> None:
    keys = _backoff_keys(ip, account)
    try:
        await get_redis().delete(*(key for pair in keys.values() for key in pair))
    except RedisError as exc:
        log.exception("auth security Redis failure clearing login failures")
        raise AuthSecurityUnavailable from exc
