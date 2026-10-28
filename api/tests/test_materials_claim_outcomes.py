"""Scientific-statement distinctions on actual disposable PostgreSQL.

Cases mirror disclosed paper failure modes; synthetic fixtures are not Gold.
"""
import copy
from pathlib import Path
import runpy

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from alembic.operations import Operations
from alembic.migration import MigrationContext

from models.db import Base
from models.materials_claim_outcomes_v1 import VERSION
from services.materials_review_context import review_context, OUTCOMES_VERSION
from services.materials_review_subject import capture_context_subject
from tests.test_research_freeze import db_session as db_session
from tests.test_materials_conditions import setup, claim, condition, payload, LINK_VERSION
from tests.test_materials_result_definitions import semantics
from tests.test_materials_context import quantity, protocol, event as context_event
from tests.test_research_release_schema import flush_constraints
from tests.test_research_publication import actors


def tc(q=None):
    return {"version":VERSION,"kind":"tc","quantity":q or quantity(raw="6.61 K",value=6.61,unit="K")}


def conditional(bound=None):
    return {"condition":"if_superconducting","raw":"if they are superconducting at all",
        "tc_bound":bound or quantity(raw="lower than 1.9 K",relation="lt",value=None,upper=1.9,unit="K")}


def negative(availability="not_reported",ids=(),**extra):
    return {"version":VERSION,"kind":"non_detection","target":"superconductivity","observable":"resistive_transition",
        "raw":"No superconductivity was observed down to 1.8 K in this pressure range.",
        "window":{"availability":availability,"condition_ids":list(ids)},**extra}


def window(key="W",*,position="lower_limit",**kw):
    c=condition(key,"temperature","detection_window",**{"raw":"1.8 K","unit":"K","value":1.8,**kw})
    c["window_position"]=position
    return c


async def outcome(db,f,e,body,**kw):
    meta={"state_semantics":{"version":LINK_VERSION},"materials_outcome":body}
    if body.get("kind")=="tc":meta["result_semantics"]=semantics("onset",target="claim")
    return await claim(db,f,e,**{"extraction_metadata":meta,**kw})


@pytest.mark.parametrize("shape",["exact","interval","lt","le","gt","ge"])
async def test_tc_source_shape_and_millikelvin_projection(db_session,shape):
    f,x,s,e=await setup(db_session)
    q=quantity(raw="approximately 6600 mK",unit="mK",relation=shape,approximate=True,
        value=6610 if shape=="exact" else None,lower=6600 if shape in {"interval","gt","ge"} else None,
        upper=6630 if shape in {"interval","lt","le"} else None,
        uncertainty={"kind":"standard_error","minus":20,"plus":30,"level":None,"raw":"-20/+30 mK"})
    c=await outcome(db_session,f,e,tc(q),value_kelvin=999,minimum_temperature_k=0)
    assert c["value_relation"]==shape and c["result_status"]=="observed" and c["property_type"]=="tc"
    assert c["value_kelvin"]==(6.61 if shape=="exact" else None)
    assert c["value_lower_kelvin"]==(6.6 if shape in {"interval","gt","ge"} else None)
    assert c["value_upper_kelvin"]==(6.63 if shape in {"interval","lt","le"} else None)
    assert c["minimum_temperature_k"] is None
    assert c["extraction_metadata"]["materials_outcome"]["quantity"]==q


@pytest.mark.parametrize("status",["not_reported","not_accessible","not_extracted","ambiguous","conflicted"])
async def test_missing_tc_stays_missing_instead_of_zero_or_non_detection(db_session,status):
    f,x,s,e=await setup(db_session)
    q=quantity(status=status,raw=None,relation=None,value=None,unit=None)
    c=await outcome(db_session,f,e,tc(q),value_kelvin=0)
    assert c["property_type"]=="tc" and c["value_relation"]=="unreported"
    assert c["value_kelvin"] is c["value_lower_kelvin"] is c["value_upper_kelvin"] is None
    assert c["result_status"]==("inconclusive" if status in {"ambiguous","conflicted"} else "unknown")


