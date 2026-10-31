"""Scientific quantity/ownership regressions on owned disposable PostgreSQL.

Fixtures deliberately include source-shaped errors; they are not expert labels.
"""
import copy
import json
from pathlib import Path
import runpy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from alembic.operations import Operations
from alembic.migration import MigrationContext

from models.db import Base
from models.materials_conditions_v1 import VERSION,LINK_VERSION,SOURCE_VERSION,SUPPORT_VERSION,REGISTRY_VERSION
from services.materials_review_subject import capture_subject,capture_context_subject
from services.materials_review_context import review_context,CONDITIONS_VERSION
from services.scientific_result_subject import ScientificSubjectError
from tests.test_research_freeze import add,seed,db_session as db_session
from tests.test_research_release_schema import flush_constraints,release
from tests.test_materials_context import sample,protocol,quantity
from tests.test_materials_result_definitions import semantics
from tests.test_research_publication import actors


def condition(key="P",kind="pressure",role="measurement",**q):
    return {"id":key,"kind":kind,"role":role,"quantity":quantity(**{"raw":"10 GPa","value":10,"unit":"GPa",**q}),
        "orientation_raw":None,"basis_raw":None,"window_position":None}


def payload(items=(),availability="not_reported",regime="unknown",selected=None,basis=None,temperature=None):
    return {"items":list(items),"pressure":{"availability":availability,"regime":regime,"condition_id":selected,"basis_raw":basis},
        "temperature_condition_id":temperature}


async def state(db,f,sid,body,**overrides):
    return await add(db,"material_states",**{"material_id":f["material"],"sample_id":sid,"resolution":"source_scoped",
        "condition_schema_version":VERSION,"pressure_status":"not_reported","temperature_role":"unknown",
        "context_sha256":"0"*64,"source_artifact_id":f["source"],"conditions":body,**overrides})


async def event(db,f,s,p=None,**overrides):
    context={"materials_context":{"version":"materials-context/1","composition_ids":[],"protocol_id":str(p["id"]),"relation_ids":[]}} if p else {}
    return await add(db,"research_events",**{"material_id":f["material"],"state_id":s["id"],"event_type":"measurement",
        "knowledge_origin":"Observed","record_sha256":"2"*64,"context":context,**overrides})


async def claim(db,f,e,**overrides):
    return await add(db,"material_claims",**{"material_id":f["material"],"work_id":f["work"],"paper_id":f["paper"],
        "event_id":e["id"],"source_snapshot_id":f["snapshot"],"result_key":"pending-state","interpretation_revision":1,
        "source_record_hash":uuid4().hex*2,"extractor_version":"synthetic/1","value_relation":"exact","value_kelvin":4.6,
        "extraction_metadata":{"state_semantics":{"version":LINK_VERSION}},**overrides})


async def setup(db,body=None):
    f=await seed(db);await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"));await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    x=await sample(db,f);s=await state(db,f,x["id"],body or payload());e=await event(db,f,s)
    return f,x,s,e


async def thickness(db,f,e,s,*,key="thickness",q=None,value=8,relation="exact",support=True,**overrides):
    q=q or quantity(raw="8 nm",value=8,unit="nm")
    raw={"result_semantics":semantics("not_applicable",key=key),"source_quantity":{"version":SOURCE_VERSION,"quantity":q}}
    if support:raw["condition_support"]={"version":SUPPORT_VERSION,"targets":[{"state_id":str(s["id"]),"condition_id":"D","relation":"measures","relation_raw":"total film thickness measured by X-ray reflectivity (8 nm)"}]}
    return await add(db,"event_properties",**{"event_id":e["id"],"property_key":"thickness","registry_version":REGISTRY_VERSION,
        "relation":relation,"value":value,"unit":"nm","record_sha256":"a"*64,"raw":raw,**overrides})


@pytest.mark.parametrize("availability",["not_reported","not_accessible","not_extracted","ambiguous","conflicted","not_applicable"])
async def test_missing_pressure_never_becomes_ambient_or_zero(db_session,availability):
    f,x,s,e=await setup(db_session,payload(availability=availability));c=await claim(db_session,f,e,pressure_state="explicit_ambient",pressure_gpa=0)
    assert s["pressure_status"]==c["pressure_state"]==availability
    assert s["pressure_gpa"] is c["pressure_gpa"] is None
    assert s["conditions"]["pressure"]["regime"]=="unknown"


async def test_ambient_statement_is_not_a_measured_zero_pressure(db_session):
    body=payload(availability="reported",regime="explicit_ambient",basis="at ambient pressure")
    f,x,s,e=await setup(db_session,body);c=await claim(db_session,f,e)
    assert s["pressure_status"]==c["pressure_state"]=="explicit_ambient"
    assert s["pressure_gpa"] is c["pressure_gpa"] is None
    subject=await capture_context_subject(db_session,result_kind="claim",result_id=c["id"])
    assert subject.data["target"]["state_id"]==str(s["id"])
    with pytest.raises(ScientificSubjectError,match="materials_conditions_review_contract_required"):
        await capture_subject(db_session,result_kind="claim",result_id=c["id"])


