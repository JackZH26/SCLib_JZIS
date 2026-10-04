"""Owned PostgreSQL archival return flow; local subjects are reconstructed tests.

Contrasting retained values exercise the actual API field semantics. These tests
do not attest production subject pins, source-paper fidelity or human review.
"""
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from models.db import Base
from services import discovery_designs as designs
from services import discovery_feedback as service
from services import discovery_feedback_contract as contract
from services.research_release_manifest import canonical, digest
from services.source_property_pending import SourcePropertyConflict, SourcePropertyNotFound
from tests.research_access_helpers import research_operator
from tests.test_discovery_design_contract import operation as design_operation
from tests.test_discovery_designs import save
from tests.test_material_field_cases import retained
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state

PT_ONSET = {"tc_kelvin": 23.0, "tc_type": "onset", "measurement": "resistivity", "evidence_type": "primary_experimental",
            "hc2_tesla": 65.0, "hc2_conditions": "0 K"}
PT_ZERO = {"tc_kelvin": 21.5, "tc_type": "zero_resistance", "measurement": "resistivity", "evidence_type": "primary_experimental",
           "hc2_tesla": 65.0, "hc2_conditions": "0 K"}
CAFFE = {"tc_kelvin": 23.0, "tc_type": "onset", "measurement": "resistivity", "evidence_type": "primary_experimental",
         "hc2_tesla": 102.0, "hc2_conditions": "0 K, estimated by WHH formula"}


async def feedback_case(db, actor=None):
    actor = actor or await research_operator()
    material, paper = await retained(db, record={**PT_ONSET, "private_source_text": "DO NOT RETURN SOURCE"})
    materials = Base.metadata.tables["materials"]
    await db.execute(materials.update().where(materials.c.id == material).values(
        formula="BaFe1.906Pt0.094As2", formula_normalized="BaFe1.906Pt0.094As2",
        records=[{**PT_ONSET, "paper_id": paper, "private_source_text": "DO NOT RETURN SOURCE"},
                 {**PT_ZERO, "paper_id": paper, "private_source_text": "DO NOT RETURN SOURCE"}]))
    baseline = await designs.context(db, actor_user_id=actor["id"], kind="retained_result", material_id=material, record_index=0)
    request = design_operation(baseline=baseline["baseline"])
    request["payload"]["design"]["next_action"]["question"] = "Which transition criterion and Hc2 conditions does the archive retain?"
    parent = await save(db, actor, request)
    ctx = await service.context(db, actor_user_id=actor["id"], design_id=parent["design_id"],
        revision_id=parent["receipt_id"], record_sha256=parent["receipt_sha256"], material_id=material, record_index=1)
    return actor, material, paper, parent, ctx


def return_request(ctx):
    return {"version": contract.REQUEST_VERSION, "request_key": "feedback-service:" + uuid4().hex,
        "operation": "return_evidence", "payload": {"design": ctx["design"], "evidence": ctx["evidence"],
            "findings": "The inspected archival record retains zero resistance and a separate onset value.",
            "decision": "redirect", "reason": "Compare like transition criteria before selecting the next question.",
            "unknowns": ["Physical sample association is unestablished", "Hc2 method is not supplied by the 0 K token"]}}


async def return_saved(db, actor, request):
    before = await state(db)
    preview = await service.operate(db, actor_user_id=actor["id"], request=request)
    assert preview["dry_run"] and not preview["pending_ledger_written"]
    assert await state(db) == before
    saved = await service.operate(db, actor_user_id=actor["id"], request=request, dry_run=False,
                                  expected_preview_sha256=preview["preview_sha256"])
    assert saved["receipt_sha256"] == preview["receipt_sha256"]
    return saved


@pytest.mark.asyncio
async def test_archival_return_exact_preview_recovery_history_and_rich_fields(db_session):
    actor, material, paper, parent, ctx = await feedback_case(db_session)
    raw = ctx["projection"]["record"]
    assert raw["tc_kelvin"] == 21.5 and raw["tc_type"] == "zero_resistance"
    assert raw["measurement"] == "resistivity" and raw["measurement_method"] is None
    assert raw["evidence_type"] == "primary_experimental" and raw["knowledge_origin"] is None
    assert raw["hc2_tesla"] == 65 and raw["hc2_conditions"] == "0 K"
    assert raw["pressure_gpa"] is None and ctx["projection"]["physical_association"] == "unestablished"
    request = return_request(ctx)
    before = await state(db_session)
    with pytest.raises(SourcePropertyConflict, match="exact_preview"):
        await service.operate(db_session, actor_user_id=actor["id"], request=request, dry_run=False)
    assert await state(db_session) == before
    saved = await return_saved(db_session, actor, request)
    committed = await state(db_session)
    replay = await service.operate(db_session, actor_user_id=actor["id"], request=request, dry_run=False)
    out = await service.outcome(db_session, actor_user_id=actor["id"], request_key_value=request["request_key"],
                                expected_request_sha256=saved["request_sha256"])
    assert replay["replayed"] and out["receipt_sha256"] == saved["receipt_sha256"]
    assert await state(db_session) == committed
    page = await service.returns(db_session, actor_user_id=actor["id"], design_id=parent["design_id"])
    assert page["total"] == 1 and page["entries"][0]["projection"] == ctx["projection"]
    entry = page["entries"][0]
    assert entry["decision"] == "redirect" and entry["unknowns"] == request["payload"]["unknowns"]
    assert entry["follow_ups"] == [] and entry["eligibility"]["eligible"]
    for value in (saved, page):
        assert value["canonical_promotions"] == 0 and value["scientific_acceptance"] is False
        assert value["calculation_executed"] is value["experiment_executed"] is value["physical_association_established"] is False
        assert "DO NOT RETURN SOURCE" not in canonical(value).decode()
    proof = json.loads(saved["receipt_canonical_json"])
    assert "context_json" not in proof and "projection" not in proof
    assert digest(proof) == saved["receipt_sha256"] and "21.5" not in saved["receipt_canonical_json"]
    changed = deepcopy(request)
    changed["payload"]["reason"] = "Changed request under the same key"
    with pytest.raises(SourcePropertyConflict, match="request_conflict"):
        await service.operate(db_session, actor_user_id=actor["id"], request=changed)