async def test_conditional_upper_bound_is_neither_measured_tc_nor_detection_floor(db_session):
    f,x,s,e=await setup(db_session,payload([window()]))
    body={"version":VERSION,"kind":"conditional_tc","conditional":conditional()}
    c=await outcome(db_session,f,e,body,value_kelvin=0,value_upper_kelvin=1.9,minimum_temperature_k=1.9)
    assert c["property_type"]=="non_transition" and c["result_status"]=="inconclusive"
    assert c["value_relation"]=="unreported"
    assert all(c[k] is None for k in ["value_kelvin","value_lower_kelvin","value_upper_kelvin","minimum_temperature_k"])
    assert c["extraction_metadata"]["materials_outcome"]["conditional"]["tc_bound"]["upper"]==1.9
    data=(await capture_context_subject(db_session,result_kind="claim",result_id=c["id"])).data
    root=next(r["snapshot"] for r in data["rows"] if r["table"]=="material_claims" and r["row_id"]==str(c["id"]))
    assert root["extraction_metadata"]["materials_outcome"]==body


@pytest.mark.parametrize("availability",["not_reported","not_accessible","not_extracted","ambiguous","conflicted"])
async def test_explicit_non_detection_can_retain_unavailable_window(db_session,availability):
    f,x,s,e=await setup(db_session)
    c=await outcome(db_session,f,e,negative(availability),minimum_temperature_k=1.9,value_kelvin=0)
    assert c["result_status"]=="not_detected" and c["property_type"]=="non_transition"
    assert c["value_kelvin"] is c["value_upper_kelvin"] is c["minimum_temperature_k"] is None


@pytest.mark.parametrize("scope",["floor","interval","upper_only","bounded_floor","two_windows"])
async def test_only_reported_selected_window_can_supply_minimum_temperature(db_session,scope):
    items=[window()];expected=1.8
    if scope=="interval":items=[window(position="interval",relation="interval",value=None,lower=1.8,upper=70)]
    if scope=="upper_only":items=[window(position="upper_limit",value=70)];expected=None
    if scope=="bounded_floor":items=[window(relation="gt",value=None,lower=1.8)];expected=None
    if scope=="two_windows":items.append(window("W2",value=2));expected=None
    f,x,s,e=await setup(db_session,payload(items))
    c=await outcome(db_session,f,e,negative("reported",[v["id"] for v in items],conditional=conditional()))
    assert c["minimum_temperature_k"]==expected and c["value_relation"]=="unreported"
    assert c["value_upper_kelvin"] is None  # Neither Tmin nor the conditional bound is a Tc label.


@pytest.mark.parametrize("mistake",["missing_condition","synthesis","measurement","non_temperature","duplicate","unreported_with_ids","reported_without_ids","window_wrong_shape","window_wrong_direction","foreign_condition","unknown_observable","wrong_target","computed","theory_attribution","extra_quantity","malformed_conditional","unconditional_upper_bound"])
async def test_false_negative_or_window_binding_is_rejected(db_session,mistake):
    c=window();body=negative("reported",["W"]);extra={}
    if mistake=="synthesis":c.update(role="synthesis",window_position=None)
    if mistake=="measurement":c.update(role="measurement",window_position=None)
    if mistake=="non_temperature":c["kind"]="pressure";c["quantity"]["unit"]="GPa"
    if mistake=="window_wrong_shape":c["window_position"]="interval"
    if mistake=="window_wrong_direction":c["quantity"].update(relation="lt",value=None,upper=1.8)
    f,x,s,e=await setup(db_session,payload([c]))
    if mistake in {"missing_condition","foreign_condition"}:body["window"]["condition_ids"]=["elsewhere"]
    if mistake=="duplicate":body["window"]["condition_ids"].append("W")
    if mistake=="unreported_with_ids":body["window"]["availability"]="not_reported"
    if mistake=="reported_without_ids":body["window"]["condition_ids"]=[]
    if mistake=="unknown_observable":body["observable"]="no_magnetism"
    if mistake=="wrong_target":body["target"]="ferromagnetism"
    if mistake=="computed":
        from tests.test_materials_conditions import event
        e=await event(db_session,f,s,event_type="calculation",knowledge_origin="Inferred")
    if mistake=="theory_attribution":extra["evidence_role"]="primary_theoretical"
    if mistake=="extra_quantity":body["quantity"]=quantity(raw="0 K",value=0,unit="K")
    if mistake=="malformed_conditional":body["conditional"]=None
    if mistake=="unconditional_upper_bound":body["tc_bound"]=conditional()["tc_bound"]
    with pytest.raises(DBAPIError,match="materials_outcome"):
        async with db_session.begin_nested():await outcome(db_session,f,e,body,**extra)