@pytest.mark.parametrize("shape",["exact","interval","gt","ge","lt","le"])
async def test_pressure_shape_survives_without_midpoint_fabrication(db_session,shape):
    q={"relation":shape,"value":100 if shape=="exact" else None,"lower":90 if shape in {"interval","gt","ge"} else None,
        "upper":110 if shape in {"interval","lt","le"} else None,"unit":"kbar","approximate":True}
    c=condition(**q);body=payload([c],availability="reported",regime="nonambient",selected="P",basis="under high pressure")
    f,x,s,e=await setup(db_session,body);r=await claim(db_session,f,e)
    assert s["pressure_gpa"]==r["pressure_gpa"]==(10 if shape=="exact" else None)
    assert s["conditions"]["items"][0]==c
    assert s["pressure_status"]==r["pressure_state"]=="reported"


async def test_synthesis_temperature_and_detection_window_keep_their_roles(db_session):
    synth=condition("Td","temperature","synthesis",raw="740 °C",value=740,unit="°C")
    window=condition("W","temperature","detection_window",raw="1.9 K",value=1.9,unit="K");window["window_position"]="lower_limit"
    f,x,s,e=await setup(db_session,payload([synth,window],temperature="Td"))
    assert s["temperature_role"]=="synthesis" and s["temperature_k"]==1013.15
    c=await claim(db_session,f,e)
    assert c["minimum_temperature_k"] is None and c["value_kelvin"]==4.6
    assert s["conditions"]["items"][1]["quantity"]["value"]==1.9


@pytest.mark.parametrize("mistake",["synthesis_pressure","study_extent_pressure","window_temperature","duplicate_id","false_ambient","unknown_id","missing_key","unknown_role","window_marker","negative_kelvin","unit_mismatch"])
async def test_ambiguous_or_misassigned_context_cannot_be_registered(db_session,mistake):
    c=condition();body=payload([c],availability="reported",selected="P")
    if mistake=="synthesis_pressure":c["role"]="synthesis"
    if mistake=="study_extent_pressure":c["role"]="study_extent"
    if mistake=="window_temperature":
        c.update(kind="temperature",role="detection_window",window_position="lower_limit");c["quantity"].update(unit="K")
        body=payload([c],temperature="P")
    if mistake=="duplicate_id":body["items"].append(copy.deepcopy(c))
    if mistake=="false_ambient":body["pressure"].update(availability="not_reported",regime="explicit_ambient",basis_raw="ambient")
    if mistake=="unknown_id":body["pressure"]["condition_id"]="missing"
    if mistake=="missing_key":del body["temperature_condition_id"]
    if mistake=="unknown_role":c["role"]="tc"
    if mistake=="window_marker":c["window_position"]="lower_limit"
    if mistake=="negative_kelvin":c.update(kind="temperature");c["quantity"].update(value=-300,unit="°C");body=payload([c],temperature="P")
    if mistake=="unit_mismatch":c["quantity"]["unit"]="K"
    f=await seed(db_session);x=await sample(db_session,f)
    with pytest.raises(DBAPIError,match="materials_state_condition_contract"):
        async with db_session.begin_nested():await state(db_session,f,x["id"],body)


async def geometry(db,*,method="X-ray reflectivity",method_class="other",value=8):
    f=await seed(db);await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"));await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    x=await sample(db,f);d=condition("D","thickness","sample_geometry",raw="8 nm",value=value,unit="nm")
    s=await state(db,f,x["id"],payload([d]));p=await protocol(db,f,method_class=method_class,method_raw=method)
    e=await event(db,f,s,p);return f,x,s,p,e


async def test_two_measured_results_support_one_state_condition_without_duplication(db_session):
    f,x,s,p,e=await geometry(db_session)
    first=await thickness(db_session,f,e,s)
    other=await protocol(db_session,f,method_class="other",method_raw="TEM")
    e2=await event(db_session,f,s,other)
    second=await thickness(db_session,f,e2,s,key="tem",q=quantity(raw="80 Å",value=80,unit="Å"))
    assert first["value"]==second["value"]==8
    for prop in (first,second):
        data=(await capture_context_subject(db_session,result_kind="property",result_id=prop["id"])).data
        rows={(v["table"],v["row_id"]):v["snapshot"] for v in data["rows"]}
        assert rows["material_states",str(s["id"])]["conditions"]["items"][0]["id"]=="D"
        assert rows["event_properties",str(prop["id"])]["raw"]["condition_support"]["targets"][0]["state_id"]==str(s["id"])
    assert (await db_session.scalar(sa.text("SELECT count(*) FROM material_states WHERE id=:id"),{"id":s["id"]}))==1