@pytest.mark.asyncio
async def test_cross_material_comparator_retains_explicit_whh_only_where_supplied(db_session):
    actor, _, _, parent, _ = await feedback_case(db_session)
    other_material, _ = await retained(db_session, record={**CAFFE, "knowledge_origin": "Computed"})
    ctx = await service.context(db_session, actor_user_id=actor["id"], design_id=parent["design_id"],
        revision_id=parent["receipt_id"], record_sha256=parent["receipt_sha256"], material_id=other_material, record_index=0)
    assert ctx["eligibility"]["eligible"] and ctx["projection"]["record"]["hc2_conditions"] == CAFFE["hc2_conditions"]
    assert ctx["projection"]["record"]["knowledge_origin"] == "Computed"
    assert ctx["projection"]["physical_association"] == "unestablished"
    saved = await return_saved(db_session, actor, return_request(ctx))
    assert saved["design"]["design_id"] == parent["design_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,path", [
    ("hc2_tesla", {"unsupported": 65}, "hc2_tesla"),
    ("hc2_tesla_unit", "T" * 41, "hc2_tesla_unit"),
    ("tc_criterion", "criterion\x01private", "tc_criterion"),
    ("hc2_conditions", "x" * 2001, "hc2_conditions"),
])
async def test_invalid_source_field_is_withheld_without_clipping_or_coercion(db_session, field, value, path):
    actor, _, _, parent, _ = await feedback_case(db_session)
    material, _ = await retained(db_session, record={**CAFFE, field: value})
    ctx = await service.context(db_session, actor_user_id=actor["id"], design_id=parent["design_id"],
        revision_id=parent["receipt_id"], record_sha256=parent["receipt_sha256"], material_id=material, record_index=0)
    # The independent catalogue parser can hold an entire malformed record.
    # Exercise the bounded reading separately without weakening that policy.
    captured = await designs.sql_context(db_session, {**ctx["evidence"], "expected_context_sha256": "0" * 64})
    projection = json.loads(await service._projection_text(db_session, captured))
    assert projection["record"][field] is None and path in projection["withheld_fields"]
    if field in {"hc2_tesla", "hc2_tesla_unit"}:
        assert not ctx["eligibility"]["eligible"] and ctx["projection"] is None
        assert ctx["projection_canonical_json"] is None


@pytest.mark.asyncio
async def test_unresolved_hc2_proposal_suppresses_stale_scalar_and_preserves_source_unit(db_session):
    actor, _, _, parent, _ = await feedback_case(db_session)
    material, _ = await retained(db_session, record={**CAFFE, "scientific_values": {"hc2_tesla": {
        "raw_value": "200 kOe", "input_unit": "unknown", "raw_unit": "kOe", "normalized_value": 20,
        "normalized_unit": "T", "status": "unresolved", "private_note": "DO NOT RETURN SOURCE"}}})
    ctx = await service.context(db_session, actor_user_id=actor["id"], design_id=parent["design_id"],
        revision_id=parent["receipt_id"], record_sha256=parent["receipt_sha256"], material_id=material, record_index=0)
    captured = await designs.sql_context(db_session, {**ctx["evidence"], "expected_context_sha256": "0" * 64})
    projection = json.loads(await service._projection_text(db_session, captured))
    proposal = projection["record"]["scientific_values"]["hc2_tesla"]
    assert proposal["raw_value"] == "200 kOe" and proposal["raw_unit"] == "kOe"
    assert set(proposal) == set(contract.SCIENTIFIC_VALUE_FIELDS) and "private_note" not in canonical(projection).decode()
    assert projection["record"]["hc2_tesla"] == 102  # distinct retained scalar, never substituted for source token
    assert not ctx["eligibility"]["eligible"] and ctx["projection"] is ctx["projection_canonical_json"] is None


