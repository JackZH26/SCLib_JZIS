"""Owned SQL and authenticated HTTP; all people/events/assertions are synthetic."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from config import get_settings
from models.ml_pilot_attestations_v1 import TABLE, VERSION
from routers import ml_pilot_registration as router
from services import ml_pilot_attestation_contract as contract
from services import ml_pilot_attestations as service
from services import ml_pilot_review_worker as worker
from services.research_publication import revoke_role
from tests.test_ml_pilot_registration import confirmed, decision_args
from tests.test_ml_pilot_registration_http import BASE, acceptance_headers
from tests.test_ml_pilot_review_admission import packet, prepared
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state

URL = BASE + "/review-attestations"


async def count(db, member):
    return await db.scalar(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE participant_id=CAST(:id AS uuid)"),
        {"id": member["id"]},
    )


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    for name in (
        "ML_PILOT_REGISTRATION_ENABLED",
        "ML_PILOT_REVIEW_INTAKE_ENABLED",
        "ML_PILOT_ATTESTATIONS_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def payload(f, member, at, *, previous=None):
    value = packet(f, member, at)
    value["version"] = worker.ATTESTATION_VERSION
    value["parameters"].update(
        request_key="synthetic-declaration-" + uuid4().hex,
        reason_code="review_completed",
        supersedes_id=None if previous is None else previous["id"],
        supersedes_sha256=None if previous is None else previous["record_sha256"],
        declaration_version="ml08-own-review-declaration/1.0.0",
        declaration_sha256=contract.SHA256,
        declaration_acknowledged=True,
        expected_intent_sha256=None,
        dry_run=True,
    )
    return value


async def signed(client, value, member, *, return_response=False):
    preview = await client.post(URL, json=value, headers=acceptance_headers(member))
    assert preview.status_code == 200, preview.text
    assert preview.json()["result"]["declaration"] is None
    value["parameters"].update(
        dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"]
    )
    saved = await client.post(URL, json=value, headers=acceptance_headers(member))
    assert saved.status_code == 200, saved.text
    return saved if return_response else saved.json()["result"]["declaration"]


async def test_actual_three_account_preview_commit_and_exact_recovery(client, db_session, tmp_path):
    root = Path(__file__).resolve().parents[2]
    paths = sorted(
        {
            *(root / "api/models").glob("*.py"),
            *(root / "api/services").glob("*.py"),
            *(root / "api/services").glob("*.schema.json"),
            *(root / "api/routers").glob("*.py"),
            *(root / "api/tests").glob("*.py"),
            *(root / "scripts").glob("*.py"),
            root / "api/main.py",
            root / "api/config.py",
        }
    )

    def pins():
        return [
            {
                "path": str(path.relative_to(root)),
                "sha256": worker.documents.sha(path.read_bytes()),
            }
            for path in paths
        ]

    capture = {
        "fixture_notice": "Actual owned SQL, authenticated HTTP and installed review worker; all account identities, events and declarations are synthetic, not a real independent review or pilot acceptance.",
        "capture_test_path": "api/tests/test_ml_pilot_attestations.py",
        "source_pins": pins(),
        "participants": [],
    }
    f, first, _, at = await prepared(db_session)
    records = []
    for member in first["participants"]:
        wording = await client.get(URL + "/declaration", headers=auth(member["user_id"]))
        assert wording.status_code == 200
        assert wording.json()["declaration_text"] == contract.TEXT
        assert wording.json()["declaration_sha256"] == contract.SHA256
        value = payload(f, member, at)
        before = await state(db_session)
        await db_session.rollback()
        preview = await client.post(URL, json=value, headers=acceptance_headers(member))
        assert preview.status_code == 200, preview.text
        assert preview.json()["version"] == VERSION and preview.json()["committed"] is False
        assert not preview.json()["result"]["declaration_recorded"]
        assert await state(db_session) == before
        await db_session.rollback()
        original_upload = deepcopy(value)
        saved = await signed(client, value, member, return_response=True)
        record = saved.json()["result"]["declaration"]
        records.append(record)
        assert record["actor_user_id"] == member["user_id"]
        assert record["basis"]["selected_candidates"] == 60
        assert record["basis"]["review_record_count"] == 61
        assert record["basis"]["recorded_recommendation"] == "stop"
        again = await client.post(URL, json=value, headers=acceptance_headers(member))
        assert again.status_code == 200 and again.json()["result"]["replayed"]
        lookup = {
            "request_key": value["parameters"]["request_key"],
            "expected_intent_sha256": value["parameters"]["expected_intent_sha256"],
        }
        recovered = await client.post(
            URL + "/outcome", json=lookup, headers=auth(member["user_id"])
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["result"]["declaration"] == record
        capture["participants"].append(
            {
                "actor_user_id": member["user_id"],
                "upload": original_upload,
                "declaration_wording": wording.text,
                "preview": preview.text,
                "committed": saved.text,
                "replayed": again.text,
                "recovered": recovered.text,
            }
        )
        for key, expected in service.boundary().items():
            assert recovered.json()["result"][key] == expected
        assert recovered.headers["cache-control"] == "private, no-store"
        for other in first["participants"]:
            if other["id"] != member["id"]:
                assert other["user_id"] not in recovered.text
        assert "PRIVATE_SYNTHETIC_SOURCE" not in recovered.text
        assert "SYNTHETIC_UNOPENED_CANARY" not in recovered.text
    assert sorted(r["basis"]["own_review_record_count"] for r in records) == [0, 1, 60]
    assert sum(r["basis"]["conclusion_author_is_current_account"] for r in records) == 1
    assert len({r["basis"]["document_projection_sha256"] for r in records}) == 1
    assert sum([await count(db_session, member) for member in first["participants"]]) == 3
    assert capture["source_pins"] == pins()
    (tmp_path / "ml-pilot-attestations-wire.json").write_text(
        json.dumps(capture, sort_keys=True) + "\n"
    )


def test_attestation_schema_requires_explicit_controls_and_rejects_numeric_consent():
    from pydantic import ValidationError

    control = {
        "participant_id": str(uuid4()),
        "participant_sha256": "a" * 64,
        "registration_sha256": "b" * 64,
        "request_key": "synthetic",
        "reason_code": "synthetic",
        "supersedes_id": None,
        "supersedes_sha256": None,
        "dry_run": True,
        "expected_intent_sha256": None,
        "declaration_version": contract.VERSION,
        "declaration_sha256": contract.SHA256,
        "declaration_acknowledged": True,
    }
    assert {"dry_run", "expected_intent_sha256", "declaration_acknowledged"} <= set(
        router.AttestationControl.model_json_schema()["required"]
    )
    for value in (1, 0, "true", None):
        with pytest.raises(ValidationError):
            router.AttestationControl.model_validate({**control, "declaration_acknowledged": value})
    for name in ("dry_run", "expected_intent_sha256"):
        with pytest.raises(ValidationError):
            router.AttestationControl.model_validate(
                {k: v for k, v in control.items() if k != name}
            )


@pytest.mark.parametrize(
    "flag",
    [
        "ML_PILOT_ATTESTATIONS_ENABLED",
        "ML_PILOT_REVIEW_INTAKE_ENABLED",
        "ML_PILOT_REGISTRATION_ENABLED",
    ],
)
async def test_disabled_before_source_upload(client, db_session, monkeypatch, flag):
    f, first, _, at = await prepared(db_session)
    member = first["participants"][0]
    monkeypatch.setenv(flag, "false")
    get_settings.cache_clear()

    async def forbidden(*args, **kwargs):
        raise AssertionError("source body must not be read")

    monkeypatch.setattr(router, "upload", forbidden)
    r = await client.post(URL, json=payload(f, member, at), headers=acceptance_headers(member))
    assert r.status_code == 404


@pytest.mark.parametrize(
    "case",
    [
        "no_consent",
        "changed_declaration",
        "actor_field",
        "proof_only",
        "unreviewed",
        "header_mismatch",
        "commit_without_preview",
        "old_envelope",
    ],
)
async def test_invalid_or_unbound_upload_cannot_write(client, db_session, case):
    f, first, _, at = await prepared(db_session)
    member = first["participants"][0]
    value = payload(f, member, at)
    if case == "no_consent":
        value["parameters"]["declaration_acknowledged"] = False
    if case == "changed_declaration":
        value["parameters"]["declaration_version"] = "approved"
    if case == "actor_field":
        value["parameters"]["actor_user_id"] = member["user_id"]
    if case == "proof_only":
        value = {"document_check": {"ready": True}}
    if case == "unreviewed":
        value["reviews_base64"] = ""
    if case == "header_mismatch":
        value["parameters"]["participant_id"] = str(uuid4())
    if case == "commit_without_preview":
        value["parameters"]["dry_run"] = False
    if case == "old_envelope":
        value["version"] = worker.VERSION
    r = await client.post(URL, json=value, headers=acceptance_headers(member))
    assert r.status_code in {400, 409}, r.text
    assert "x-operation-state" not in r.headers
    assert await count(db_session, member) == 0


async def test_withdrawal_and_recovery_survive_role_and_participation_revocation(
    client, db_session, monkeypatch
):
    f, first, heads, at = await prepared(db_session)
    member = first["participants"][0]
    value = payload(f, member, at)
    record = await signed(client, value, member)
    await confirmed(
        db_session,
        decision_args(member, f["inputs"], decision="withdraw", prior=heads[member["id"]]),
    )
    await revoke_role(
        db_session,
        actor_user_id=f["people"][0],
        grant_id=member["reviewer_grant_id"],
        reason_code="synthetic",
        dry_run=False,
    )
    await db_session.commit()
    monkeypatch.setenv("ML_PILOT_REVIEW_INTAKE_ENABLED", "false")
    get_settings.cache_clear()
    controls = {
        **value["parameters"],
        "request_key": "synthetic-withdraw-" + uuid4().hex,
        "supersedes_id": record["id"],
        "supersedes_sha256": record["record_sha256"],
        "dry_run": True,
        "expected_intent_sha256": None,
        "reason_code": "review_withdrawn",
    }
    r = await client.post(URL + "/withdraw", json=controls, headers=auth(member["user_id"]))
    assert r.status_code == 200, r.text
    for invalid in (False, 1, "true"):
        rejected = await client.post(
            URL + "/withdraw",
            json={**controls, "declaration_acknowledged": invalid},
            headers=auth(member["user_id"]),
        )
        assert rejected.status_code == 400
        assert await count(db_session, member) == 1
        await db_session.rollback()
    controls.update(dry_run=False, expected_intent_sha256=r.json()["result"]["intent_sha256"])
    withdrawn = await client.post(URL + "/withdraw", json=controls, headers=auth(member["user_id"]))
    assert withdrawn.status_code == 200, withdrawn.text
    new = withdrawn.json()["result"]["declaration"]
    assert new["action"] == "withdraw" and new["basis"] == record["basis"]
    old = await client.post(
        URL + "/outcome",
        json={k: value["parameters"][k] for k in ("request_key", "expected_intent_sha256")},
        headers=auth(member["user_id"]),
    )
    assert old.status_code == 200 and old.json()["result"]["declaration"] == record
    ref = {
        key: value["parameters"][key]
        for key in ("participant_id", "participant_sha256", "registration_sha256")
    }
    inspected = await client.post(URL + "/inspect", json=ref, headers=auth(member["user_id"]))
    assert inspected.status_code == 200 and inspected.json()["head"] == new
    assert (
        inspected.json()["historical_record_only"]
        and not inspected.json()["current_collective_signoff_verified"]
    )
    assert await count(db_session, member) == 2


async def test_current_state_is_rechecked_after_actual_child(client, db_session, monkeypatch):
    f, first, _, at = await prepared(db_session)
    member = first["participants"][0]
    value = payload(f, member, at)
    real = worker.check_in_worker

    async def changed(raw, **kwargs):
        checked = await real(raw, **kwargs)
        other = first["participants"][1]
        await revoke_role(
            db_session,
            actor_user_id=f["people"][0],
            grant_id=other["reviewer_grant_id"],
            reason_code="synthetic",
            dry_run=False,
        )
        await db_session.commit()
        return checked

    monkeypatch.setattr(worker, "check_in_worker", changed)
    r = await client.post(URL, json=value, headers=acceptance_headers(member))
    assert r.status_code == 403, r.text
    assert "x-operation-state" not in r.headers
    assert await count(db_session, member) == 0


async def test_concurrent_roots_do_not_fork_or_duplicate_history(client, db_session):
    f, first, _, at = await prepared(db_session)
    member = first["participants"][0]
    uploads = [payload(f, member, at), payload(f, member, at)]
    for upload in uploads:
        preview = await client.post(URL, json=upload, headers=acceptance_headers(member))
        assert preview.status_code == 200
        upload["parameters"].update(
            dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"]
        )
    replies = await asyncio.gather(
        *(client.post(URL, json=u, headers=acceptance_headers(member)) for u in uploads)
    )
    assert sum(r.status_code == 200 for r in replies) == 1
    assert all(r.status_code in {200, 409, 503} for r in replies)
    assert await count(db_session, member) == 1


@pytest.mark.parametrize(
    "sql",
    [f"UPDATE {TABLE} SET reason_code='tampered'", f"DELETE FROM {TABLE}", f"TRUNCATE {TABLE}"],
)
async def test_actual_sql_immutable_guards(client, db_session, sql):
    f, first, _, at = await prepared(db_session)
    member = first["participants"][0]
    await signed(client, payload(f, member, at), member)
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(sql))
    assert await state(db_session) == before


async def test_foreign_inspection_recovery_and_mutated_idempotency_key_are_refused(
    client, db_session
):
    f, first, _, at = await prepared(db_session)
    member, other = first["participants"][:2]
    value = payload(f, member, at)
    await signed(client, value, member)
    ref = {
        k: value["parameters"][k]
        for k in ("participant_id", "participant_sha256", "registration_sha256")
    }
    r = await client.post(URL + "/inspect", json=ref, headers=auth(other["user_id"]))
    assert r.status_code == 404
    lookup = {k: value["parameters"][k] for k in ("request_key", "expected_intent_sha256")}
    r = await client.post(URL + "/outcome", json=lookup, headers=auth(other["user_id"]))
    assert r.status_code == 404
    altered = deepcopy(value)
    altered["parameters"]["reason_code"] = "changed"
    r = await client.post(URL, json=altered, headers=acceptance_headers(member))
    assert r.status_code == 409
    assert await count(db_session, member) == 1
