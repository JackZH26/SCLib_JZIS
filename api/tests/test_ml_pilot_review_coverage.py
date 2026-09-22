"""Actual owned SQL, original-file worker and HTTP; no real scientific signoff."""

from __future__ import annotations

import base64
from copy import deepcopy

import pytest

from config import get_settings
from services import ml_pilot_accounting as accounting
from services import ml_pilot_attestations as attestations
from services import ml_pilot_review_documents as documents
from tests.test_ml_pilot_attestations import URL, payload, signed
from tests.test_ml_pilot_attestations import enabled as enabled
from tests.test_ml_pilot_registration import confirmed, decision_args
from tests.test_ml_pilot_registration_http import acceptance_headers
from tests.test_ml_pilot_review_admission import packet, prepared, replace_document
from tests.test_research_freeze import db_session as db_session


async def coverage(client, member, upload):
    result = await client.post(URL + "/coverage", json=upload, headers=acceptance_headers(member))
    assert result.status_code == 200, result.text
    return result.json()


def for_member(value, member):
    result = deepcopy(value)
    result["parameters"].update(
        participant_id=member["id"],
        participant_sha256=member["record_sha256"],
        registration_sha256=member["registration_sha256"],
    )
    return result


@pytest.mark.parametrize("case", ["conclusion", "review", "raw_bytes", "participation"])
async def test_old_declarations_do_not_cover_changed_originals_or_reaccepted_participation(
    client, db_session, case
):
    f, first, heads, at = await prepared(db_session)
    members = first["participants"]
    own = members[0]
    for member in members:
        await signed(client, payload(f, member, at), member)
    upload = packet(f, own, at)
    assert (await coverage(client, own, upload))["account_declarations_complete"]
    if case == "conclusion":
        replace_document(
            upload,
            "conclusion",
            lambda value: value.update(rationale="SYNTHETIC revised rationale"),
        )
    elif case == "review":
        rows = replace_document(
            upload,
            "reviews",
            lambda rows: rows[0].update(outcome_reason="SYNTHETIC changed failure"),
        )
        upload["review_log_sha256"] = accounting.review_hash(rows)
        replace_document(
            upload,
            "conclusion",
            lambda value: value.update(review_log_sha256=upload["review_log_sha256"]),
        )
    elif case == "raw_bytes":
        raw = base64.b64decode(upload["reviews_base64"]) + b"\n"
        upload.update(
            reviews_base64=base64.b64encode(raw).decode(), reviews_file_sha256=documents.sha(raw)
        )
    else:
        withdrawn = (
            await confirmed(
                db_session,
                decision_args(own, f["inputs"], decision="withdraw", prior=heads[own["id"]]),
            )
        )["decision"]
        await db_session.commit()
        unavailable = await client.post(
            URL + "/coverage", json=upload, headers=acceptance_headers(own)
        )
        assert unavailable.status_code == 409
        await confirmed(db_session, decision_args(own, f["inputs"], prior=withdrawn))
        await db_session.commit()
    value = await coverage(client, own, upload)
    assert not value["account_declarations_complete"]
    assert value["stale_declaration_count"] == (1 if case == "participation" else 3)
    assert value["matching_declaration_count"] == (2 if case == "participation" else 0)
    assert value["own_declaration_status"] == "stale"
    # A new exact own declaration replaces only that account's stale head.
    new = payload(f, own, at)
    new.update(
        {key: value for key, value in upload.items() if key not in {"parameters", "version"}}
    )
    inspected = await client.post(
        URL + "/inspect", json=upload["parameters"], headers=acceptance_headers(own)
    )
    head = inspected.json()["head"]
    new["parameters"].update(supersedes_id=head["id"], supersedes_sha256=head["record_sha256"])
    await signed(client, new, own)
    after = await coverage(client, own, upload)
    assert after["stale_declaration_count"] == (0 if case == "participation" else 2)
    assert after["account_declarations_complete"] is (case == "participation")


async def test_unused_arbitrator_is_not_required_to_declare_nonexistent_reviews(client, db_session):
    f, first, _, at = await prepared(db_session)
    members = first["participants"]
    primary = next(m for m in members if m["roles"] == ["primary"])
    unused = next(m for m in members if m["roles"] == ["arbitration"])
    selected = accounting._loads(f["inputs"]["selection_raw"].decode())
    author_alias = next(row["id"] for row in selected["reviewers"] if row["roles"] == ["primary"])
    original = packet(f, primary, at)
    replace_document(original, "conclusion", lambda value: value.update(reviewer_id=author_alias))
    for member in members:
        if member == unused:
            continue
        value = payload(f, member, at)
        value.update(
            {key: item for key, item in original.items() if key not in {"parameters", "version"}}
        )
        await signed(client, value, member)
    checked = await coverage(client, unused, for_member(original, unused))
    assert checked["required_declaration_count"] == checked["matching_declaration_count"] == 2
    assert checked["account_declarations_complete"]
    assert checked["own_declaration_status"] == "not_required"
    assert checked["conclusion_author_declaration_current"]
    assert not checked["current_collective_signoff_verified"]


async def test_coverage_flag_rejects_before_worker_or_body(client, db_session, monkeypatch):
    f, first, _, at = await prepared(db_session)
    member = first["participants"][0]
    monkeypatch.setenv("ML_PILOT_ATTESTATIONS_ENABLED", "false")
    get_settings.cache_clear()
    from routers import ml_pilot_registration as router

    async def forbidden(*args, **kwargs):
        pytest.fail("Disabled coverage must not receive source bytes")

    monkeypatch.setattr(router, "upload", forbidden)
    monkeypatch.setattr(router.review_worker, "check_in_worker", forbidden)
    result = await client.post(
        URL + "/coverage", json=packet(f, member, at), headers=acceptance_headers(member)
    )
    assert result.status_code == 404


async def test_concurrent_withdrawal_does_not_mix_two_database_snapshots(
    client, db_session, monkeypatch
):
    f, first, _, at = await prepared(db_session)
    members = first["participants"]
    records = {
        member["id"]: await signed(client, payload(f, member, at), member) for member in members
    }
    original = attestations.head
    fired = False

    async def concurrent(db, participant):
        nonlocal fired
        result = await original(db, participant)
        if not fired:
            fired = True
            target = next(member for member in members if member["id"] != str(participant))
            controls = payload(f, target, at, previous=records[target["id"]])["parameters"]
            preview = await client.post(
                URL + "/withdraw", json=controls, headers=acceptance_headers(target)
            )
            assert preview.status_code == 200, preview.text
            controls.update(
                dry_run=False, expected_intent_sha256=preview.json()["result"]["intent_sha256"]
            )
            committed = await client.post(
                URL + "/withdraw", json=controls, headers=acceptance_headers(target)
            )
            assert committed.status_code == 200, committed.text
        return result

    monkeypatch.setattr(attestations, "head", concurrent)
    own = members[0]
    old = await coverage(client, own, packet(f, own, at))
    assert fired and old["account_declarations_complete"] and old["historical_snapshot_only"]
    new = await coverage(client, own, packet(f, own, at))
    assert not new["account_declarations_complete"]
    assert new["withdrawn_declaration_count"] == 1 and new["matching_declaration_count"] == 2
