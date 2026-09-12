"""Private HTTP admission/recovery boundaries; compiler doubles are explicit."""
from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa

from config import get_settings
from models.db import User
from models.ml_use_submissions_v1 import RETENTION_POLICY, TABLES
from routers import ml_use_submissions as router
from tests.test_ml_use_preflight import db_session as db_session
from tests.test_ml_use_preflight import enabled as enabled
from tests.test_ml_use_preflight import private, setup
from tests.test_ml_use_submissions import BASE, headers, prepared
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import state


@pytest.mark.parametrize("identity", ["admin", "member", "reviewer", "publisher"])
async def test_nonadmitted_account_never_consumes_upload(client, db_session, monkeypatch, identity):
    context, _, _ = await setup(db_session)
    await db_session.commit()
    async def forbidden(*_a, **_k):
        pytest.fail("private bytes read before admission")
    monkeypatch.setattr(router.preflight, "_reconstruction_body", forbidden)
    result = await client.post(BASE, content=b"PRIVATE", headers=auth(context["actors"][identity]))
    assert result.status_code == 403
    private(result)


@pytest.mark.parametrize("missing", ["Idempotency-Key", "X-SCLib-Envelope-Sha256", "X-SCLib-Inventory-Sha256",
                                     "X-SCLib-Retention-Policy", "X-SCLib-Intent-Sha256"])
async def test_exact_headers_required_before_private_upload(client, db_session, monkeypatch, missing):
    context, _, _ = await setup(db_session)
    await db_session.commit()
    async def forbidden(*_a, **_k):
        pytest.fail("body read before complete intent")
    monkeypatch.setattr(router.preflight, "_reconstruction_body", forbidden)
    from services.ml_audited_dataset import digest
    from services.ml_use_submissions import intent
    proposal = intent(request_key="synthetic-header", envelope_sha256="a" * 64,
                      inventory_sha256="b" * 64, retention_policy=RETENTION_POLICY)
    request_headers = headers({"actor_user_id": context["actors"]["curator"], "submission_intent": proposal,
                               "expected_intent_sha256": digest(proposal)})
    request_headers.pop(missing)
    response = await client.post(BASE, content=b"PRIVATE", headers=request_headers)
    assert response.status_code == 400, response.text
    private(response)


@pytest.mark.parametrize("body", [b'{"request_key":"private","expected_intent_sha256":"bad"}',
    b'{"request_key":"private","request_key":"duplicate"}', b'{"approved":true}', b'[]'])
async def test_closed_lookup_rejects_untrusted_fields_without_echo(client, db_session, body):
    context, _, _ = await setup(db_session)
    await db_session.commit()
    response = await client.post(BASE + "/outcome", content=body,
        headers={**auth(context["actors"]["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 400
    assert "private" not in response.text and "approved" not in response.text
    private(response)


async def test_flag_off_before_body(client, monkeypatch):
    monkeypatch.setenv("ML_USE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    response = await client.post(BASE, content=b"PRIVATE")
    assert response.status_code == 404
    private(response)


@pytest.mark.parametrize("change", ["session_version", "is_admin", "is_active", "email_verified"])
async def test_account_change_after_inspection_prevents_commit(client, db_session, monkeypatch, change):
    _, args, values = await prepared(db_session)
    await db_session.commit()
    async def rebuilt(_user, raw):
        return raw, {}, args["reconstruction"]
    async def inspect(_user, _raw, _rebuilt):
        await db_session.execute(sa.update(User).where(User.id == args["actor_user_id"]).values(
            **{change: 1 if change == "session_version" else False}))
        await db_session.commit()
        return values["observation"]
    monkeypatch.setattr(router.preflight, "_rebuild_bytes", rebuilt)
    monkeypatch.setattr(router, "_inspect", inspect)
    result = await client.post(BASE, content=args["raw"], headers=headers(values))
    assert result.status_code == 403, result.text
    assert not any(row["actor_user_id"] == str(args["actor_user_id"]) for row in (await state(db_session))[TABLES[0]])
    private(result)


async def test_concurrent_identical_submit_has_one_durable_outcome(client, db_session, monkeypatch):
    _, args, values = await prepared(db_session)
    await db_session.commit()
    async def rebuilt(_user, raw):
        return raw, {}, args["reconstruction"]
    async def inspect(_user, _raw, _rebuilt):
        return values["observation"]
    monkeypatch.setattr(router.preflight, "_rebuild_bytes", rebuilt)
    monkeypatch.setattr(router, "_inspect", inspect)
    results = await asyncio.gather(*(client.post(BASE, content=args["raw"], headers=headers(values)) for _ in range(2)))
    assert all(result.status_code in {200, 503} for result in results), [result.text for result in results]
    assert any(result.status_code == 200 for result in results)
    retry = await client.post(BASE, content=args["raw"], headers=headers(values))
    assert retry.status_code == 200 and retry.json()["replayed"], retry.text
    rows = [row for row in (await state(db_session))[TABLES[0]] if row["actor_user_id"] == str(args["actor_user_id"])]
    assert len(rows) == 1 and retry.json()["submission_id"] == rows[0]["id"]
