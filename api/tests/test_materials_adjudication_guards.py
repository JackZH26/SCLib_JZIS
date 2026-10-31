"""Adversarial claim review, source binding and consumer gates (synthetic)."""
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from services import materials_adjudication as service
from services import materials_adjudication_contract as contract
from services import scientific_adjudication_contract as legacy
from services.materials_review_effects import resolve_claim_status
from services.research_release_manifest import canonical, digest
from tests.test_materials_adjudication import setup,context,request_for,append,settings,BASE
from tests.test_research_freeze import add,seed,state
from tests.test_research_freeze import db_session as db_session
from tests.test_research_publication import actors
from tests.test_scientific_review_operators import auth,private


async def raw_request(db,people,request):
    return await add(db,"scientific_adjudication_requests",actor_user_id=people["reviewer"],
        actor_grant_id=people["grants"]["reviewer"],request_key=request["request_key"],
        request_version=request["version"],request_json=canonical(request).decode(),
        request_sha256=digest(request),item_count=len(request["items"]))


@pytest.mark.parametrize("change",["unknown_field","kind","legacy_profile","scope","proposition","limitations",
    "attestation","check_state","check_key","empty_refs","hash","duplicate_refs","extra_evidence_key","version","dependency"])
async def test_closed_contract_rejected_by_both_python_and_raw_sql(db_session,change):
    fixture,people,_=await setup(db_session);request=request_for(await context(db_session,fixture,people["reviewer"]));item=request["items"][0]
    if change=="unknown_field": item["ml_training_approved"]=True
    elif change=="kind": item["result_kind"]="property"
    elif change=="legacy_profile": item["profile_version"]="sampled-phonon-minimum-review/1.0.0"
    elif change=="scope": item["scope"]="scientific_result"
    elif change=="proposition": item["proposition"]="proven_superconductivity"
    elif change=="limitations": item["limitations"]=[]
    elif change=="attestation": item["source_inspection_attested"]=False
    elif change=="check_state": item["checks"]["source_match"]="not_applicable"
    elif change=="check_key": item["checks"]["model_consensus"]="satisfied"
    elif change=="empty_refs": item["evidence_refs"]=[]
    elif change=="hash": item["expected_subject_sha256"]="not-a-hash"
    elif change=="duplicate_refs": item["evidence_refs"]*=2
    elif change=="extra_evidence_key": item["evidence_refs"][0]["raw_quote"]="private"
    elif change=="version": request["version"]="materials-result-adjudication/99"
    else: item["extraction_decision_id"]=str(uuid4())
    before=await state(db_session)
    with pytest.raises(legacy.ScientificAdjudicationError): contract.validate_request(request)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested(): await raw_request(db_session,people,request)
    assert before==await state(db_session)


@pytest.mark.parametrize("field",["occurrence_id","capture_id","source_revision_id","bytes_sha256"])
async def test_other_result_or_capture_cannot_supply_source_evidence(db_session,field):
    fixture,people,_=await setup(db_session);other,_,_=await setup(db_session)
    request=request_for(await context(db_session,fixture,people["reviewer"]))
    other_ref=(await context(db_session,other,people["reviewer"]))["targets"][0]["eligible_evidence_refs"][0]
    request["items"][0]["evidence_refs"][0][field]="0"*64 if field=="bytes_sha256" else other_ref[field]
    before=await state(db_session)
    with pytest.raises(DBAPIError,match="exact_claim_source_required"):
        await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request)
    assert before==await state(db_session)


@pytest.mark.parametrize("change",["computed_event","quoted_result","unknown_method","unresolved_sample","pressure_conflict","zero_tc"])
async def test_scientific_profile_refuses_known_scope_errors_after_faithful_extraction(db_session,change):
    fixture,people,_=await setup(db_session)
    claims=Base.metadata.tables["material_claims"];events=Base.metadata.tables["research_events"];states=Base.metadata.tables["material_states"]
    if change=="computed_event":
        run=await add(db_session,"research_runs",run_kind="dft",status="completed",settings_schema_version="synthetic/1",record_sha256="9"*64)
        table,key,values=events,fixture["event"],dict(event_type="calculation",knowledge_origin="Computed",producer_run_id=run["id"])
    elif change=="quoted_result": table,key,values=claims,fixture["claim"],dict(evidence_role="cited")
    elif change=="unknown_method": table,key,values=claims,fixture["claim"],dict(measurement_method=None)
    elif change=="unresolved_sample": table,key,values=states,fixture["state"],dict(resolution="unresolved")
    elif change=="pressure_conflict": table,key,values=claims,fixture["claim"],dict(pressure_state="reported",pressure_gpa=20)
    else: table,key,values=claims,fixture["claim"],dict(value_kelvin=0)
    await db_session.execute(table.update().where(table.c.id==key).values(**values))
    await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"])))
    other=await actors(db_session);request=request_for(await context(db_session,fixture,other["reviewer"]),scope="scientific_result")
    with pytest.raises(DBAPIError,match="experimental_tc_scope_required"):
        await service.adjudicate(db_session,actor_user_id=other["reviewer"],request=request)