@pytest.mark.parametrize("mistake",["wrong_state","missing_condition","wrong_relation","duplicate_target","numeric_mismatch","source_projection","method_missing","fitted_layer","computed","state_mutation","event_origin_change"])
async def test_false_geometry_support_is_refused(db_session,mistake):
    f,x,s,p,e=await geometry(db_session,method=None if mistake=="method_missing" else "X-ray reflectivity",
        method_class="unspecified" if mistake=="method_missing" else "other")
    kwargs={};raw={"result_semantics":semantics("not_applicable",key="bad"),
        "source_quantity":{"version":SOURCE_VERSION,"quantity":quantity(raw="8 nm",value=8,unit="nm")},
        "condition_support":{"version":SUPPORT_VERSION,"targets":[{"state_id":str(s["id"]),"condition_id":"D","relation":"measures","relation_raw":"measured thickness"}]}}
    edge=raw["condition_support"]["targets"][0]
    if mistake=="wrong_state":edge["state_id"]=str(uuid4())
    if mistake=="missing_condition":edge["condition_id"]="missing"
    if mistake=="wrong_relation":edge["relation"]="derived_from"
    if mistake=="duplicate_target":raw["condition_support"]["targets"].append(copy.deepcopy(edge))
    if mistake=="numeric_mismatch":raw["source_quantity"]["quantity"].update(raw="5 nm",value=5);kwargs["value"]=5
    if mistake=="source_projection":kwargs["value"]=5
    if mistake=="fitted_layer":kwargs.update(property_key="superconducting_layer_thickness",registry_version="materials-properties/1")
    if mistake=="computed":
        # Use a fresh inferred event; changing an existing one is also forbidden.
        e=await event(db_session,f,s,p,event_type="calculation",knowledge_origin="Inferred")
    with pytest.raises(DBAPIError,match="materials_"):
        async with db_session.begin_nested():
            if mistake=="state_mutation":await db_session.execute(Base.metadata.tables['material_states'].update().where(Base.metadata.tables['material_states'].c.id==s['id']).values(pressure_status="explicit_ambient"))
            elif mistake=="event_origin_change":await db_session.execute(Base.metadata.tables['research_events'].update().where(Base.metadata.tables['research_events'].c.id==e['id']).values(knowledge_origin="Inferred"))
            else:await thickness(db_session,f,e,s,raw=raw,**kwargs)


async def test_source_uncertainty_and_approximation_remain_visible_without_quotes(db_session):
    f,x,s,p,e=await geometry(db_session)
    q=quantity(raw="approximately 8 ± 0.2 nm",value=8,unit="nm",approximate=True,
        uncertainty={"kind":"reported_unspecified","minus":0.2,"plus":0.2,"level":None,"raw":"± 0.2 nm"})
    prop=await thickness(db_session,f,e,s,q=q,support=False);people=await actors(db_session)
    body=await review_context(db_session,actor_user_id=people["reviewer"],result_kind="property",result_id=prop["id"])
    assert body["version"]==CONDITIONS_VERSION
    assert body["result"]["source_quantity"]["approximate"] is True
    assert body["result"]["source_quantity"]["uncertainty"]["plus"]==0.2
    assert body["state"]["conditions"]["items"][0]["role"]=="sample_geometry"
    assert "approximately" not in str(body) and not body["source_text_disclosed"] and not any(body["authority"].values())


async def test_new_state_requires_explicit_claim_link_and_retains_old_release_gate(db_session):
    f,x,s,e=await setup(db_session,payload(availability="reported",regime="explicit_ambient",basis="ambient pressure"))
    with pytest.raises(DBAPIError,match="materials_claim_state_link_required"):
        async with db_session.begin_nested():await claim(db_session,f,e,extraction_metadata={})
    c=await claim(db_session,f,e)
    body=await db_session.scalar(sa.text("SELECT sclib_scientific_subject_capture_v2('claim',:id)"),{"id":c["id"]})
    with pytest.raises(DBAPIError,match="materials_conditions_review_contract_required"):
        async with db_session.begin_nested():await db_session.execute(sa.text("INSERT INTO scientific_result_subjects(basis_json) VALUES(:body)"),{"body":body})
    with pytest.raises(DBAPIError,match="materials_conditions_release_contract_required"):
        async with db_session.begin_nested():await release(db_session,{"dataset":{"id":f["args"]["dataset_id"]}},[("material_states",s["id"])])


async def migrate(db,direction):
    module=runpy.run_path(str(Path(__file__).parents[1]/'alembic/versions/0097_materials_conditions.py'));conn=await db.connection()
    def run(connection):
        with Operations.context(MigrationContext.configure(connection)):module[direction]()
    await conn.run_sync(run)


async def test_empty_migration_roundtrip_preserves_legacy_ambient_semantics(db_session):
    f=await seed(db_session);x=await sample(db_session,f)
    old=await state(db_session,f,x["id"],{},condition_schema_version="legacy",pressure_status="explicit_ambient",pressure_gpa=0)
    await flush_constraints(db_session);await migrate(db_session,'downgrade');await migrate(db_session,'upgrade')
    actual=(await db_session.execute(sa.select(Base.metadata.tables['material_states']).where(Base.metadata.tables['material_states'].c.id==old['id']))).mappings().one()
    assert actual==old


async def test_retained_state_refuses_downgrade(db_session):
    await setup(db_session)
    with pytest.raises(DBAPIError,match="materials_conditions_retained_history_refuses_downgrade"):
        async with db_session.begin_nested():await migrate(db_session,'downgrade')
