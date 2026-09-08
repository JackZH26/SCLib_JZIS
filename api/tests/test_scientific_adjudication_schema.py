"""Native exact-review guards using explicitly synthetic source/reviewer fixtures."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.scientific_adjudication_v1 import LIMITATIONS, PROFILES, REQUEST_VERSION, TABLE_ORDER
from services.research_access import active_grant
from services.research_release_manifest import canonical
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as db_session
from tests.test_scientific_pending_import import _finish, _start, seed_import


async def fixture(db):
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='10s'"))
    result = await seed_import(db)
    started = await _start(db, result)
    finished = await _finish(db, result, started)
    result.update(started=started, finished=finished, property_id=UUID(finished["row_ids"]["property"]))
    result["reviewer"] = result["actors"]["reviewer"]
    result["grant"] = await active_grant(db, result["reviewer"], role="reviewer")
    return result


async def capture(db, property_id):
    body = await db.scalar(sa.text("SELECT sclib_scientific_subject_capture_v1(:id)"), {"id": property_id})
    parsed = json.loads(body)
    sha = hashlib.sha256(body.encode()).hexdigest()
    property_sha = await db.scalar(sa.text("""SELECT sclib_scientific_adjudication_text_hash_v1(
        sclib_scientific_adjudication_canonical_v1(value->'snapshot')) FROM jsonb_array_elements(CAST(:body AS jsonb)->'rows')
        WHERE value->>'table'='event_properties' AND value->>'row_id'=:id"""), {"body": body, "id": str(property_id)})
    values = {key: UUID(value) if key.endswith("_id") and key != "material_id" and value else value
              for key, value in parsed["target"].items()}
    return {"id": uuid4(), **values, "subject_version": parsed["version"], "basis_json": body,
            "subject_sha256": sha, "property_row_sha256": property_sha}


async def item_for(db, subject, *, profile="native-sampled-frequency-extraction/1.0.0", decision="accept", predecessor=None):
    impact = await db.scalar(sa.text("SELECT sclib_scientific_result_impact_capture_v1(:id)"), {"id": subject["property_id"]})
    body = json.loads(subject["basis_json"])
    refs = ([{"artifact_id": row["artifact_id"], "bytes_sha256": row["sha256"]}
             for row in body["native_import"]["source_files"]] if body["native_import"] else
            [{"artifact_id": row["artifact_id"], "bytes_sha256": row["bytes_sha256"]} for row in body["artifacts"]])
    return {"decision_id": str(uuid4()), "subject_id": str(subject["id"]), "property_id": str(subject["property_id"]),
        "scope": PROFILES[profile][0], "profile_version": profile, "expected_subject_sha256": subject["subject_sha256"],
        "expected_previous_decision_id": str(predecessor) if predecessor else None,
        "expected_impact_sha256": hashlib.sha256(impact.encode()).hexdigest(), "decision": decision,
        "reason_code": "evidence_and_scope_match" if decision == "accept" else "scientific_concern" if decision == "reject" else "insufficient_evidence",
        "rationale": "Synthetic review declaration for native guard testing only.", "proposition": PROFILES[profile][1],
        "limitations": list(LIMITATIONS), "checks": {key: "satisfied" for key in ("source_match", "quantity_and_units", "state_association", "method_and_scope")},
        "evidence_refs": sorted(refs, key=lambda row: row["artifact_id"]), "source_inspection_attested": True,
        "resolves_decision_id": None, "extraction_decision_id": None}


async def request_for(db, seeded, items, *, request_key=None):
    document = {"version": REQUEST_VERSION, "request_key": request_key or "synthetic-review:" + uuid4().hex, "items": items}
    body = canonical(document).decode()
    return await add(db, "scientific_adjudication_requests", id=uuid4(), actor_user_id=seeded["reviewer"],
        actor_grant_id=seeded["grant"]["id"], request_key=document["request_key"], request_json=body,
        request_sha256=hashlib.sha256(body.encode()).hexdigest(), item_count=len(items))


async def decision_for(db, request, subject, item, index=0):
    return await add(db, "scientific_result_decisions", id=UUID(item["decision_id"]), request_id=request["id"], item_index=index,
        subject_id=subject["id"], property_id=subject["property_id"], event_id=subject["event_id"], scope=item["scope"],
        profile_version=item["profile_version"], decision=item["decision"], reason_code=item["reason_code"],
        predecessor_id=UUID(item["expected_previous_decision_id"]) if item["expected_previous_decision_id"] else None,
        resolves_decision_id=UUID(item["resolves_decision_id"]) if item["resolves_decision_id"] else None,
        extraction_decision_id=UUID(item["extraction_decision_id"]) if item["extraction_decision_id"] else None,
        actor_user_id=request["actor_user_id"], actor_grant_id=request["actor_grant_id"],
        item_sha256=hashlib.sha256(canonical(item)).hexdigest())


async def accepted(db, seeded=None):
    seeded = seeded or await fixture(db)
    subject = dict(await add(db, "scientific_result_subjects", **await capture(db, seeded["property_id"])))
    item = await item_for(db, subject)
    request = await request_for(db, seeded, [item])
    decision = await decision_for(db, request, subject, item)
    await db.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    return seeded, subject, request, decision


def test_three_additive_tables_and_restrict_fks_do_not_modify_frozen_spec():
    from services.research_release_spec import SPEC
    assert not set(TABLE_ORDER) & set(SPEC)
    assert all(fk.ondelete == "RESTRICT" and fk.onupdate == "RESTRICT"
               for name in TABLE_ORDER for fk in Base.metadata.tables[name].foreign_keys)


async def test_actual_native_subject_request_and_fidelity_decision(db_session):
    seeded, subject, request, decision = await accepted(db_session)
    body = json.loads(subject["basis_json"])
    assert body["target"]["property_id"] == str(seeded["property_id"])
    assert body["native_import"] is not None
    assert decision["scope"] == "extraction_fidelity" and decision["decision"] == "accept"
    assert request["record_sha256"] and decision["record_sha256"]
    assert body["target"]["state_id"] == seeded["finished"]["row_ids"]["state"]


async def test_native_sql_impact_matches_existing_bounded_reader(db_session):
    from services.scientific_result_impact import inspect_result_impact
    seeded = await fixture(db_session)
    sql = await db_session.scalar(sa.text("SELECT sclib_scientific_result_impact_capture_v1(:id)"), {"id": seeded["property_id"]})
    expected = await inspect_result_impact(db_session, property_id=seeded["property_id"], event_id=UUID(seeded["finished"]["row_ids"]["event"]))
    assert json.loads(sql) == expected and sql.encode() == canonical(expected)


@pytest.mark.parametrize("table", TABLE_ORDER)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_all_history_rows_refuse_even_noop_mutation(db_session, table, operation):
    _, subject, request, decision = await accepted(db_session)
    record = {TABLE_ORDER[0]: subject, TABLE_ORDER[1]: request, TABLE_ORDER[2]: decision}[table]
    query = (f"UPDATE {table} SET record_sha256=record_sha256 WHERE id=:id" if operation == "UPDATE" else
             f"DELETE FROM {table} WHERE id=:id" if operation == "DELETE" else f"TRUNCATE {table} CASCADE")
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(query), {"id": record["id"]})
    assert await state(db_session) == before


@pytest.mark.parametrize("change", ["extra", "null_check", "numeric_hash", "null_attestation", "unknown_profile",
    "wrong_proposition", "missing_limit", "unsorted_limit", "empty_accept_refs", "duplicate_ref", "null_ref_hash",
    "unresolved_accept", "short_rationale", "control_rationale", "wrong_reason", "extra_ref", "duplicate_item",
    "too_many_items", "missing_cas", "wrong_scope"])
async def test_raw_request_rejects_closed_shape_and_profile_bypasses(db_session, change):
    seeded = await fixture(db_session)
    subject = await add(db_session, TABLE_ORDER[0], **await capture(db_session, seeded["property_id"]))
    item = await item_for(db_session, subject)
    items = [item]
    if change == "extra": item["approval"] = True
    elif change == "null_check": item["checks"]["source_match"] = None
    elif change == "numeric_hash": item["expected_subject_sha256"] = int("1" * 64)
    elif change == "null_attestation": item["source_inspection_attested"] = None
    elif change == "unknown_profile": item["profile_version"] = "arbitrary-approval/1"
    elif change == "wrong_proposition": item["proposition"] = "full_zone_stability"
    elif change == "missing_limit": item["limitations"].pop()
    elif change == "unsorted_limit": item["limitations"].reverse()
    elif change == "empty_accept_refs": item["evidence_refs"] = []
    elif change == "duplicate_ref": item["evidence_refs"].append(item["evidence_refs"][0])
    elif change == "null_ref_hash": item["evidence_refs"][0]["bytes_sha256"] = None
    elif change == "unresolved_accept": item["checks"]["method_and_scope"] = "unresolved"
    elif change == "short_rationale": item["rationale"] = "insufficient"
    elif change == "control_rationale": item["rationale"] += "\x01"
    elif change == "wrong_reason": item["reason_code"] = "scientific_concern"
    elif change == "extra_ref": item["evidence_refs"][0]["content"] = "private"
    elif change == "duplicate_item": items.append(deepcopy(item))
    elif change == "too_many_items": items = [deepcopy(item) for _ in range(21)]
    elif change == "missing_cas": del item["expected_previous_decision_id"]
    elif change == "wrong_scope": item["scope"] = "whole_material"
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="scientific_adjudication_"):
        async with db_session.begin_nested():
            await request_for(db_session, seeded, items)
    assert await state(db_session) == before


@pytest.mark.parametrize("change", ["omitted_row", "source_hash", "property_id", "property_hash", "event_revision", "material"])
async def test_subject_is_independently_recaptured_not_client_asserted(db_session, change):
    seeded = await fixture(db_session)
    subject = await capture(db_session, seeded["property_id"])
    if change in {"omitted_row", "source_hash"}:
        body = json.loads(subject["basis_json"])
        if change == "omitted_row": body["rows"].pop()
        else: body["artifacts"][0]["bytes_sha256"] = "f" * 64
        subject["basis_json"] = canonical(body).decode()
        subject["subject_sha256"] = hashlib.sha256(subject["basis_json"].encode()).hexdigest()
    elif change == "property_id": subject["property_id"] = uuid4()
    elif change == "property_hash": subject["property_row_sha256"] = "0" * 64
    elif change == "event_revision": subject["event_revision"] += 1
    elif change == "material": subject["material_id"] = "not-this-material"
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="scientific_(subject|adjudication)_"):
        async with db_session.begin_nested():
            await add(db_session, TABLE_ORDER[0], **subject)
    assert await state(db_session) == before


@pytest.mark.parametrize("change", ["impact", "source_ref", "subset_refs", "no_fidelity", "wrong_actor", "wrong_item_id"])
async def test_decision_trigger_refuses_unproven_acceptance(db_session, change):
    seeded = await fixture(db_session)
    subject = await add(db_session, TABLE_ORDER[0], **await capture(db_session, seeded["property_id"]))
    profile = "sampled-phonon-minimum-review/1.0.0" if change == "no_fidelity" else "native-sampled-frequency-extraction/1.0.0"
    item = await item_for(db_session, subject, profile=profile)
    if change == "impact": item["expected_impact_sha256"] = "0" * 64
    elif change == "source_ref": item["evidence_refs"][0]["bytes_sha256"] = "0" * 64
    elif change == "subset_refs": item["evidence_refs"].pop()
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="scientific_adjudication_"):
        async with db_session.begin_nested():
            request = await request_for(db_session, seeded, [item])
            if change == "wrong_actor": request = {**request, "actor_user_id": seeded["actors"]["curator"]}
            elif change == "wrong_item_id": item = {**item, "decision_id": str(uuid4())}
            await decision_for(db_session, request, subject, item)
    assert await state(db_session) == before


async def test_request_without_exact_decision_inventory_cannot_complete(db_session):
    seeded = await fixture(db_session)
    subject = await add(db_session, TABLE_ORDER[0], **await capture(db_session, seeded["property_id"]))
    item = await item_for(db_session, subject)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="complete_atomic_request"):
        async with db_session.begin_nested():
            await request_for(db_session, seeded, [item])
            await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    assert await state(db_session) == before


async def test_two_scopes_one_atomic_request_and_exact_dependency(db_session):
    seeded = await fixture(db_session)
    subject = await add(db_session, TABLE_ORDER[0], **await capture(db_session, seeded["property_id"]))
    first = await item_for(db_session, subject)
    second = await item_for(db_session, subject, profile="sampled-phonon-minimum-review/1.0.0")
    second["extraction_decision_id"] = first["decision_id"]
    request = await request_for(db_session, seeded, [first, second])
    await decision_for(db_session, request, subject, first)
    result = await decision_for(db_session, request, subject, second, 1)
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    assert result["extraction_decision_id"] == UUID(first["decision_id"])
    assert await db_session.scalar(sa.text("SELECT review_status FROM research_events WHERE id=:id"), {"id": subject["event_id"]}) == "pending"


async def test_native_changed_raw_remains_visible_but_new_acceptance_is_refused(db_session):
    seeded = await fixture(db_session)
    old = await capture(db_session, seeded["property_id"])
    await db_session.execute(sa.text("UPDATE event_properties SET raw=raw || jsonb_build_object('new_interpretation',true) WHERE id=:id"), {"id": seeded["property_id"]})
    changed = await capture(db_session, seeded["property_id"])
    assert changed["subject_sha256"] != old["subject_sha256"]
    subject = await add(db_session, TABLE_ORDER[0], **changed)
    item = await item_for(db_session, subject)
    with pytest.raises(DBAPIError, match="native_snapshot_changed"):
        async with db_session.begin_nested():
            request = await request_for(db_session, seeded, [item])
            await decision_for(db_session, request, subject, item)
    negative = await item_for(db_session, subject, decision="request_clarification")
    negative["evidence_refs"] = []
    negative["source_inspection_attested"] = False
    negative["checks"] = {key: "unresolved" for key in negative["checks"]}
    request = await request_for(db_session, seeded, [negative])
    await decision_for(db_session, request, subject, negative)
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))


async def test_same_head_fork_is_rejected_and_exact_successor_allowed(db_session):
    seeded, subject, _, first = await accepted(db_session)
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete DEFERRED"))
    stale = await item_for(db_session, subject)
    with pytest.raises(DBAPIError, match="current_head"):
        async with db_session.begin_nested():
            request = await request_for(db_session, seeded, [stale])
            await decision_for(db_session, request, subject, stale)
    next_item = await item_for(db_session, subject, decision="reject", predecessor=first["id"])
    request = await request_for(db_session, seeded, [next_item])
    second = await decision_for(db_session, request, subject, next_item)
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    assert second["predecessor_id"] == first["id"]


async def test_governance_rehash_does_not_change_scientific_event_subject(db_session):
    seeded = await fixture(db_session)
    before = await capture(db_session, seeded["property_id"])
    await db_session.execute(sa.text("UPDATE research_events SET review_status='rejected',validity_status='disputed',record_sha256=:hash WHERE id=:id"),
        {"id": UUID(seeded["finished"]["row_ids"]["event"]), "hash": "f" * 64})
    after = await capture(db_session, seeded["property_id"])
    assert after["basis_json"] == before["basis_json"]
    subject = await add(db_session, TABLE_ORDER[0], **after)
    item = await item_for(db_session, subject)
    with pytest.raises(DBAPIError, match="source_held"):
        async with db_session.begin_nested():
            request = await request_for(db_session, seeded, [item])
            await decision_for(db_session, request, subject, item)


async def test_recorded_profile_cannot_accept_rejected_source_governance(db_session):
    seeded = await fixture(db_session)
    await db_session.execute(sa.text("UPDATE research_events SET review_status='rejected' WHERE id=:id"),
        {"id": UUID(seeded["finished"]["row_ids"]["event"])})
    subject = await add(db_session, TABLE_ORDER[0], **await capture(db_session, seeded["property_id"]))
    item = await item_for(db_session, subject, profile="recorded-sampled-frequency-fidelity/1.0.0")
    with pytest.raises(DBAPIError, match="source_held"):
        async with db_session.begin_nested():
            request = await request_for(db_session, seeded, [item])
            await decision_for(db_session, request, subject, item)


@pytest.mark.parametrize("mutation", ["source", "impact", "governance"])
async def test_immediate_validation_cannot_be_consumed_before_same_transaction_mutation(db_session, mutation):
    from tests.test_research_freeze import seed
    other = await seed(db_session)
    seeded, subject, _, _ = await accepted(db_session)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="scientific_adjudication_(assembly_changed|source_held)"):
        async with db_session.begin_nested():
            if mutation == "source":
                await db_session.execute(sa.text("UPDATE event_properties SET value=value+1 WHERE id=:id"), {"id": seeded["property_id"]})
            elif mutation == "governance":
                await db_session.execute(sa.text("UPDATE research_events SET review_status='rejected' WHERE id=:id"), {"id": subject["event_id"]})
            else:
                await add(db_session, "ml_example_inputs", example_id=other["example"], input_kind="property",
                    input_event_id=subject["event_id"], input_property_id=seeded["property_id"], feature_key="post-review",
                    matching_policy_version="synthetic/1", record_sha256="b" * 64)
    assert await state(db_session) == before


async def test_later_transaction_may_change_source_and_review_becomes_stale(db_session):
    from services.scientific_result_effects import resolve_result_status
    seeded, subject, _, _ = await accepted(db_session)
    await db_session.commit()
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db_session.execute(sa.text("SET LOCAL statement_timeout='10s'"))
    await db_session.execute(sa.text("UPDATE event_properties SET value=value+1 WHERE id=:id"), {"id": seeded["property_id"]})
    after = await capture(db_session, seeded["property_id"])
    assert after["subject_sha256"] != subject["subject_sha256"]
    status = await resolve_result_status(db_session, seeded["property_id"])
    assert status["scopes"][0]["effective_status"] == "stale"


async def test_forward_claim_hold_is_not_ignored_by_recorded_accept(db_session):
    from tests.test_research_freeze import seed
    other = await seed(db_session)
    seeded = await fixture(db_session)
    await db_session.execute(sa.text("UPDATE material_claims SET validity_status='disputed' WHERE id=:id"), {"id": other["claim"]})
    await add(db_session, "event_evidence", event_id=UUID(seeded["finished"]["row_ids"]["event"]),
        link_type="supports", input_event_id=other["event"], input_claim_id=other["claim"])
    subject = await add(db_session, TABLE_ORDER[0], **await capture(db_session, seeded["property_id"]))
    item = await item_for(db_session, subject, profile="recorded-sampled-frequency-fidelity/1.0.0")
    with pytest.raises(DBAPIError, match="source_held"):
        async with db_session.begin_nested():
            request = await request_for(db_session, seeded, [item])
            await decision_for(db_session, request, subject, item)


async def test_new_request_callback_rechecks_consumed_scientific_fidelity_dependency(db_session):
    seeded, subject, _, fidelity = await accepted(db_session)
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete DEFERRED"))
    science = await item_for(db_session, subject, profile="sampled-phonon-minimum-review/1.0.0")
    science["extraction_decision_id"] = str(fidelity["id"])
    request = await request_for(db_session, seeded, [science])
    await decision_for(db_session, request, subject, science)
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="current_fidelity_required"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete DEFERRED"))
            successor = await item_for(db_session, subject, decision="reject", predecessor=fidelity["id"])
            next_request = await request_for(db_session, seeded, [successor])
            await decision_for(db_session, next_request, subject, successor)
            await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    assert await state(db_session) == before


@pytest.mark.parametrize("complete", [False, True])
async def test_twenty_distinct_items_are_complete_or_entire_request_refuses(db_session, complete):
    seeded = await fixture(db_session)
    subjects = []
    for index in range(20):
        row = await add(db_session, "event_properties", event_id=UUID(seeded["finished"]["row_ids"]["event"]),
            property_key="phonon_min_frequency", component_key=f"synthetic-point-{index}", relation="exact",
            value=float(index), unit="THz", record_sha256="1" * 64)
        subjects.append(await add(db_session, TABLE_ORDER[0], **await capture(db_session, row["id"])))
    items = []
    for subject in subjects:
        item = await item_for(db_session, subject, profile="recorded-sampled-frequency-fidelity/1.0.0")
        support = json.loads(subject["basis_json"])["support_artifact_ids"]
        item["evidence_refs"] = [ref for ref in item["evidence_refs"] if ref["artifact_id"] in support][:1]
        items.append(item)
    if complete:
        request = await request_for(db_session, seeded, items)
        for index, (subject, item) in enumerate(zip(subjects, items)):
            await decision_for(db_session, request, subject, item, index)
        await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
        assert await db_session.scalar(sa.text("SELECT count(*) FROM scientific_result_decisions WHERE request_id=:id"), {"id": request["id"]}) == 20
    else:
        before = await state(db_session)
        with pytest.raises(DBAPIError, match="complete_atomic_request_required"):
            async with db_session.begin_nested():
                request = await request_for(db_session, seeded, items)
                for index, (subject, item) in enumerate(zip(subjects[:-1], items[:-1])):
                    await decision_for(db_session, request, subject, item, index)
                await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
        assert await state(db_session) == before


@pytest.mark.parametrize("setting", ["read_committed", "timeout_unlimited", "timeout_excessive"])
async def test_native_lock_requires_bounded_serializable_snapshot(db_session, setting):
    if setting == "read_committed": await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
    else: await db_session.execute(sa.text("SET LOCAL statement_timeout=" + ("0" if setting == "timeout_unlimited" else "10001")))
    with pytest.raises(DBAPIError, match="scientific_adjudication_bounded_snapshot_required"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SELECT sclib_scientific_adjudication_lock_v1()"))


@pytest.mark.parametrize("column,changed", [("total_papers", False), ("formula_normalized", True)])
async def test_read_committed_catalogue_writer_fences_older_review_snapshot(db_session, column, changed):
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.db import get_engine
    seeded = await fixture(db_session)
    before = await capture(db_session, seeded["property_id"])
    await db_session.commit()
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db_session.execute(sa.text("SET LOCAL statement_timeout='10s'"))
    assert (await capture(db_session, seeded["property_id"]))["subject_sha256"] == before["subject_sha256"]
    # Separate, genuine native connection with READ COMMITTED, not mocked state.
    async with AsyncSession(get_engine().execution_options(isolation_level="READ COMMITTED")) as writer:
        expression = "total_papers+1" if column == "total_papers" else "formula_normalized||'synthetic-change'"
        await writer.execute(sa.text(f"UPDATE materials SET {column}={expression} WHERE id=:id"), {"id": seeded["material"]})
        await writer.commit()
    with pytest.raises(DBAPIError, match="serializ"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SELECT sclib_scientific_adjudication_lock_v1()"))
    await db_session.rollback()
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db_session.execute(sa.text("SET LOCAL statement_timeout='10s'"))
    after = await capture(db_session, seeded["property_id"])
    assert (after["subject_sha256"] != before["subject_sha256"]) is changed
