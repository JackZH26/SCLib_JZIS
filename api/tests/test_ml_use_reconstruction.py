"""Authenticated reconstruction-route boundaries; mocked worker cases are explicit."""
from __future__ import annotations

import hashlib

import pytest
import sqlalchemy as sa

from models.db import User
from routers import ml_use_preflight as router
from services import ml_use_reconstruction_worker as worker
from services.ml_audited_dataset import canonical
from services.ml_use_reconstruction import MAX_ENVELOPE_BYTES, VERSION
from tests.test_ml_use_governance import arguments, decide
from tests.test_ml_use_preflight import db_session as db_session
from tests.test_ml_use_preflight import enabled as enabled
from tests.test_ml_use_preflight import private, setup
from tests.test_research_distribution_operators import auth

BASE = "/v1/ml/use/preflight/reconstruct"


@pytest.mark.parametrize("identity", [None, "admin", "member", "reviewer", "publisher"])
@pytest.mark.parametrize("suffix", ["", "/current"])
async def test_admission_before_upload_and_worker(client, db_session, monkeypatch, identity, suffix):
    context, _, _ = await setup(db_session)
    await db_session.commit()

    async def forbidden(*_a, **_k):
        pytest.fail("private input consumed before admission")
    monkeypatch.setattr(router, "_reconstruction_body", forbidden)
    monkeypatch.setattr(worker, "reconstruct_in_worker", forbidden)
    response = await client.post(BASE + suffix, content=b"PRIVATE", headers={"Content-Type": "application/json",
        **({} if identity is None else auth(context["actors"][identity]))})
    assert response.status_code == (401 if identity is None else 403), response.text
    private(response)


@pytest.mark.parametrize("change", ["session", "admin", "active", "verified", "requester", "curator"])
@pytest.mark.parametrize("suffix", ["", "/current"])
async def test_current_admission_rechecked_after_cpu_worker(client, db_session, monkeypatch, change, suffix):
    from services import research_publication
    context, body, membership = await setup(db_session)
    people = context["actors"]
    await db_session.commit()
    envelope = {**body, "version": VERSION, "inputs_base64": {}, "artifacts_base64": {}}

    async def synthetic_worker(raw):
        if change in {"session", "admin", "active", "verified"}:
            values = {"session": {"session_version": 1}, "admin": {"is_admin": False},
                      "active": {"is_active": False}, "verified": {"email_verified": False}}[change]
            await db_session.execute(sa.update(User).where(User.id == people["curator"]).values(**values))
        elif change == "requester":
            await decide(db_session, arguments(people, user_id=str(people["curator"]), action="revoke", previous=membership["decision"]))
        else:
            await research_publication.revoke_role(db_session, actor_user_id=people["admin"],
                grant_id=people["grants"]["curator"], reason_code="synthetic_revoke", dry_run=False)
        await db_session.commit()
        return {"request_sha256": body["expected_request_sha256"], "envelope_sha256": hashlib.sha256(raw).hexdigest(),
                "all_eight_input_bytes_verified": True, "dataset_and_preparation_rebuilt": True}
    monkeypatch.setattr(worker, "reconstruct_in_worker", synthetic_worker)
    response = await client.post(BASE + suffix, content=canonical(envelope),
        headers={**auth(people["curator"]), "Content-Type": "application/json"})
    assert response.status_code == 403, response.text
    private(response)


@pytest.mark.parametrize("raw,headers,expected", [
    (b"{}", {"Content-Type": "text/plain"}, 415),
    (b"{}", {"Content-Type": "application/json", "Content-Encoding": "gzip"}, 415),
    (b"{}", {"Content-Type": "application/json", "Content-Length": str(MAX_ENVELOPE_BYTES + 1)}, 413),
    (b'{}\n', {"Content-Type": "application/json"}, 400),
    (b'{"private":true,"private":false}', {"Content-Type": "application/json"}, 400),
    (b'{"secret":NaN}', {"Content-Type": "application/json"}, 400),
])
@pytest.mark.parametrize("suffix", ["", "/current"])
async def test_closed_bounded_private_upload(client, db_session, raw, headers, expected, suffix):
    context, _, _ = await setup(db_session)
    await db_session.commit()
    response = await client.post(BASE + suffix, content=raw, headers={**auth(context["actors"]["curator"]), **headers})
    assert response.status_code == expected, response.text
    assert "secret" not in response.text and "private" not in response.text
    private(response)


@pytest.mark.parametrize("suffix", ["", "/current"])
async def test_worker_timeout_sanitized_and_capacity_released(client, db_session, monkeypatch, suffix):
    context, body, _ = await setup(db_session)
    await db_session.commit()

    async def timeout(_):
        raise TimeoutError("PRIVATE_INPUT")
    monkeypatch.setattr(worker, "reconstruct_in_worker", timeout)
    raw = canonical({**body, "version": VERSION, "inputs_base64": {}, "artifacts_base64": {}})
    headers = {**auth(context["actors"]["curator"]), "Content-Type": "application/json"}
    for _ in range(3):
        result = await client.post(BASE + suffix, content=raw, headers=headers)
        assert result.status_code == 503 and "PRIVATE_INPUT" not in result.text
        private(result)
    assert router._slots.acquire(blocking=False)
    assert router._slots.acquire(blocking=False)
    router._slots.release()
    router._slots.release()
