"""Isolated tests for Redis-backed auth limits; no database is required."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from redis.exceptions import ConnectionError

from services import auth_security


class _Pipeline:
    def __init__(self, owner: _Redis, result=None, error=None) -> None:
        self.owner = owner
        self.result = result or []
        self.error = error
        self.command_stack: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, command: str):
        def queue(*args, **kwargs):
            self.command_stack.append((command, args, kwargs))
            return self

        return queue

    async def execute(self):
        self.owner.executed.append(self.command_stack)
        if self.error:
            raise self.error
        return self.result


class _Redis:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.executed: list[list[tuple[str, tuple, dict]]] = []
        self.deleted: tuple[str, ...] = ()

    def pipeline(self, **_kwargs):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            return _Pipeline(self, error=result)
        return _Pipeline(self, result=result)

    async def delete(self, *keys):
        self.deleted = keys


def _settings(**overrides):
    values = {
        "jwt_secret": "unit-test-secret-long-enough-for-hmac",
        "auth_login_window_seconds": 900,
        "auth_login_ip_limit": 30,
        "auth_login_account_limit": 10,
        "auth_register_window_seconds": 3600,
        "auth_register_ip_limit": 10,
        "auth_register_account_limit": 3,
        "auth_reset_window_seconds": 3600,
        "auth_reset_ip_limit": 10,
        "auth_reset_account_limit": 3,
        "auth_backoff_base_seconds": 2,
        "auth_backoff_ip_threshold": 5,
        "auth_backoff_account_threshold": 3,
        "auth_backoff_max_seconds": 300,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_login_consumes_ip_and_account_budgets(monkeypatch):
    redis = _Redis(
        [
            [-1, -1],
            [1, True, 900, 1, True, 900],
        ]
    )
    monkeypatch.setattr(auth_security, "get_redis", lambda: redis)
    monkeypatch.setattr(auth_security, "get_settings", _settings)

    await auth_security.enforce_auth_attempt("login", "203.0.113.4", "A@EXAMPLE.COM")

    commands = redis.executed[1]
    assert [command for command, _, _ in commands] == [
        "incr",
        "expire",
        "ttl",
        "incr",
        "expire",
        "ttl",
    ]
    assert "a@example.com" not in str(commands)
    assert "203.0.113.4" not in str(commands)


@pytest.mark.asyncio
async def test_account_budget_rejects_even_when_ip_is_within_budget(monkeypatch):
    redis = _Redis(
        [
            [-1, -1],
            [2, True, 800, 11, True, 700],
        ]
    )
    monkeypatch.setattr(auth_security, "get_redis", lambda: redis)
    monkeypatch.setattr(auth_security, "get_settings", _settings)

    with pytest.raises(auth_security.AuthRateLimited) as exc_info:
        await auth_security.enforce_auth_attempt("login", "203.0.113.4", "target@example.com")

    assert exc_info.value.scope == "account"
    assert exc_info.value.retry_after == 700


@pytest.mark.asyncio
async def test_ip_budget_rejects_across_different_accounts(monkeypatch):
    redis = _Redis(
        [
            [-1, -1],
            [31, True, 650, 1, True, 850],
        ]
    )
    monkeypatch.setattr(auth_security, "get_redis", lambda: redis)
    monkeypatch.setattr(auth_security, "get_settings", _settings)

    with pytest.raises(auth_security.AuthRateLimited) as exc_info:
        await auth_security.enforce_auth_attempt("login", "203.0.113.4", "another@example.com")

    assert exc_info.value.scope == "ip"
    assert exc_info.value.retry_after == 650


@pytest.mark.asyncio
async def test_login_failures_create_exponential_account_backoff(monkeypatch):
    redis = _Redis(
        [
            [1, True, 3, True],
            [True],
        ]
    )
    monkeypatch.setattr(auth_security, "get_redis", lambda: redis)
    monkeypatch.setattr(auth_security, "get_settings", _settings)

    delay = await auth_security.record_login_failure("203.0.113.4", "target@example.com")

    assert delay == 2
    set_commands = redis.executed[1]
    assert len(set_commands) == 1
    assert set_commands[0][0] == "set"
    assert set_commands[0][2]["ex"] == 2


@pytest.mark.asyncio
async def test_auth_limits_fail_closed_when_redis_is_unavailable(monkeypatch):
    redis = _Redis([ConnectionError("down")])
    monkeypatch.setattr(auth_security, "get_redis", lambda: redis)
    monkeypatch.setattr(auth_security, "get_settings", _settings)

    with pytest.raises(auth_security.AuthSecurityUnavailable):
        await auth_security.enforce_auth_attempt("register", "203.0.113.4", "target@example.com")
