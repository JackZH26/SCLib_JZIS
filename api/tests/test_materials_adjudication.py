"""Owned disposable PostgreSQL only; every reviewer/source/result is synthetic.

Passing these engineering checks is not a human read or scientific acceptance
of any real paper. Never copy fixture approvals into a production database.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from services import materials_adjudication as service
from services import materials_adjudication_contract as contract
from services import scientific_adjudication_contract as old_contract
from services import research_publication
from services.materials_review_effects import resolve_claim_status, gate_exact_claim_reviews
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical, digest
from services.scientific_result_effects import ScientificResultReviewHeld
from services.source_registry import import_source_provenance_bundle
from tests.test_research_freeze import add, seed, state
from tests.test_research_freeze import db_session as db_session
from tests.test_research_publication import actors
from tests.test_source_registry import bundle, reviewed
from tests.test_scientific_review_operators import auth, private

BASE = "/v1/ml/scientific-review/adjudication/claims"


async def settings(db):
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))


async def setup(db, *, reviewed_source=True, non_detection=False):
    fixture = await seed(db); await settings(db); people = await actors(db)
    await add(db,"paper_work_map",paper_id=fixture["paper"],work_id=fixture["work"],
              relation_type="preprint",match_method="manual",review_status="accepted")
    claims = Base.metadata.tables["material_claims"]
    changes = dict(evidence_role="primary_experimental", measurement_method="resistivity", tc_definition="zero_resistance")
    if non_detection: changes.update(property_type="non_transition",result_status="not_detected",value_relation="unreported",value_kelvin=None)
    claim = (await db.execute(claims.update().where(claims.c.id==fixture["claim"]).values(**changes).returning(claims))).mappings().one()
    source = bundle(fixture["paper"],fixture["work"],fixture["claim"])
    if reviewed_source: await reviewed(db,source,claim)
    await import_source_provenance_bundle(db,source,dry_run=False)
    return fixture,people,source


async def context(db, fixture, actor):
    return await service.action_context(db,actor_user_id=actor,targets=[{"result_kind":"claim","result_id":str(fixture["claim"])}])


def request_for(context, *, decision="accept", scope="extraction_fidelity"):
    items=[]
    for target in context["targets"]:
        profile=next(p for p in target["available_profiles"] if contract.PROFILES[p][0]==scope)
        heads={row["scope"]:row["decision_id"] for row in target["heads"]}
        items.append({"decision_id":str(uuid4()),"subject_id":target["subject_id"],"result_kind":"claim","result_id":target["result_id"],
            "scope":scope,"profile_version":profile,"expected_subject_sha256":target["subject_sha256"],
            "expected_previous_decision_id":heads[scope],"expected_impact_sha256":target["impact_sha256"],
            "decision":decision,"reason_code":{"accept":"evidence_and_scope_match","reject":"scientific_concern","request_clarification":"insufficient_evidence"}[decision],
            "rationale":"Synthetic source reviewer declaration for bounded integration tests only.",
            "proposition":contract.PROFILES[profile][1],"limitations":list(contract.LIMITATIONS),
            "checks":{key:"satisfied" if decision=="accept" else "unresolved" for key in contract.CHECKS},
            "evidence_refs":deepcopy(target["eligible_evidence_refs"]) if decision=="accept" else [],
            "source_inspection_attested":decision=="accept","resolves_decision_id":None,
            "extraction_decision_id":heads["extraction_fidelity"] if scope=="scientific_result" and decision=="accept" else None})
    return {"version":contract.VERSION,"request_key":"synthetic-claim-review:"+uuid4().hex,"items":items}


async def append(db, actor, request, *, commit=True):
    preview=await service.adjudicate(db,actor_user_id=actor,request=request)
    receipt=await service.adjudicate(db,actor_user_id=actor,request=request,expected_preview_sha256=preview["preview_sha256"],dry_run=False)
    assert receipt["committed"] is False
    if commit: await db.commit(); await settings(db)
    return preview,receipt


async def migration(db, action):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    module=runpy.run_path(str(Path(__file__).parents[1]/"alembic/versions/0095_materials_adjudication.py"))
    conn=await db.connection()
    def apply(connection):
        with Operations.context(MigrationContext.configure(connection)): module[action]()
    await conn.run_sync(apply)


async def test_00_migration_roundtrip_retains_legacy_hashes_rows_and_behavior(db_session):
    from tests.test_scientific_adjudication_schema import accepted
    from services.scientific_result_subject import capture_result_subject
    seeded,subject,request,decision=await accepted(db_session)
    old=await capture_result_subject(db_session,seeded["property_id"]); before=await state(db_session)
    legacy_hash=await db_session.scalar(sa.text("SELECT sclib_scientific_adjudication_text_hash_v1(sclib_scientific_adjudication_canonical_v1(to_jsonb(d)-ARRAY['claim_id','created_at','record_sha256','basis_json','request_json','assembly_xid'])) FROM scientific_result_decisions d WHERE id=:id"),{"id":decision["id"]})
    assert legacy_hash==decision["record_sha256"]
    await migration(db_session,"downgrade")
    assert await capture_result_subject(db_session,seeded["property_id"])==old
    assert await db_session.scalar(sa.text("SELECT record_sha256=sclib_scientific_adjudication_record_hash_v1(to_jsonb(d)) FROM scientific_result_decisions d WHERE id=:id"),{"id":decision["id"]})
    await migration(db_session,"upgrade")
    assert before==await state(db_session) and await capture_result_subject(db_session,seeded["property_id"])==old


async def test_context_and_real_sql_preview_preserve_all_rows(db_session):
    fixture,people,_=await setup(db_session);before=await state(db_session)
    ctx=await context(db_session,fixture,people["reviewer"]); request=request_for(ctx)
    result=await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request)
    assert result["can_commit"] and not result["database_mutated"] and not result["ml_training_approved"]
    assert before==await state(db_session)
    assert ctx["targets"][0]["dossier"]["result"]["pressure_gpa"] is None
    assert ctx["targets"][0]["dossier"]["result"]["measurement_method"]=="resistivity"
    assert ctx["targets"][0]["dossier"]["result"]["evidence_role"]=="primary_experimental"


@pytest.mark.parametrize("decision,expected",[("accept","accepted"),("reject","rejected"),("request_clarification","clarification_required")])
async def test_claim_decision_replay_and_exact_scope_do_not_approve_siblings(db_session,decision,expected):
    fixture,people,_=await setup(db_session);ctx=await context(db_session,fixture,people["reviewer"])
    before=await state(db_session);request=request_for(ctx,decision=decision)
    preview,receipt=await append(db_session,people["reviewer"],request)
    after=await state(db_session)
    ignored={"scientific_result_subjects","scientific_adjudication_requests","scientific_result_decisions","research_integrity_epoch","research_publication_epoch","source_lifecycle_epoch"}
    assert {k:v for k,v in before.items() if k not in ignored}=={k:v for k,v in after.items() if k not in ignored}
    replay=await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request,expected_preview_sha256=preview["preview_sha256"],dry_run=False)
    assert {**replay,"replayed":False}==receipt and after==await state(db_session)
    status=await resolve_claim_status(db_session,fixture["claim"])
    assert status["scopes"][0]["effective_status"]==expected and status["scopes"][1]["effective_status"]=="unreviewed"
    assert not status["ml_training_approved"] and not status["public_release_authorized"]
    sibling=await resolve_claim_status(db_session,fixture["children"]["sibling_claim"])
    assert all(s["effective_status"]=="unreviewed" for s in sibling["scopes"])
    if decision!="accept":
        with pytest.raises(ScientificResultReviewHeld): await gate_exact_claim_reviews(db_session,[fixture["claim"]])


async def test_scientific_acceptance_requires_a_different_current_reviewer_and_same_fidelity_subject(db_session):
    fixture,people,_=await setup(db_session)
    await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"])))
    request=request_for(await context(db_session,fixture,people["reviewer"]),scope="scientific_result")
    with pytest.raises(DBAPIError,match="independent_current_fidelity"):
        await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request)
    other=await actors(db_session);request=request_for(await context(db_session,fixture,other["reviewer"]),scope="scientific_result")
    await append(db_session,other["reviewer"],request)
    status=await resolve_claim_status(db_session,fixture["claim"])
    assert [s["effective_status"] for s in status["scopes"]]==["accepted","accepted"]
    assert not status["ml_training_approved"] and await gate_exact_claim_reviews(db_session,[fixture["claim"]])
    assert await db_session.scalar(sa.text("SELECT validity_status FROM material_claims WHERE id=:id"),{"id":fixture["claim"]})=="pending"


@pytest.mark.parametrize("change",["value","criterion","state","raw","new_source_version"])
async def test_changed_scientific_basis_stales_prior_decision_and_preview(db_session,change):
    fixture,people,_=await setup(db_session)
    oldctx=await context(db_session,fixture,people["reviewer"])
    await append(db_session,people["reviewer"],request_for(oldctx))
    request=request_for(await context(db_session,fixture,people["reviewer"]))
    claims=Base.metadata.tables["material_claims"]
    if change=="value": values={"value_kelvin":38}
    elif change=="criterion": values={"tc_definition":"onset"}
    elif change=="raw": values={"raw_record":{"quote":"Changed private evidence"}}
    else: values={}
    if values: await db_session.execute(claims.update().where(claims.c.id==fixture["claim"]).values(**values))
    elif change=="state":
        await db_session.execute(sa.text("UPDATE material_states SET conditions='{"+'"measurement":"changed"'+"}'::jsonb WHERE id=:id"),{"id":fixture["state"]})
    else:
        data=bundle(fixture["paper"],fixture["work"],fixture["claim"])
        data["source_revisions"][0].update(revision_key="arxiv-v3",provider_revision="v3")
        await import_source_provenance_bundle(db_session,data,dry_run=False)
    before=await state(db_session)
    with pytest.raises(old_contract.ScientificAdjudicationConflict,match="subject_changed"):
        await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request)
    assert before==await state(db_session)
    assert (await resolve_claim_status(db_session,fixture["claim"]))["scopes"][0]["effective_status"]=="stale"
    with pytest.raises(ScientificResultReviewHeld): await gate_exact_claim_reviews(db_session,[fixture["claim"]])


async def test_current_request_cannot_change_its_source_before_commit(db_session):
    fixture,people,_=await setup(db_session)
    request=request_for(await context(db_session,fixture,people["reviewer"]))
    await append(db_session,people["reviewer"],request,commit=False)
    with pytest.raises(DBAPIError,match="assembly_changed"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("UPDATE material_claims SET value_kelvin=38 WHERE id=:id"),{"id":fixture["claim"]})


async def test_impact_includes_exact_ml_label_input_and_distinguishes_event_context(db_session):
    fixture,people,_=await setup(db_session);original,sha=await service._impact(db_session,fixture["claim"])
    assert any(x["relation"]=="label_claim_reference" and x["row_id"]==str(fixture["example"]) for x in original["items"])
    assert any(x["relation"]=="input_event_context_reference" for x in original["items"])
    assert not any(x["relation"]=="input_claim_reference" for x in original["items"])
    request=request_for(await context(db_session,fixture,people["reviewer"]))
    await add(db_session,"ml_example_inputs",example_id=fixture["example"],input_kind="claim",input_event_id=fixture["event"],
              input_claim_id=fixture["claim"],feature_key="synthetic-claim-input",matching_policy_version="synthetic/1",record_sha256="1"*64)
    new,newsha=await service._impact(db_session,fixture["claim"])
    assert sha!=newsha and any(x["relation"]=="input_claim_reference" for x in new["items"])
    with pytest.raises(old_contract.ScientificAdjudicationConflict,match="impact_changed"):
        await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request)


async def test_no_reviewed_source_no_acceptance_but_clarification_can_be_recorded(db_session):
    fixture,people,_=await setup(db_session,reviewed_source=False);ctx=await context(db_session,fixture,people["reviewer"])
    assert not ctx["targets"][0]["eligible_evidence_refs"]
    with pytest.raises(old_contract.ScientificAdjudicationError,match="acceptance_checks"):
        await service.adjudicate(db_session,actor_user_id=people["reviewer"],request=request_for(ctx))
    await append(db_session,people["reviewer"],request_for(ctx,decision="request_clarification"))


async def test_nondetection_fidelity_preserves_unknown_window_without_a_negative_scientific_profile(db_session):
    fixture,people,_=await setup(db_session,non_detection=True);ctx=await context(db_session,fixture,people["reviewer"])
    assert ctx["targets"][0]["available_profiles"]==["reported-non-detection-fidelity/1.0.0"]
    await append(db_session,people["reviewer"],request_for(ctx))
    row=(await db_session.execute(sa.text("SELECT value_kelvin,minimum_temperature_k FROM material_claims WHERE id=:id"),{"id":fixture["claim"]})).one()
    assert row.value_kelvin is None and row.minimum_temperature_k is None
    assert (await resolve_claim_status(db_session,fixture["claim"]))["scopes"][1]["effective_status"]=="unreviewed"


@pytest.mark.parametrize("role",["admin","curator","publisher","member"])
async def test_current_reviewer_required_no_legacy_role_escalation(db_session,role):
    fixture,people,_=await setup(db_session);request=request_for(await context(db_session,fixture,people["reviewer"]));before=await state(db_session)
    with pytest.raises(ResearchAccessDenied): await service.adjudicate(db_session,actor_user_id=people[role],request=request)
    assert before==await state(db_session)


async def test_revoked_review_cannot_continue_as_a_current_acceptance(db_session):
    fixture,people,_=await setup(db_session)
    await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"])))
    await research_publication.revoke_role(db_session,actor_user_id=people["admin"],grant_id=people["grants"]["reviewer"],reason_code="synthetic_revocation",dry_run=False)
    assert (await resolve_claim_status(db_session,fixture["claim"]))["scopes"][0]["effective_status"]=="reviewer_unavailable"
    with pytest.raises(ScientificResultReviewHeld): await gate_exact_claim_reviews(db_session,[fixture["claim"]])


async def test_migration_refuses_to_erase_retained_claim_history(db_session):
    fixture,people,_=await setup(db_session)
    await append(db_session,people["reviewer"],request_for(await context(db_session,fixture,people["reviewer"])))
    before=await state(db_session)
    with pytest.raises(DBAPIError,match="retained_history_refuses_downgrade"):
        async with db_session.begin_nested(): await migration(db_session,"downgrade")
    assert before==await state(db_session)


async def test_http_preview_commit_replay_and_private_receipt(client,db_session):
    fixture,people,_=await setup(db_session);await db_session.commit();headers=auth(people["reviewer"])
    response=await client.post(BASE+"/context",headers=headers,json={"targets":[{"result_kind":"claim","result_id":str(fixture["claim"])}]})
    assert response.status_code==200,response.text
    private(response);request=request_for(response.json());await db_session.rollback()
    before=await state(db_session);await db_session.rollback()
    response=await client.post(BASE+"/preview",headers=headers,json=request)
    assert response.status_code==200,response.text
    private(response);preview=response.json();assert before==await state(db_session);await db_session.rollback()
    response=await client.post(BASE+"/commit",headers=headers,json={"request":request,"expected_preview_sha256":preview["preview_sha256"]})
    assert response.status_code==200,response.text
    private(response);assert response.json()["committed"] and not response.json()["ml_training_approved"]
    found=await client.get(BASE+"/requests/"+request["request_key"],headers=headers)
    assert found.status_code==200 and found.json()["replayed"] and "Synthetic source reviewer" not in found.text
    private(found)
