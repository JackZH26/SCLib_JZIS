"""Authenticated impact inspection; no work is enqueued and no science approved."""
from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from config import get_settings
from routers import source_impacts as router
from services import auth_service
from services.source_lifecycle import inspect_source_lifecycle
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as _serializable_db_session

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio
_BASE = "/v1/ml/source-lifecycle"


async def fixture(db):
    paper = "impact-http:" + uuid4().hex
    material = "impact-material:" + uuid4().hex
    await add(db, "papers", id=paper, source="arxiv", title="SECRET SOURCE TITLE", authors=[],
              abstract="SECRET SOURCE ABSTRACT", status="corrected")
    await add(db, "materials", id=material, formula="MgB2", formula_normalized="MgB2",
              records=[{"paper_id": paper, "tc_kelvin": 39, "private_note": "SECRET RECORD"}])
    result = await inspect_source_lifecycle(db, paper_id=paper)
    await db.commit()
    return {"paper": paper, "material": material, "event": result["head"]}


def impact_url(context):
    event = context["event"]
    return f"{_BASE}/{event['id']}/impact?expected_event_sha256={event['record_sha256']}"


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers and "location" not in response.headers


async def test_impact_routes_hidden_by_existing_kill_switch(client, monkeypatch):
    monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "false")
    get_settings.cache_clear()
    try:
        for url in (_BASE, f"{_BASE}/{uuid4()}/impact?expected_event_sha256={'a' * 64}"):
            response = await client.get(url)
            assert response.status_code == 404
            private(response)
    finally:
        monkeypatch.setenv("ML_FOUNDATION_PUBLIC_ENABLED", "true")
        get_settings.cache_clear()


async def test_anonymous_or_legacy_admin_cannot_inspect_dependencies(client, db_session):
    context = await fixture(db_session)
    legacy = await research_user(is_admin=True, is_reviewer=True)
    for path in (f"{_BASE}?paper_id={context['paper']}", impact_url(context)):
        anonymous = await client.get(path)
        assert anonymous.status_code == 401
        private(anonymous)
        denied = await client.get(path, headers=legacy["headers"])
        assert denied.status_code == 403
        assert context["material"] not in denied.text
        private(denied)


async def test_operator_gets_deterministic_private_plan_without_writes(client, db_session):
    context = await fixture(db_session)
    operator = await research_operator()
    before = await state(db_session)
    await db_session.commit()
    history = await client.get(_BASE, params={"paper_id": context["paper"]}, headers=operator["headers"])
    assert history.status_code == 200, history.text
    assert history.json()["head"]["id"] == context["event"]["id"]
    private(history)
    first = await client.get(impact_url(context), headers=operator["headers"])
    assert first.status_code == 200, first.text
    second = await client.get(impact_url(context), headers={**operator["headers"], "If-None-Match": "*"})
    assert second.status_code == 200, second.text
    body = first.json()
    assert body["inventory_sha256"] == second.json()["inventory_sha256"]
    assert body["complete_for_declared_scope"] is True
    assert body["propagation_complete"] is body["scientific_acceptance"] is body["ml_training_approved"] is False
    assert context["material"] in first.text
    for value in ("SECRET SOURCE TITLE", "SECRET SOURCE ABSTRACT", "SECRET RECORD", '"tc_kelvin"'):
        assert value not in first.text
    private(first)
    private(second)
    assert await state(db_session) == before


async def test_impact_requires_current_source_head_and_exact_hash(client, db_session):
    context = await fixture(db_session)
    operator = await research_operator()
    path = impact_url(context)
    mismatch = await client.get(path.replace(context["event"]["record_sha256"], "0" * 64), headers=operator["headers"])
    assert mismatch.status_code == 409
    private(mismatch)
    await db_session.execute(sa.text("UPDATE papers SET status='published' WHERE id=:id"), {"id": context["paper"]})
    await db_session.commit()
    stale = await client.get(path, headers=operator["headers"])
    assert stale.status_code == 409
    private(stale)
    history = await client.get(_BASE, params={"paper_id": context["paper"]}, headers=operator["headers"])
    assert history.status_code == 200 and history.json()["lifecycle_review_required"] is True
    assert history.json()["head"]["id"] != context["event"]["id"]


