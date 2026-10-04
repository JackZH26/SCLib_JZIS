"""Owned native service transactions and private proposal history.

Synthetic source records establish transport/transaction behavior only.
"""
from copy import deepcopy
import json
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from services import discovery_condition_batches as service
from services import discovery_condition_batch_contract as contract
from services import discovery_designs as designs
from services.research_release_manifest import canonical, digest
from services.source_property_pending import SourcePropertyConflict, SourcePropertyNotFound
from tests.research_access_helpers import research_operator
from tests.test_discovery_condition_batch_sql import AXES, actor_pins, native_parent
from tests.test_discovery_design_contract import operation
from tests.test_discovery_designs import save
from tests.test_research_freeze import db_session, state


def retain_request(parent, manifest, axes=AXES):
    return {"version": contract.REQUEST_VERSION, "request_key": "batch-service:"+uuid4().hex,
            "operation": "retain_batch", "payload": {
                "parent": {"design_id": str(parent["design_id"]), "revision_id": str(parent["id"]),
                           "revision": parent["revision"], "record_sha256": parent["record_sha256"]},
                "axes": deepcopy(axes), "expected_input_sha256": manifest["input_sha256"],
                "expected_manifest_sha256": manifest["manifest_sha256"]}}


def child_request(batch, candidate):
    return {"version": contract.REQUEST_VERSION, "request_key": "batch-child-service:"+uuid4().hex,
            "operation": "propose_candidate_child", "payload": {
                "batch": {"id": batch["batch_id"], "record_sha256": batch["batch_record_sha256"],
                          "manifest_sha256": batch["manifest_sha256"]},
                "candidate_sha256": candidate["candidate_sha256"]}}


async def retain(db, actor, parent, axes=AXES):
    manifest = contract.build_manifest(parent, parent["projection"], actor_pins(actor), axes)
    req = retain_request(parent, manifest, axes)
    before = await state(db)
    preview = await service.operate(db, actor_user_id=actor["id"], request=req)
    assert preview["dry_run"] and not preview["pending_ledger_written"]
    assert await state(db) == before
    saved = await service.operate(db, actor_user_id=actor["id"], request=req, dry_run=False,
                                  expected_preview_sha256=preview["preview_sha256"])
    assert saved["receipt_sha256"] == preview["receipt_sha256"]
    return req, manifest, saved


@pytest.mark.asyncio
async def test_real_batch_preview_commit_replay_outcome_and_original_manifest(db_session):
    actor, parent, _ = await native_parent(db_session)
    req, manifest, saved = await retain(db_session, actor, parent)
    before = await state(db_session)
    replay = await service.operate(db_session, actor_user_id=actor["id"], request=req, dry_run=False)
    outcome = await service.outcome(db_session, actor_user_id=actor["id"],
        request_key_value=req["request_key"], expected_request_sha256=saved["request_sha256"])
    assert replay["replayed"] and outcome["replayed"] and not outcome["dry_run"]
    assert replay["receipt_sha256"] == saved["receipt_sha256"] == outcome["receipt_sha256"]
    assert await state(db_session) == before
    exported = await service.export_manifest(db_session, actor_user_id=actor["id"], batch_id=saved["batch_id"])
    assert exported == canonical(manifest).decode()
    assert json.loads(exported)["batch_saved"] is False
    page = await service.batches(db_session, actor_user_id=actor["id"])
    detail = await service.batch_detail(db_session, actor_user_id=actor["id"], batch_id=saved["batch_id"], offset=8)
    assert page["total"] == 1 and page["entries"][0]["eligibility"] == {"eligible": True, "reason_codes": []}
    assert page["entries"][0]["scenario_total"] == 12 and len(detail["scenarios"]) == 4
    assert all(s["child"] is None for s in detail["scenarios"])
    for value in (saved, page, detail):
        assert value["canonical_promotions"] == 0
        assert all(value[k] is False for k in ("scientific_acceptance", "ml_training_approved", "public_release", "calculation_executed"))
        text = canonical(value).decode()
        assert "literature_locator" not in text and '"values"' not in text
        assert "projection" not in value


