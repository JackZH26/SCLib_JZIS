"""Private read-only task receipts, never implicit enqueue or live readiness."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from config import get_settings
from services import auth_service, source_tasks
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state
from tests.test_source_impact_http import private
from tests.test_source_tasks import execution, prepared

db_session = _serializable_db_session
pytestmark = pytest.mark.asyncio
_BASE = "/v1/ml/source-lifecycle/tasks"


async def fixture(db):
    context = await prepared(db)
    request = await source_tasks.enqueue_source_task(db, **context["args"], dry_run=False)
    await source_tasks.execute_source_task(db, **execution(context, request), dry_run=False)
    await db.commit()
    token, _ = auth_service.create_access_token(context["actors"]["curator"])
    return {"url": f"{_BASE}/{request['request']['id']}", "headers": {"Authorization": f"Bearer {token}"}}


async def test_operator_reads_historical_receipt_without_inventory_bytes_or_writes(client, db_session):
    context = await fixture(db_session)
    before = await state(db_session)
    await db_session.commit()
    response = await client.get(context["url"], headers={**context["headers"], "If-None-Match": "*"})
    assert response.status_code == 200, response.text
    private(response)
    body = response.json()
    assert body["stored_state"] == "succeeded" and len(body["attempts"]) == 1
    assert body["receipt_semantics"]["timeline_rebuilt"] is False
    assert body["receipt_semantics"]["currentness"] == "historical_receipt_not_live_projection_state"
    for forbidden in ("inventory_json", "UNEXPOSED", "@example.test", "tc_kelvin", "UNEXPOSED_RECORD"):
        assert forbidden not in response.text
    assert await state(db_session) == before
    await db_session.commit()
    denied_write = await client.post(context["url"], headers=context["headers"], json={"execute": True})
    assert denied_write.status_code == 405
    private(denied_write)


async def test_task_history_hidden_with_kill_switch(client):
    settings = get_settings()
    old = settings.ml_foundation_public_enabled
    settings.ml_foundation_public_enabled = False
    try:
        response = await client.get(f"{_BASE}/{uuid4()}")
        assert response.status_code == 404
        private(response)
    finally:
        settings.ml_foundation_public_enabled = old


async def test_anonymous_and_legacy_admin_cannot_read_task_history(client, db_session):
    context = await fixture(db_session)
    legacy = await research_user(is_admin=True, is_reviewer=True)
    for headers, status in (({}, 401), (legacy["headers"], 403)):
        response = await client.get(context["url"], headers=headers)
        assert response.status_code == status
        private(response)


async def test_revoked_role_cannot_read_historical_receipt(client, db_session):
    context = await fixture(db_session)
    operator = await research_operator()
    assert (await client.get(context["url"], headers=operator["headers"])).status_code == 200
    await revoke_research_grant(grant_id=operator["grant_id"], revoked_by=operator["grantor_id"])
    response = await client.get(context["url"], headers=operator["headers"])
    assert response.status_code == 403
    private(response)


async def test_unknown_and_malformed_request_ids_are_private(client):
    operator = await research_operator()
    for identifier, status in ((str(uuid4()), 404), ("bad-uuid", 422)):
        response = await client.get(f"{_BASE}/{identifier}", headers=operator["headers"])
        assert response.status_code == status
        private(response)


@pytest.mark.parametrize("failure,status", [(source_tasks.SourceTaskError, 404), (SQLAlchemyError, 503)])
async def test_task_read_errors_are_sanitized(client, db_session, monkeypatch, failure, status):
    context = await fixture(db_session)
    async def broken(*_args, **_kwargs):
        raise failure("PRIVATE_DATABASE_DIAGNOSTIC")
    monkeypatch.setattr(source_tasks, "inspect_source_task", broken)
    response = await client.get(context["url"], headers=context["headers"])
    assert response.status_code == status
    assert "PRIVATE_DATABASE_DIAGNOSTIC" not in response.text
    private(response)