async def test_role_revocation_removes_access_without_cached_inventory(client, db_session):
    context = await fixture(db_session)
    operator = await research_operator()
    assert (await client.get(impact_url(context), headers=operator["headers"])).status_code == 200
    await revoke_research_grant(grant_id=operator["grant_id"], revoked_by=operator["grantor_id"])
    for url in (_BASE + "?paper_id=" + context["paper"], impact_url(context)):
        response = await client.get(url, headers={**operator["headers"], "If-None-Match": "*"})
        assert response.status_code == 403
        private(response)


@pytest.mark.parametrize("params", [{}, {"paper_id": "p", "work_id": str(uuid4())},
    {"paper_id": "p", "limit": 101}, {"paper_id": "p", "before_revision": 2**32}])
async def test_history_validation_errors_are_private(client, params):
    operator = await research_operator()
    response = await client.get(_BASE, params=params, headers=operator["headers"])
    assert response.status_code == 422
    private(response)


async def test_bad_hash_and_unknown_source_are_private(client):
    operator = await research_operator()
    bad = await client.get(f"{_BASE}/{uuid4()}/impact?expected_event_sha256=bad", headers=operator["headers"])
    assert bad.status_code == 422
    private(bad)
    missing = await client.get(_BASE, params={"paper_id": "unknown:" + uuid4().hex}, headers=operator["headers"])
    assert missing.status_code == 404
    private(missing)


@pytest.mark.parametrize("failure", ["limit", "invalid", "database", "timeout"])
async def test_failed_inventory_is_never_returned_as_empty_or_complete(client, db_session, monkeypatch, failure):
    from services import source_impact
    context = await fixture(db_session)
    operator = await research_operator()

    async def broken(*_args, **_kwargs):
        error = {"limit": source_impact.SourceImpactLimitError, "invalid": source_impact.SourceImpactError,
                 "database": SQLAlchemyError, "timeout": TimeoutError}[failure]
        raise error("SECRET INTERNAL QUERY DIAGNOSTIC")

    monkeypatch.setattr(source_impact, "inspect_source_impact", broken)
    response = await client.get(impact_url(context), headers=operator["headers"])
    assert response.status_code == (409 if failure in {"limit", "invalid"} else 503)
    assert "SECRET INTERNAL" not in response.text
    if failure == "limit":
        assert response.json()["detail"]["complete_for_declared_scope"] is False
        assert response.json()["detail"]["refresh_execution"] == "not_scheduled"
    private(response)


async def test_inspector_and_role_check_share_read_only_repeatable_snapshot(client, db_session, monkeypatch):
    from services import source_impact
    context = await fixture(db_session)
    operator = await research_operator()
    seen = []
    real_access = router.require_research_operator

    async def access(db, user_id):
        seen.append(id(db))
        return await real_access(db, user_id)

    async def inspection(db, **_kwargs):
        assert seen == [id(db)]
        assert (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() == "repeatable read"
        assert (await db.execute(sa.text("SHOW transaction_read_only"))).scalar_one() == "on"
        assert (await db.execute(sa.text("SHOW statement_timeout"))).scalar_one() == "5s"
        return {"synthetic_snapshot_check": True}

    monkeypatch.setattr(router, "require_research_operator", access)
    monkeypatch.setattr(source_impact, "inspect_source_impact", inspection)
    response = await client.get(impact_url(context), headers=operator["headers"])
    assert response.status_code == 200 and response.json()["synthetic_snapshot_check"] is True


async def test_session_setup_failure_is_sanitized(client, monkeypatch):
    operator = await research_operator()

    def broken():
        raise SQLAlchemyError("SECRET DATABASE DSN")

    monkeypatch.setattr(router, "get_engine", broken)
    response = await client.get(_BASE, params={"paper_id": "p"}, headers=operator["headers"])
    assert response.status_code == 503 and "SECRET DATABASE" not in response.text
    private(response)


async def test_impact_has_no_mutating_http_route(client):
    operator = await research_operator()
    for method in ("POST", "PUT", "DELETE"):
        response = await client.request(method, f"{_BASE}/{uuid4()}/impact", headers=operator["headers"])
        assert response.status_code == 405
        private(response)


async def test_inactive_or_unverified_operator_cannot_read(client):
    for field, expected in (("is_active", 401), ("email_verified", 403)):
        operator = await research_operator()
        from models.db import get_session_factory
        async with get_session_factory()() as session:
            await session.execute(sa.text(f"UPDATE users SET {field}=false WHERE id=:id"), {"id": operator["id"]})
            await session.commit()
        token, _ = auth_service.create_access_token(operator["id"])
        response = await client.get(_BASE, params={"paper_id": "p"}, headers={"Authorization": "Bearer " + token})
        assert response.status_code == expected
        private(response)