@pytest.mark.asyncio
async def test_candidate_child_is_atomic_and_exact_parent_never_changes(db_session):
    actor, parent, _ = await native_parent(db_session)
    _, manifest, batch = await retain(db_session, actor, parent)
    candidate = manifest["scenarios"][0]
    req = child_request(batch, candidate)
    before = await state(db_session)
    preview = await service.operate(db_session, actor_user_id=actor["id"], request=req)
    assert await state(db_session) == before
    assert preview["child"]["dry_run"] and not preview["child"]["pending_ledger_written"]
    with pytest.raises(SourcePropertyConflict, match="exact_preview"):
        await service.operate(db_session, actor_user_id=actor["id"], request=req, dry_run=False, expected_preview_sha256="a"*64)
    assert await state(db_session) == before
    saved = await service.operate(db_session, actor_user_id=actor["id"], request=req, dry_run=False,
                                  expected_preview_sha256=preview["preview_sha256"])
    assert saved["receipt_sha256"] == preview["receipt_sha256"]
    assert not saved["child"]["dry_run"] and saved["child"]["pending_ledger_written"]
    child = (await db_session.execute(sa.select(designs.table()).where(
        designs.table().c.id == UUID(saved["child"]["receipt_id"])))).mappings().one()
    assert child["design"] == candidate["proposal"] and child["baseline"] == parent["baseline"]
    assert child["parent"] == {k: manifest["parent"][k] for k in ("design_id", "revision_id", "record_sha256")}
    original = (await db_session.execute(sa.select(designs.table()).where(designs.table().c.id == parent["id"]))).mappings().one()
    assert dict(original) == dict(parent)
    detail = await service.batch_detail(db_session, actor_user_id=actor["id"], batch_id=batch["batch_id"])
    assert detail["scenarios"][0]["child"] == {"design_id": saved["child"]["design_id"],
        "revision_id": saved["child"]["receipt_id"], "record_sha256": saved["child"]["receipt_sha256"]}
    committed = await state(db_session)
    # A second request for the same exact batch candidate must leave neither a
    # second initial link nor an orphan native child.
    with pytest.raises((DBAPIError, SourcePropertyConflict)):
        await service.operate(db_session, actor_user_id=actor["id"], request=child_request(batch, candidate))
    assert await state(db_session) == committed
    replay = await service.outcome(db_session, actor_user_id=actor["id"],
        request_key_value=req["request_key"], expected_request_sha256=saved["request_sha256"])
    assert replay["child"]["replayed"] and replay["receipt_sha256"] == saved["receipt_sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", ["source_context_changed", "parent_revision_changed", "parent_withdrawn"])
async def test_historical_batch_is_preserved_but_changed_parent_cannot_generate_children(db_session, hold):
    actor, parent, fixture = await native_parent(db_session)
    _, manifest, batch = await retain(db_session, actor, parent)
    original = await service.export_manifest(db_session, actor_user_id=actor["id"], batch_id=batch["batch_id"])
    if hold == "source_context_changed":
        states = Base.metadata.tables["material_states"]
        await db_session.execute(states.update().where(states.c.id == fixture["state"]).values(context_sha256="a"*64))
    else:
        req = operation("withdraw" if hold == "parent_withdrawn" else "revise", baseline=parent["baseline"], parent=parent["parent"])
        if hold == "parent_withdrawn":
            req["payload"] = {"reason": "Synthetic parent withdrawn for audit"}
        req["payload"].update(design_id=str(parent["design_id"]), predecessor={"id": str(parent["id"]), "record_sha256": parent["record_sha256"]})
        await save(db_session, actor, req)
    detail = await service.batch_detail(db_session, actor_user_id=actor["id"], batch_id=batch["batch_id"])
    assert not detail["entry"]["eligibility"]["eligible"] and hold in detail["entry"]["eligibility"]["reason_codes"]
    assert await service.export_manifest(db_session, actor_user_id=actor["id"], batch_id=batch["batch_id"]) == original
    before = await state(db_session)
    with pytest.raises(SourcePropertyConflict, match="not_currently_eligible"):
        await service.operate(db_session, actor_user_id=actor["id"], request=child_request(batch, manifest["scenarios"][0]))
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_renewed_session_authorizes_new_child_without_rewriting_old_generation(db_session):
    actor, parent, _ = await native_parent(db_session)
    _, manifest, batch = await retain(db_session, actor, parent)
    original = await service.export_manifest(db_session, actor_user_id=actor["id"], batch_id=batch["batch_id"])
    users = Base.metadata.tables["users"]
    await db_session.execute(users.update().where(users.c.id == actor["id"]).values(session_version=1))
    req = child_request(batch, manifest["scenarios"][0])
    preview = await service.operate(db_session, actor_user_id=actor["id"], request=req)
    saved = await service.operate(db_session, actor_user_id=actor["id"], request=req, dry_run=False,
                                  expected_preview_sha256=preview["preview_sha256"])
    assert saved["actor_session_version"] == saved["child"]["actor_session_version"] == 1
    assert await service.export_manifest(db_session, actor_user_id=actor["id"], batch_id=batch["batch_id"]) == original
    detail = await service.batch_detail(db_session, actor_user_id=actor["id"], batch_id=batch["batch_id"])
    assert detail["session_version"] == 1 and detail["entry"]["receipt"]["actor_session_version"] == 0


