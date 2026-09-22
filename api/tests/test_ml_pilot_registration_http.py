"""Actual authenticated HTTP and child checks; all study/person data synthetic."""

from __future__ import annotations

import base64
import json

import pytest
import sqlalchemy as sa

from config import get_settings
from models.db import Base
from models.ml_pilot_registration_v1 import TABLES
from routers import ml_pilot_registration as router
from tests.test_ml_pilot_registration import decision_args, fixture, no_authority, registered
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session

BASE = "/v1/ml/pilots"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("ML_PILOT_REGISTRATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def upload(f, member=None):
    values = f["args"]
    parameters = (
        {"curator_grant_id": values["curator_grant_id"], "request_key": values["request_key"]}
        if member is None
        else {
            k: v
            for k, v in decision_args(member, f["inputs"]).items()
            if k not in {"actor_user_id", "decision", "document_check"}
        }
    )
    parameters.update(dry_run=True, expected_intent_sha256=None)
    return {
        "version": "ml08-registration-upload/1.0.0",
        "operation": "register" if member is None else "accept",
        "parameters": parameters,
        **{k: v for k, v in f["inputs"].items() if k.endswith("sha256")},
        "selection_base64": base64.b64encode(f["inputs"]["selection_raw"]).decode(),
        "protocol_base64": base64.b64encode(f["inputs"]["protocol_raw"]).decode(),
        **({"bindings": f["bindings"]} if member is None else {}),
    }


def acceptance_headers(member):
    return {
        **auth(member["user_id"]),
        "X-SCLib-Participant-Id": member["id"],
        "X-SCLib-Participant-Sha256": member["record_sha256"],
    }


async def http_registration(client, f):
    payload = upload(f)
    headers = auth(f["people"][0])
    preview = await client.post(BASE + "/registrations", json=payload, headers=headers)
    assert preview.status_code == 200, preview.text
    payload["parameters"].update(
        dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"]
    )
    committed = await client.post(BASE + "/registrations", json=payload, headers=headers)
    assert committed.status_code == 200 and committed.json()["committed"], committed.text
    assert committed.headers["cache-control"] == "private, no-store"
    assert committed.headers["x-content-type-options"] == "nosniff"
    return payload, committed.json()["result"]


async def test_http_real_worker_registration_own_acceptance_and_private_inspection(
    client, db_session
):
    f = await fixture(db_session)
    await db_session.commit()
    payload, registered_result = await http_registration(client, f)
    no_authority(registered_result)
    assert "PRIVATE_SYNTHETIC_SOURCE" not in json.dumps(registered_result)
    for member in registered_result["participants"]:
        proposal = upload(f, member)
        headers = acceptance_headers(member)
        preview = await client.post(BASE + "/participation/accept", json=proposal, headers=headers)
        assert preview.status_code == 200, preview.text
        proposal["parameters"].update(
            dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"]
        )
        accepted = await client.post(BASE + "/participation/accept", json=proposal, headers=headers)
        assert accepted.status_code == 200 and accepted.json()["committed"], accepted.text
        no_authority(accepted.json()["result"])
    reg = registered_result["registration"]
    observed = await client.post(
        BASE + "/inspect",
        json={"registration_id": reg["id"], "registration_sha256": reg["record_sha256"]},
        headers=auth(f["people"][0]),
    )
    assert observed.status_code == 200 and observed.json()["ready_for_prospective_review"], (
        observed.text
    )
    no_authority(observed.json())
    replay = await client.post(BASE + "/registrations", json=payload, headers=auth(f["people"][0]))
    assert replay.status_code == 200 and replay.json()["result"]["replayed"]
    assert replay.json()["result"]["participant_confirmations_checked"] is False


@pytest.mark.parametrize("case", ["disabled", "anonymous", "nonregistrar"])
async def test_admission_precedes_body_or_worker(client, db_session, monkeypatch, case):
    f = await fixture(db_session)
    await db_session.commit()

    async def forbidden(*_args, **_kwargs):
        pytest.fail("Private body/worker entered before admission")

    monkeypatch.setattr(router, "upload", forbidden)
    monkeypatch.setattr(router.worker, "check_in_worker", forbidden)
    if case == "disabled":
        monkeypatch.setenv("ML_PILOT_REGISTRATION_ENABLED", "false")
        get_settings.cache_clear()
    response = await client.post(
        BASE + "/registrations",
        content=b"PRIVATE_BAD_JSON",
        headers={}
        if case == "anonymous"
        else auth(f["people"][1 if case == "nonregistrar" else 0]),
    )
    assert response.status_code == {"disabled": 404, "anonymous": 401, "nonregistrar": 403}[case], (
        response.text
    )
    assert "PRIVATE_BAD_JSON" not in response.text


async def test_cross_account_invitation_is_hidden_before_upload_even_with_wrong_pin(
    client, db_session, monkeypatch
):
    f = await fixture(db_session)
    first = await registered(db_session, f["args"])
    await db_session.commit()
    member = first["participants"][0]

    async def forbidden(*_args, **_kwargs):
        pytest.fail("Foreign invitation must not receive source bytes")

    monkeypatch.setattr(router, "upload", forbidden)
    for pin in (member["record_sha256"], "f" * 64):
        response = await client.post(
            BASE + "/participation/accept",
            content=b"PRIVATE_SOURCE",
            headers={
                **auth(f["people"][0]),
                "X-SCLib-Participant-Id": member["id"],
                "X-SCLib-Participant-Sha256": pin,
            },
        )
        assert response.status_code == 404, response.text


async def test_session_revocation_after_real_worker_prevents_registration(
    client, db_session, monkeypatch
):
    f = await fixture(db_session)
    await db_session.commit()
    original = router.worker.check_in_worker

    async def changed(raw):
        result = await original(raw)
        users = Base.metadata.tables["users"]
        await db_session.execute(
            users.update()
            .where(users.c.id == f["people"][0])
            .values(session_version=users.c.session_version + 1)
        )
        await db_session.commit()
        return result

    monkeypatch.setattr(router.worker, "check_in_worker", changed)
    response = await client.post(
        BASE + "/registrations", json=upload(f), headers=auth(f["people"][0])
    )
    assert response.status_code == 403, response.text
    assert not await db_session.scalar(
        sa.select(
            sa.exists(
                sa.select(Base.metadata.tables[TABLES[0]].c.id).where(
                    Base.metadata.tables[TABLES[0]].c.actor_user_id == f["people"][0]
                )
            )
        )
    )


async def test_commit_response_loss_recovers_exact_historical_registration_without_worker(
    client, db_session, monkeypatch
):
    f = await fixture(db_session)
    await db_session.commit()
    proposal = upload(f)
    headers = auth(f["people"][0])
    preview = await client.post(BASE + "/registrations", json=proposal, headers=headers)
    assert preview.status_code == 200, preview.text
    pin = preview.json()["result"]["intent_sha256"]
    proposal["parameters"].update(dry_run=False, expected_intent_sha256=pin)
    original = router.write

    async def lost(*args, **kwargs):
        await original(*args, **kwargs)
        raise TimeoutError("PRIVATE_COMPLETED_RESPONSE")

    monkeypatch.setattr(router, "write", lost)
    lost_reply = await client.post(BASE + "/registrations", json=proposal, headers=headers)
    assert lost_reply.status_code == 503 and lost_reply.headers["x-operation-state"] == "unknown", (
        lost_reply.text
    )
    assert "PRIVATE_COMPLETED_RESPONSE" not in lost_reply.text

    async def forbidden(_raw):
        pytest.fail("Recovery must not reparse files or create a new operation")

    monkeypatch.setattr(router.worker, "check_in_worker", forbidden)
    recovered = await client.post(
        BASE + "/registrations/outcome",
        json={"request_key": proposal["parameters"]["request_key"], "expected_intent_sha256": pin},
        headers=headers,
    )
    assert recovered.status_code == 200 and recovered.json()["result"]["replayed"], recovered.text
    assert recovered.json()["result"]["registration_recorded"]
