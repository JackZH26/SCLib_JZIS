"""Administrative job status is bounded, read-only and never publicly cached."""
from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from models.background_jobs_v1 import JOB_LOCK_KEYS
from models.db import User, get_session_factory
from routers import background_jobs as router
from tests.research_access_helpers import research_user

_PATH = "/v1/admin/background-jobs"


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers and "location" not in response.headers


async def test_anonymous_and_non_admin_users_cannot_inspect_jobs(client):
    response = await client.get(_PATH)
    assert response.status_code == 401
    private(response)
    for flags in ({}, {"is_reviewer": True}):
        user = await research_user(**flags)
        response = await client.get(_PATH, headers=user["headers"])
        assert response.status_code == 403
        private(response)


async def test_admin_reads_all_fixed_jobs_with_no_cache_bypass_or_private_users(client):
    user = await research_user(is_admin=True)
    for headers in (user["headers"], {**user["headers"], "If-None-Match": "*"}):
        response = await client.get(_PATH, headers=headers)
        assert response.status_code == 200, response.text
        private(response)
        body = response.json()
        assert body["scope"] == "database_cycles_not_external_cache_delivery"
        assert {job["job_name"] for job in body["jobs"]} == set(JOB_LOCK_KEYS)
        assert all(len(job["recent_cycles"]) <= 20 for job in body["jobs"])
        assert str(user["id"]) not in response.text
        assert "@example.test" not in response.text


@pytest.mark.parametrize("field", ["is_active", "is_admin"])
async def test_fresh_snapshot_flags_override_stale_authentication_object(client, monkeypatch, field):
    user = await research_user(is_admin=True)
    stale = User(id=user["id"], is_active=True, is_admin=True)
    async with get_session_factory()() as db:
        await db.execute(sa.update(User).where(User.id == user["id"]).values(**{field: False}))
        await db.commit()

    async def original_identity(*_args):
        return stale

    monkeypatch.setattr(router, "current_user_from_jwt", original_identity)
    response = await client.get(_PATH, headers=user["headers"])
    assert response.status_code == 403
    private(response)


async def test_job_inspection_uses_read_only_repeatable_snapshot(client, monkeypatch):
    user = await research_user(is_admin=True)

    async def inspect(db):
        assert await db.scalar(sa.text("SHOW transaction_isolation")) == "repeatable read"
        assert await db.scalar(sa.text("SHOW transaction_read_only")) == "on"
        assert await db.scalar(sa.text("SHOW statement_timeout")) == "5s"
        assert await db.scalar(sa.select(User.is_admin).where(User.id == user["id"])) is True
        return {"synthetic_snapshot_verified": True}

    monkeypatch.setattr(router, "inspect_background_jobs", inspect)
    response = await client.get(_PATH, headers=user["headers"])
    assert response.status_code == 200 and response.json()["synthetic_snapshot_verified"] is True
    private(response)


@pytest.mark.parametrize("failure", ["database", "timeout", "setup"])
async def test_registry_failure_is_sanitized_and_not_an_empty_success(client, monkeypatch, failure):
    user = await research_user(is_admin=True)

    async def inspect(_db):
        raise (SQLAlchemyError if failure == "database" else TimeoutError)("PRIVATE DATABASE DETAILS")

    def engine():
        raise SQLAlchemyError("PRIVATE DATABASE DETAILS")

    if failure == "setup":
        monkeypatch.setattr(router, "get_engine", engine)
    else:
        monkeypatch.setattr(router, "inspect_background_jobs", inspect)
    response = await client.get(_PATH, headers=user["headers"])
    assert response.status_code == 503
    assert "PRIVATE" not in response.text
    private(response)


async def test_operational_registry_has_no_http_writer(client):
    user = await research_user(is_admin=True)
    for method in ("POST", "PUT", "DELETE"):
        response = await client.request(method, _PATH, headers=user["headers"], json={"owner_id": str(uuid4())})
        assert response.status_code == 405
        private(response)
