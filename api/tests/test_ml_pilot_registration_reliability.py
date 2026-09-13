"""Actual owned SQL/HTTP chronology and colliding-writer checks; synthetic study."""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from datetime import timedelta

import pytest
import sqlalchemy as sa

from models.ml_pilot_registration_v1 import TABLES
from services import ml_pilot_accounting as accounting
from services import ml_pilot_registration as service
from services import ml_pilot_registration_documents as documents
from services.ml_pilot_documents import json_value
from services.ml_use_preflight import MlUsePreflightConflict
from tests.test_ml_label_capture import read_snapshot
from tests.test_ml_pilot_registration import (
    confirmed,
    decision_args,
    fixture,
    no_authority,
    registered,
)
from tests.test_ml_pilot_registration_http import (
    BASE,
    acceptance_headers,
    http_registration,
    upload,
)
from tests.test_ml_pilot_registration_http import enabled as enabled
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state


def retime(f, *, selected_at=None, frozen_at):
    selection = json_value(f["inputs"]["selection_raw"])
    selection["frozen_at"] = frozen_at
    if selected_at is not None:
        selection["selected_at"] = selected_at
    selection["selection_sha256"] = accounting.selection_hash(selection)
    raw = accounting.canonical(selection)
    f["inputs"].update(
        selection_raw=raw,
        selection_sha256=selection["selection_sha256"],
        selection_file_sha256=documents.sha(raw),
    )
    f["args"]["commitment"] = documents.check(**f["inputs"], bindings=f["bindings"])


@pytest.mark.parametrize("dry_run", [True, False])
async def test_future_declared_freeze_is_rejected_by_actual_database_clock_without_rows(
    db_session, dry_run
):
    f = await fixture(db_session)
    now = await db_session.scalar(sa.select(sa.func.clock_timestamp()))
    retime(f, frozen_at=(now + timedelta(days=1)).isoformat())
    before = await state(db_session)
    # Pure document consistency alone can pass; persistence must compare the DB clock.
    assert f["args"]["commitment"]["selected_candidates"] == 60
    args = f["args"]
    intent = {
        "version": service.INTENT_VERSION,
        **{k: str(args[k]) for k in ("actor_user_id", "curator_grant_id", "request_key")},
        **{
            k: args["commitment"][k]
            for k in ("selection_sha256", "selection_file_sha256", "protocol_file_sha256")
        },
        "roster_sha256": service.digest(args["commitment"]["participant_bindings"]),
        "implementation_sha256": service.digest(args["implementation"]),
    }
    with pytest.raises(ValueError, match="invalid_pilot_registration_documents"):
        await service.register(
            db_session, **args, dry_run=dry_run, expected_intent_sha256=service.digest(intent)
        )
    assert await state(db_session) == before


async def test_exact_timezone_instants_and_acceptance_cannot_move_freeze_after_registration(
    db_session,
):
    f = await fixture(db_session)
    retime(f, selected_at="2026-09-02T08:00:00+08:00", frozen_at="2026-09-02T00:00:00.000001Z")
    first = await registered(db_session, f["args"])
    args = decision_args(first["participants"][0], f["inputs"])
    valid = deepcopy(args["document_check"])
    before = await state(db_session)
    # Explicit internal verifier-output adversary, not a client upload capability.
    now = await db_session.scalar(sa.select(sa.func.clock_timestamp()))
    args["document_check"]["selection_chronology"]["frozen_at"] = now.isoformat(
        timespec="microseconds"
    )
    with pytest.raises(ValueError):
        await service.decide(db_session, **args)
    assert await state(db_session) == before
    args["document_check"] = valid
    accepted = await confirmed(db_session, args)
    no_authority(accepted)


async def test_older_verifier_policy_is_readable_but_not_retroactively_current(
    db_session, monkeypatch
):
    f = await fixture(db_session)
    legacy = documents.implementation()
    legacy["version"] = "ml08-registration-documents/1.0.0"
    # Synthetic compatibility branch fixture; not relabeling an archived receipt.
    with monkeypatch.context() as m:
        m.setattr(documents, "implementation", lambda: legacy)
        first = await registered(db_session, {**f["args"], "implementation": legacy})
    member = first["participants"][0]
    before = await state(db_session)
    with pytest.raises(MlUsePreflightConflict):
        await service.decide(db_session, **decision_args(member, f["inputs"]))
    assert await state(db_session) == before
    await db_session.commit()
    await read_snapshot(db_session)
    inspected = await service.inspect(
        db_session,
        actor_user_id=f["people"][0],
        registration_id=first["registration"]["id"],
        registration_sha256=first["registration"]["record_sha256"],
    )
    assert inspected["registration_document_check_version"] == legacy["version"]
    assert not inspected["current_registration_document_policy"]
    assert not inspected["ready_for_prospective_review"]
    no_authority(inspected)
    recovered = await service.outcome(
        db_session,
        actor_user_id=f["people"][0],
        kind="registration",
        request_key=f["args"]["request_key"],
        expected_intent_sha256=first["intent_sha256"],
    )
    assert recovered["registration"] == first["registration"]