@pytest.mark.asyncio
async def test_source_drift_retains_history_and_original_outcome_but_withholds_values(db_session):
    actor, material, paper, parent, ctx = await feedback_case(db_session)
    request = return_request(ctx)
    saved = await return_saved(db_session, actor, request)
    papers = Base.metadata.tables["papers"]
    await db_session.execute(papers.update().where(papers.c.id == paper).values(status="withdrawn"))
    page = await service.returns(db_session, actor_user_id=actor["id"], design_id=parent["design_id"])
    entry = page["entries"][0]
    assert not entry["eligibility"]["eligible"] and entry["projection"] is entry["projection_canonical_json"] is None
    assert "evidence_source_context_changed" in entry["eligibility"]["reason_codes"]
    assert entry["findings"] == request["payload"]["findings"]
    assert "21.5" not in entry["receipt"]["receipt_canonical_json"]
    out = await service.outcome(db_session, actor_user_id=actor["id"], request_key_value=request["request_key"],
                                expected_request_sha256=saved["request_sha256"])
    assert out["receipt_sha256"] == saved["receipt_sha256"]
    changed = deepcopy(request)
    changed["request_key"] += ":new"
    with pytest.raises(SourcePropertyConflict, match="not_currently_eligible"):
        await service.operate(db_session, actor_user_id=actor["id"], request=changed)


@pytest.mark.asyncio
async def test_exact_saved_initial_child_link_is_durable_and_not_a_material_genealogy(db_session):
    actor, _, _, parent, ctx = await feedback_case(db_session)
    returned = await return_saved(db_session, actor, return_request(ctx))
    parent_row = await designs._row(db_session, actor["id"], parent["receipt_id"])
    child_request = design_operation(baseline=parent_row["baseline"], parent={key: ctx["design"][key]
                                      for key in ("design_id", "revision_id", "record_sha256")})
    child = await save(db_session, actor, child_request)
    link_request = {"version": contract.REQUEST_VERSION, "request_key": "link-service:" + uuid4().hex,
        "operation": "link_follow_up", "payload": {
            "feedback": {"id": returned["feedback_id"], "record_sha256": returned["feedback_record_sha256"]},
            "child": {"design_id": child["design_id"], "revision_id": child["receipt_id"], "record_sha256": child["receipt_sha256"]}}}
    linked = await return_saved(db_session, actor, link_request)
    page = await service.returns(db_session, actor_user_id=actor["id"], design_id=parent["design_id"])
    follow_up = page["entries"][0]["follow_ups"][0]
    assert follow_up["child"] == link_request["payload"]["child"] and follow_up["eligibility"]["eligible"]
    assert linked["feedback_record_sha256"] == returned["receipt_sha256"]
    assert follow_up["physical_association_established"] is False
    other = await save(db_session, actor, design_operation(baseline=parent_row["baseline"]))
    wrong = deepcopy(link_request)
    wrong["request_key"] += ":wrong"
    wrong["payload"]["child"] = {"design_id": other["design_id"], "revision_id": other["receipt_id"], "record_sha256": other["receipt_sha256"]}
    before = await state(db_session)
    with pytest.raises(SourcePropertyConflict, match="initial_linked_child"):
        await service.operate(db_session, actor_user_id=actor["id"], request=wrong)
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_exact_action_hash_foreign_owner_and_unsupported_execution_action(db_session):
    other = await research_operator()  # Create roles before taking source/publication locks.
    actor, _, _, parent, ctx = await feedback_case(db_session)
    request = return_request(ctx)
    request["payload"]["design"]["next_action_sha256"] = "d" * 64
    with pytest.raises(SourcePropertyConflict, match="design_pin_conflict"):
        await service.operate(db_session, actor_user_id=actor["id"], request=request)
    with pytest.raises(SourcePropertyNotFound):
        await service.returns(db_session, actor_user_id=other["id"], design_id=parent["design_id"])
    original = await designs._row(db_session, actor["id"], parent["receipt_id"])
    next_req = design_operation("revise", baseline=original["baseline"], parent=original["parent"])
    next_req["payload"].update(design_id=parent["design_id"], predecessor={"id": parent["receipt_id"], "record_sha256": parent["receipt_sha256"]})
    next_req["payload"]["design"]["next_action"]["kind"] = "calculation"
    revised = await save(db_session, actor, next_req)
    new_ctx = await service.context(db_session, actor_user_id=actor["id"], design_id=parent["design_id"],
        revision_id=revised["receipt_id"], record_sha256=revised["receipt_sha256"], material_id=ctx["evidence"]["material_id"], record_index=1)
    assert "design_action_unsupported" in new_ctx["eligibility"]["reason_codes"]
    assert new_ctx["projection"] is None
    with pytest.raises(SourcePropertyConflict, match="not_currently_eligible"):
        await service.operate(db_session, actor_user_id=actor["id"], request=return_request(new_ctx))
