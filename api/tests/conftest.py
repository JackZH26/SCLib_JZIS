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


# ---------------------------------------------------------------------------
# Helper fixtures for phase A/B/C endpoint tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def registered_user():
    """Create an active user + a JWT, bypassing the email verification
    flow (that path has its own test in test_auth.py).

    Returns ``(user, jwt_token)``. Each test gets a unique email so
    parallel fixture instantiation cannot collide on the unique
    index."""
    import uuid

    from models.db import User
    from services import auth_service

    suffix = uuid.uuid4().hex[:8]
    factory = get_session_factory()
    async with factory() as session:
        user = User(
            email=f"user-{suffix}@example.com",
            name=f"Tester {suffix}",
            password_hash=auth_service.hash_password("correcthorsebatterystaple"),
            email_verified=True,
            is_active=True,
            auth_provider="local",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    jwt_token, _ = auth_service.create_access_token(user.id)
    return user, jwt_token


@pytest_asyncio.fixture
async def sample_paper():
    """Seed one paper so bookmark tests have a real target_id to point
    at. Returns the paper's primary-key id.

    Idempotent (uses ``session.merge``) so multiple tests in the same
    session can request it without fighting the unique-id index."""
    from models.db import Paper

    paper_id = "arxiv:9999.test"
    factory = get_session_factory()
    async with factory() as session:
        paper = Paper(
            id=paper_id,
            source="arxiv",
            arxiv_id="9999.test",
            title="A Test Paper",
            authors=["Alice Test", "Bob Example"],
            abstract="Nothing useful.",
            status="published",
        )
        await session.merge(paper)
        await session.commit()
    return paper_id


@pytest_asyncio.fixture(autouse=True)
async def _flush_redis_between_tests():
    """Wipe Redis quota counters so a high-traffic test can't starve
    subsequent tests on the same day key. Scoped autouse because the
    cost is trivial (one FLUSHDB per test) and the isolation bought is
    significant for quota-sensitive assertions."""
    from services.rate_limit import get_redis

    r = get_redis()
    await r.flushdb()
    yield