async def test_future_freeze_http_real_worker_rejects_sanitized_without_persisting(
    client, db_session
):
    f = await fixture(db_session)
    now = await db_session.scalar(sa.select(sa.func.clock_timestamp()))
    retime(f, frozen_at=(now + timedelta(days=1)).isoformat())
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(
        BASE + "/registrations", json=upload(f), headers=auth(f["people"][0])
    )
    assert response.status_code == 400 and response.headers["cache-control"] == "private, no-store"
    assert "SYNTHETIC" not in response.text and "PRIVATE_SYNTHETIC_SOURCE" not in response.text
    assert await state(db_session) == before


async def test_changed_acceptance_file_fails_after_real_worker_even_with_new_self_consistent_hashes(
    client, db_session
):
    f = await fixture(db_session)
    await db_session.commit()
    _, first = await http_registration(client, f)
    member = first["participants"][0]
    proposal = upload(f, member)
    raw = base64.b64decode(proposal["selection_base64"]) + b"\n"
    proposal.update(
        selection_base64=base64.b64encode(raw).decode(), selection_file_sha256=documents.sha(raw)
    )
    before = await state(db_session)
    await db_session.rollback()
    response = await client.post(
        BASE + "/participation/accept", json=proposal, headers=acceptance_headers(member)
    )
    assert response.status_code == 409, response.text
    assert await state(db_session) == before


@pytest.mark.parametrize("operation", ["registration", "acceptance", "competing_decision"])
async def test_actual_colliding_writers_single_durable_history_and_exact_recovery(
    client, db_session, monkeypatch, operation
):
    f = await fixture(db_session)
    await db_session.commit()
    headers = auth(f["people"][0])
    if operation == "registration":
        proposal, endpoint, function = upload(f), "/registrations", "register"
        table_name, kind = TABLES[0], "registration"
    else:
        _, first = await http_registration(client, f)
        member = first["participants"][0]
        proposal, endpoint, function = upload(f, member), "/participation/accept", "decide"
        headers, table_name, kind = acceptance_headers(member), TABLES[2], "participation"
    preview = await client.post(BASE + endpoint, json=proposal, headers=headers)
    assert preview.status_code == 200, preview.text
    pin = preview.json()["result"]["intent_sha256"]
    proposal["parameters"].update(dry_run=False, expected_intent_sha256=pin)
    second, second_endpoint = deepcopy(proposal), endpoint
    if operation == "competing_decision":
        second = {
            **proposal["parameters"],
            "request_key": "synthetic-competing-decline",
            "decision": "decline",
            "dry_run": True,
            "expected_intent_sha256": None,
        }
        second_endpoint = "/participation/decisions"
        other_preview = await client.post(BASE + second_endpoint, json=second, headers=headers)
        assert other_preview.status_code == 200, other_preview.text
        second.update(
            dry_run=False, expected_intent_sha256=other_preview.json()["result"]["intent_sha256"]
        )
    entered, release = asyncio.Event(), asyncio.Event()
    original, held, sqlstates = getattr(service, function), [], []

    async def held_after_actual_lock(db, **args):
        if not held:
            held.append(await db.scalar(sa.text("SELECT pg_backend_pid()")))
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
        return await original(db, **args)

    def observed_error(context):
        sqlstates.append(getattr(context.original_exception, "sqlstate", None))

    monkeypatch.setattr(service, function, held_after_actual_lock)
    sa.event.listen(sa.engine.Engine, "handle_error", observed_error)
    task = asyncio.create_task(client.post(BASE + endpoint, json=proposal, headers=headers))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        collision = await client.post(BASE + second_endpoint, json=second, headers=headers)
        assert collision.status_code == 503, collision.text
        assert "55P03" in sqlstates  # actual PostgreSQL try-lock refusal, not a transport double
    finally:
        release.set()
        first_reply = await task
        sa.event.remove(sa.engine.Engine, "handle_error", observed_error)
    assert first_reply.status_code == 200 and first_reply.json()["committed"], first_reply.text
    before_retry = await state(db_session)
    await db_session.rollback()
    retry = await client.post(BASE + second_endpoint, json=second, headers=headers)
    if operation == "competing_decision":
        assert retry.status_code == 409, retry.text  # original root is now stale
    else:
        assert retry.status_code == 200 and retry.json()["result"]["replayed"], retry.text
    assert await state(db_session) == before_retry
    await db_session.rollback()
    recovered = await client.post(
        BASE + ("/registrations/outcome" if kind == "registration" else "/participation/outcome"),
        json={"request_key": proposal["parameters"]["request_key"], "expected_intent_sha256": pin},
        headers=headers,
    )
    assert recovered.status_code == 200 and recovered.json()["result"]["replayed"], recovered.text
    record_key = "registration" if kind == "registration" else "decision"
    record = first_reply.json()["result"][record_key]
    assert recovered.json()["result"][record_key] == record
    after = await state(db_session)
    assert after == before_retry
    rows = [r for r in after[table_name] if r["actor_user_id"] == record["actor_user_id"]]
    assert len(rows) == 1 and rows[0]["id"] == record["id"]
    no_authority(recovered.json()["result"])