@pytest.mark.asyncio
async def test_owner_pin_request_key_and_missing_outcome_boundaries(db_session):
    other = await research_operator()
    actor, parent, _ = await native_parent(db_session)
    req, manifest, batch = await retain(db_session, actor, parent)
    assert (await service.batches(db_session, actor_user_id=other["id"]))["total"] == 0
    with pytest.raises(SourcePropertyNotFound):
        await service.export_manifest(db_session, actor_user_id=other["id"], batch_id=batch["batch_id"])
    conflicting = child_request(batch, manifest["scenarios"][0]); conflicting["request_key"] = req["request_key"]
    before = await state(db_session)
    with pytest.raises(SourcePropertyConflict, match="request_conflict"):
        await service.operate(db_session, actor_user_id=actor["id"], request=conflicting)
    unknown = child_request(batch, manifest["scenarios"][0]); unknown["payload"]["candidate_sha256"] = "f"*64
    with pytest.raises(SourcePropertyNotFound):
        await service.operate(db_session, actor_user_id=actor["id"], request=unknown)
    with pytest.raises(SourcePropertyNotFound, match="not_proof_of_failure"):
        await service.outcome(db_session, actor_user_id=actor["id"], request_key_value="unconfirmed-original-request", expected_request_sha256="a"*64)
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_axes_are_detached_before_async_and_exact_raw_input_pins_are_required(db_session, monkeypatch):
    actor, parent, _ = await native_parent(db_session)
    manifest = contract.build_manifest(parent, parent["projection"], actor_pins(actor), AXES)
    req = retain_request(parent, manifest)
    original_req = deepcopy(req)
    original_grant = designs._grant
    async def mutate(db, actor_user_id, role):
        req["payload"]["axes"]["temperatures_k"][1] = "999"
        return await original_grant(db, actor_user_id, role)
    with monkeypatch.context() as patch:
        patch.setattr(designs, "_grant", mutate)
        preview = await service.operate(db_session, actor_user_id=actor["id"], request=req)
    assert json.loads(preview["request_canonical_json"]) == original_req
    wrong = deepcopy(original_req); wrong["payload"]["axes"]["pressures"][3]["raw_gpa"] = "1e1"
    before = await state(db_session)
    with pytest.raises(SourcePropertyConflict, match="generation_pin_changed"):
        await service.operate(db_session, actor_user_id=actor["id"], request=wrong)
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["3e-324", "5e-324", "2.5e-324", "1e-323", "1.7976931348623158e308",
                               "0e999999999999999999", "0e-1999999999999999997"])
async def test_current_native_target_spelling_is_measured_without_float_deduplication(db_session, raw):
    assert contract.decimal_identity(raw)
    actual = await db_session.scalar(sa.text("SELECT public.sclib_discovery_design_decimal_v1(CAST(:value AS jsonb),false)"),
                                     {"value": canonical(raw).decode()})
    assert actual is True
    print("Native 0087 target spelling admission:", raw, actual)