@pytest.mark.parametrize("mistake",["temperature_unit","negative","not_applicable","extra_key","missing_definition","conditional_point","conditional_wrong_condition","legacy_state","wrong_work"])
async def test_malformed_tc_or_conditional_contract_is_rejected(db_session,mistake):
    f,x,s,e=await setup(db_session);body=tc();extra={}
    if mistake=="temperature_unit":body["quantity"]["unit"]="T"
    if mistake=="negative":body["quantity"]["value"]=-1
    if mistake=="not_applicable":body["quantity"].update(status="not_applicable",value=None,relation=None)
    if mistake=="extra_key":body["pressure_gpa"]=0
    if mistake=="missing_definition":extra["extraction_metadata"]={"state_semantics":{"version":LINK_VERSION},"materials_outcome":body}
    if mistake.startswith("conditional_"):
        body={"version":VERSION,"kind":"conditional_tc","conditional":conditional()}
        if mistake=="conditional_point":body["conditional"]["tc_bound"].update(relation="exact",value=1.9,upper=None)
        else:body["conditional"]["condition"]="superconducting"
    if mistake=="legacy_state":e=await context_event(db_session,f,x["id"],p=(await protocol(db_session,f))["id"])
    if mistake=="wrong_work":extra["work_id"]=None
    with pytest.raises(DBAPIError,match="materials_"):
        async with db_session.begin_nested():await outcome(db_session,f,e,body,**extra)


async def test_private_read_shows_outcome_without_raw_text_or_approval(db_session):
    f,x,s,e=await setup(db_session,payload([window()]));people=await actors(db_session)
    c=await outcome(db_session,f,e,negative("reported",["W"],conditional=conditional()))
    result=await review_context(db_session,actor_user_id=people["reviewer"],result_kind="claim",result_id=c["id"])
    assert result["version"]==OUTCOMES_VERSION and result["result"]["minimum_temperature_k"]==1.8
    assert result["result"]["outcome"]["conditional"]["tc_bound"]["upper"]==1.9
    assert result["result"]["outcome"]["window"]["condition_ids"]==["W"]
    assert "No superconductivity" not in str(result) and "if they are" not in str(result)
    assert not result["source_text_disclosed"] and not any(result["authority"].values())


@pytest.mark.parametrize("action",["quantity","remove_contract","change_event","change_window","delete","approve"])
async def test_new_values_and_interpretation_cannot_be_overwritten_or_promoted(db_session,action):
    f,x,s,e=await setup(db_session,payload([window()]));c=await outcome(db_session,f,e,negative("reported",["W"]))
    table=Base.metadata.tables["material_claims"];meta=copy.deepcopy(c["extraction_metadata"])
    if action=="quantity":changes={"value_kelvin":0}
    elif action=="remove_contract":del meta["materials_outcome"];changes={"extraction_metadata":meta}
    elif action=="change_event":changes={"event_id":None}
    elif action=="change_window":meta["materials_outcome"]["window"]["condition_ids"]=[];changes={"extraction_metadata":meta}
    elif action=="approve":changes={"validity_status":"accepted"}
    with pytest.raises(DBAPIError,match="materials_"):
        async with db_session.begin_nested():
            statement=table.delete() if action=="delete" else table.update().values(**changes)
            await db_session.execute(statement.where(table.c.id==c["id"]))


async def migration(db,action):
    module=runpy.run_path(str(Path(__file__).parents[1]/"alembic/versions/0098_materials_claim_outcomes.py"));conn=await db.connection()
    def run(connection):
        with Operations.context(MigrationContext.configure(connection)):module[action]()
    await conn.run_sync(run)


async def test_empty_migration_roundtrip_keeps_old_claims_unchanged(db_session):
    f,x,s,e=await setup(db_session);c=await claim(db_session,f,e);await flush_constraints(db_session)
    await migration(db_session,"downgrade");await migration(db_session,"upgrade")
    table=Base.metadata.tables["material_claims"]
    actual=(await db_session.execute(sa.select(table).where(table.c.id==c["id"]))).mappings().one()
    assert actual==c


async def test_retained_outcome_refuses_downgrade(db_session):
    f,x,s,e=await setup(db_session);await outcome(db_session,f,e,tc())
    with pytest.raises(DBAPIError,match="materials_outcome_retained_history_refuses_downgrade"):
        async with db_session.begin_nested():await migration(db_session,"downgrade")
