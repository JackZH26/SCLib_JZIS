"""HTTP and source ownership checks for exact typed review preparation."""
from uuid import uuid4
import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from models.db import Base
from services import materials_review_context as service
from services import research_publication
from services.research_access import ResearchAccessDenied
from tests.test_research_freeze import add,state
from tests.test_research_freeze import db_session as db_session
from tests.test_research_publication import actors
from tests.test_materials_review_subjects import claim_fixture
from tests.test_materials_result_definitions import semantics
from models.materials_result_definitions_v1 import REGISTRY_VERSION
from tests.test_scientific_review_operators import auth,private

BASE="/v1/ml/scientific-review/targets/claim/"


@pytest_asyncio.fixture(autouse=True,loop_scope="function")
async def restore_only_owned_synthetic_definitions(db_session):
    """HTTP reads need committed rows; do not contaminate empty-migration tests.

    Keep immutable source/role history. Only this test's mutable claim metadata
    is restored; production downgrade protections are neither removed nor bypassed.
    """
    db_session.info["context_owned_claim_ids"]=[]
    yield
    owned=db_session.info["context_owned_claim_ids"]
    await db_session.rollback()
    if owned:
        claims=Base.metadata.tables["material_claims"]
        await db_session.execute(claims.update().where(claims.c.id.in_(owned)).values(
            tc_definition="unknown",extraction_metadata=claims.c.extraction_metadata.op("-")("result_semantics")))
        await db_session.commit()


async def setup(db):
    fixture,source=await claim_fixture(db);people=await actors(db)
    db.info["context_owned_claim_ids"].append(fixture["claim"])
    claims=Base.metadata.tables["material_claims"]
    definition=semantics("zero_resistance",target="claim")
    definition["definition"]["criterion_raw"]="PRIVATE_CRITERION_WORDING"
    await db.execute(claims.update().where(claims.c.id==fixture["claim"]).values(
        tc_definition="zero_resistance",value_kelvin=6,raw_record={"quote":"PRIVATE_SOURCE_SENTINEL"},
        extraction_metadata={"result_semantics":definition}))
    return fixture,people,source


async def test_actual_context_displays_selected_criterion_without_raw_source_or_authority(db_session):
    fixture,people,_=await setup(db_session);before=await state(db_session)
    context=await service.review_context(db_session,actor_user_id=people["reviewer"],result_kind="claim",result_id=fixture["claim"])
    assert context["target"]["result_id"]==str(fixture["claim"]) and context["result"]["value_kelvin"]==6
    assert context["result"]["definition"]["criterion"]=="zero_resistance"
    assert context["result"]["pressure_state"]=="not_reported" and context["state"]["pressure_gpa"] is None
    assert len(context["source_occurrences"])==1 and context["source_occurrences"][0]["version_status"]=="pinned"
    assert not context["review_write_available"] and not any(context["authority"].values())
    assert "PRIVATE_SOURCE" not in str(context) and "PRIVATE_CRITERION" not in str(context)
    assert await state(db_session)==before


async def test_actual_http_read_is_private_and_does_not_create_any_review(client,db_session):
    fixture,people,_=await setup(db_session);await db_session.commit()
    before=await state(db_session);await db_session.rollback()
    response=await client.get(BASE+str(fixture["claim"]),headers=auth(people["reviewer"]))
    assert response.status_code==200,response.text
    private(response);body=response.json()
    assert body["result"]["value_kelvin"]==6 and body["review_status"]=="not_determined_by_this_read"
    assert "PRIVATE_" not in response.text
    assert await state(db_session)==before


@pytest.mark.parametrize("role",["admin","member","publisher"])
async def test_live_grants_required_before_any_typed_result_is_exposed(client,db_session,role):
    fixture,people,_=await setup(db_session);await db_session.commit()
    response=await client.get(BASE+str(fixture["claim"]),headers=auth(people[role]))
    assert response.status_code==403 and "subject_id" not in response.text
    private(response)


async def test_feature_gate_and_authentication_apply_to_new_route(client,db_session,monkeypatch):
    response=await client.get(BASE+str(uuid4()));assert response.status_code==401;private(response)
    monkeypatch.setattr(get_settings(),"ml_foundation_public_enabled",False)
    response=await client.get(BASE+str(uuid4()));assert response.status_code==404;private(response)


async def test_revoked_reviewer_cannot_reuse_an_earlier_subject_context(client,db_session):
    fixture,people,_=await setup(db_session);await db_session.commit();headers=auth(people["reviewer"])
    assert (await client.get(BASE+str(fixture["claim"]),headers=headers)).status_code==200
    await research_publication.revoke_role(db_session,actor_user_id=people["admin"],grant_id=people["grants"]["reviewer"],
        reason_code="synthetic_review_access_withdrawn",dry_run=False)
    await db_session.commit()
    response=await client.get(BASE+str(fixture["claim"]),headers=headers);assert response.status_code==403;private(response)


async def test_raw_source_edit_changes_pin_while_staying_private(db_session):
    fixture,people,_=await setup(db_session)
    args=dict(actor_user_id=people["curator"],result_kind="claim",result_id=fixture["claim"])
    first=await service.review_context(db_session,**args)
    claims=Base.metadata.tables["material_claims"]
    await db_session.execute(claims.update().where(claims.c.id==fixture["claim"]).values(raw_record={"quote":"DIFFERENT_PRIVATE_SOURCE"}))
    second=await service.review_context(db_session,**args)
    assert second["subject_sha256"]!=first["subject_sha256"] and second["descriptor_sha256"]!=first["descriptor_sha256"]
    assert first["result"]==second["result"] and "DIFFERENT_PRIVATE" not in str(second)


async def test_fitted_field_thresholds_remain_separate_result_definitions(db_session):
    fixture,people,_=await setup(db_session);values=[]
    for threshold,value in ((90,134.4),(50,45.3)):
        prop=await add(db_session,"event_properties",event_id=fixture["event"],property_key="hc2",registry_version=REGISTRY_VERSION,
            component_key="perpendicular",relation="exact",value=value,unit="T",record_sha256=uuid4().hex*2,
            raw={"result_semantics":semantics(threshold=threshold,key=f"field-{threshold}")})
        context=await service.review_context(db_session,actor_user_id=people["reviewer"],result_kind="property",result_id=prop["id"])
        result=context["result"];q=result["definition"]["parameters"][0]["quantity"]
        assert result["value"]==value and result["unit"]=="T" and q["value"]==threshold and q["unit"]=="%"
        assert "raw" not in q and not context["review_write_available"]
        values.append(context)
    assert values[0]["target"]["event_id"]==values[1]["target"]["event_id"]
    assert values[0]["subject_id"]!=values[1]["subject_id"]
