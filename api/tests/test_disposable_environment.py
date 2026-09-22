"""Integration proof that cleanup targets a fresh least-privilege sandbox."""
from __future__ import annotations

import os

import pytest
from redis.exceptions import NoPermissionError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_safety import validate_test_environment, verify_postgres_identity, verify_redis_identity

from models.db import get_engine
from services.rate_limit import get_redis


@pytest.mark.asyncio
async def test_postgres_marker_and_role_are_isolated():
    capability = validate_test_environment()
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.run_sync(verify_postgres_identity, capability)
            with pytest.raises(DBAPIError):
                await conn.execute(text("CREATE ROLE forbidden_test_privilege_escalation"))
            await conn.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_only_allows_cleanup_of_its_one_disposable_database():
    capability = validate_test_environment()
    redis = get_redis()
    await verify_redis_identity(redis, capability)
    for command in (("FLUSHALL",), ("CONFIG", "GET", "dir"), ("ACL", "LIST"),
                    ("SELECT", "1")):
        # SELECT 1 is a ResponseError (only DB 0 exists); the dangerous commands
        # fail the ACL before they can affect even this disposable server.
        if command[0] == "SELECT":
            from redis.exceptions import ResponseError
            with pytest.raises(ResponseError):
                await redis.execute_command(*command)
        else:
            with pytest.raises(NoPermissionError):
                await redis.execute_command(*command)
    await redis.set("test-cleanup-proof", os.environ["SCLIB_TEST_RUN_ID"])
    await redis.flushdb()
    assert await redis.get("test-cleanup-proof") is None
    await verify_redis_identity(redis, capability)