@pytest.mark.parametrize("table",["scientific_result_subjects","scientific_adjudication_requests","scientific_result_decisions"])
@pytest.mark.parametrize("operation",["UPDATE","DELETE","TRUNCATE"])
async def test_claim_history_refuses_noop_mutation_and_truncation(db_session,table,operation):
    fixture,people,_=await setup(db_session)
    _,receipt=await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"])))
    key={"scientific_result_subjects":receipt["items"][0]["subject_id"],"scientific_adjudication_requests":receipt["request_id"],"scientific_result_decisions":receipt["items"][0]["decision_id"]}[table]
    query=f"UPDATE {table} SET record_sha256=record_sha256 WHERE id=:id" if operation=="UPDATE" else f"DELETE FROM {table} WHERE id=:id" if operation=="DELETE" else f"TRUNCATE {table} CASCADE"
    before=await state(db_session)
    with pytest.raises(DBAPIError,match="append-only"):
        async with db_session.begin_nested(): await db_session.execute(sa.text(query),{"id":UUID(key)})
    assert before==await state(db_session)


async def test_negative_head_requires_explicit_other_reviewer_resolution(db_session):
    fixture,people,_=await setup(db_session)
    _,first=await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"]),decision="reject"))
    request=request_for(await context(db_session,fixture,people["reviewer"]))
    request["items"][0]["resolves_decision_id"]=first["items"][0]["decision_id"]
    with pytest.raises(DBAPIError,match="exact_current_head_required"):
        await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request)
    other=await actors(db_session);request=request_for(await context(db_session,fixture,other["reviewer"]))
    with pytest.raises(DBAPIError,match="exact_current_head_required"):
        await service.adjudicate(db_session,actor_user_id=other["reviewer"],request=request)
    request["items"][0]["resolves_decision_id"]=first["items"][0]["decision_id"]
    await append(db_session,other["reviewer"],request)
    assert (await resolve_claim_status(db_session,fixture["claim"]))["scopes"][0]["effective_status"]=="accepted"


async def test_all_items_roll_back_when_second_subject_has_a_conflict(db_session):
    fixture,people,_=await setup(db_session);second,_,_=await setup(db_session)
    ctx=await context(db_session,fixture,people["reviewer"]);ctx["targets"]+=(await context(db_session,second,people["reviewer"]))["targets"]
    request=request_for(ctx);request["items"][1]["expected_subject_sha256"]="0"*64;before=await state(db_session)
    with pytest.raises(legacy.ScientificAdjudicationConflict): await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request)
    assert before==await state(db_session)


async def test_publication_and_distribution_read_admission_see_claim_rejection(db_session):
    from services.research_publication import _current_catalogue, PublicationUnavailable
    from services import research_distribution as distribution
    fixture,people,_=await setup(db_session)
    await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"]),decision="reject"))
    release={"manifest":{"rows":[{"table":"material_claims","row_id":str(fixture["claim"])}]}}
    with pytest.raises(PublicationUnavailable,match="review hold"): await _current_catalogue(db_session,release)
    # Invoke the actual distribution source gate with its minimal exact-row
    # dependency inventory, not a simulated boolean approval.
    rows=await distribution.fetch_rows(db_session,"material_claims",{str(fixture["claim"])},budget={})
    inventory={"dependencies":[{"table":row["table"],"row_id":row["row_id"],"row_sha256":row["row_sha256"],
        "projection":row["data"],"capsule_manifest_sha256s":[]} for row in rows]}
    with pytest.raises(distribution.ResearchDistributionError,match="exact_scientific_review_hold"):
        await distribution._current_sources(db_session,inventory)


async def test_distribution_digest_pins_review_state_without_granting_publication(db_session):
    from services import research_distribution as distribution
    fixture,people,_=await setup(db_session)
    rows=await distribution.fetch_rows(db_session,"material_claims",{str(fixture["claim"])},budget={})
    inventory={"dependencies":[{"table":r["table"],"row_id":r["row_id"],"row_sha256":r["row_sha256"],
        "projection":r["data"],"capsule_manifest_sha256s":[]} for r in rows]}
    before=await distribution._current_sources(db_session,inventory)
    await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"])))
    after=await distribution._current_sources(db_session,inventory)
    assert before!=after and after==await distribution._current_sources(db_session,inventory)
    assert not (await resolve_claim_status(db_session,fixture["claim"]))["public_release_authorized"]


async def test_faithful_extraction_of_held_source_never_removes_source_veto(db_session):
    from services.materials_review_effects import gate_exact_claim_reviews
    from services.scientific_result_effects import ScientificResultReviewHeld
    fixture,people,_=await setup(db_session)
    await db_session.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"),{"id":fixture["paper"]})
    await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"])))
    status=await resolve_claim_status(db_session,fixture["claim"])
    assert status["scopes"][0]["effective_status"]=="accepted" and status["source_held"]
    with pytest.raises(ScientificResultReviewHeld): await gate_exact_claim_reviews(db_session,[fixture["claim"]])


async def test_http_permission_failure_and_preview_hash_mismatch_are_private(client,db_session):
    fixture,people,_=await setup(db_session);ctx=await context(db_session,fixture,people["reviewer"]);request=request_for(ctx)
    await db_session.commit()
    for role in ("admin","curator","publisher","member"):
        response=await client.post(BASE+"/preview",headers=auth(people[role]),json=request)
        assert response.status_code==403;private(response)
    response=await client.post(BASE+"/commit",headers=auth(people["reviewer"]),json={"request":request,"expected_preview_sha256":"0"*64})
    assert response.status_code==409 and "Synthetic source reviewer" not in response.text;private(response)
