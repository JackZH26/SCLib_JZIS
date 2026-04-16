"""Pytest bootstrap for API tests.

Tests require a live Postgres + Redis (the test workflow provisions both
as services; locally, spin them up via docker compose). Environment
variables are set here before importing the app so pydantic-settings
picks up test values.
"""
from __future__ import annotations

import os

# --- env overrides (must come BEFORE any app import) ----------------------
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://sclib:sclib_test_pw@localhost:5432/sclib_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault(
    "JWT_SECRET",
    "test_jwt_secret_with_sufficient_length_for_pydantic_validation_0000",
)
os.environ.setdefault("EMAIL_BACKEND", "stdout")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from config import get_settings  # noqa: E402

get_settings.cache_clear()

# --- Override engine to use NullPool ------------------------------------
# asyncpg connection pool connections survive across event-loop boundaries,
# causing "Event loop is closed" / "attached to a different loop" errors
# when pytest-asyncio recreates the loop between tests. NullPool creates
# a fresh connection per checkout and closes it on return, sidestepping
# the pool lifecycle issue entirely. This is fine for tests (no perf need).
import models.db as _db_mod  # noqa: E402

_db_mod.get_engine.cache_clear()

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


def _test_engine():
    settings = get_settings()
    dsn = _db_mod._to_async_dsn(settings.database_url)
    return create_async_engine(dsn, poolclass=NullPool)


_db_mod.get_engine.cache_clear()  # clear before patching
_db_mod.get_engine = lambda: _test_engine()  # type: ignore[assignment]
_db_mod.get_session_factory.cache_clear()

from main import app  # noqa: E402
from models.db import Base, get_engine, get_session_factory  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema():
    """Create all tables before the suite, drop after. pgcrypto is
    required for gen_random_uuid() defaults."""
    engine = get_engine()
    async with engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db_session():
    factory = get_session_factory()
    async with factory() as session:
        yield session
