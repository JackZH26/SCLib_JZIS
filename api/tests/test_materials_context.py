"""Synthetic SQL contract tests; none of these rows is a scientific approval."""
import hashlib
import json
from pathlib import Path
import runpy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.materials_context_v1 import TABLE_ORDER
from services.materials_review_subject import capture_subject, capture_context_subject
from services.scientific_result_subject import ScientificSubjectError, VERSION_V3
from tests.test_research_freeze import add, seed, db_session as db_session
from tests.test_research_release_schema import release, flush_constraints
from tests.test_research_publication import actors
from services.materials_review_context import review_context, CONTEXT_VERSION
from services.research_access import ResearchAccessDenied


def quantity(**overrides):
    return {"status":"reported","raw":"0.2","relation":"exact","value":0.2,"lower":None,"upper":None,
        "unit":"1","approximate":False,"uncertainty":None, **overrides}


async def sample(db, f, **kw):
    return await add(db,"research_samples",material_id=f["material"],work_id=f["work"],source_artifact_id=f["source"],**kw)


async def composition(db, f, sid, **kw):
    return await add(db,"sample_compositions",**{"sample_id":sid,"formula_raw":"La2PrNiO7",
        "composition_basis":"unresolved","composition_schema_version":"materials-composition/1",
        "composition_payload":{"variables":[],"isotopes":[]},"source_artifact_id":f["source"],**kw})


async def protocol(db, f, **kw):
    return await add(db,"research_protocols",**{"work_id":f["work"],"method_class":"resistivity",
        "method_raw":"four-probe resistance","observable":"resistance","details_raw":None,
        "protocol_schema_version":"materials-protocol/1","parameters":[],"source_artifact_id":f["source"],**kw})


async def relation(db, f, a, b, **kw):
    return await add(db,"sample_relations",**{"from_sample_id":a,"to_sample_id":b,"relation_kind":"component_of",
        "relation_raw":"layer in film A","relation_schema_version":"materials-sample-relation/1",
        "source_artifact_id":f["source"],**kw})


async def event(db, f, sid, c=None, p=None, relations=(), **kw):
    state=await add(db,"material_states",material_id=f["material"],sample_id=sid,
        resolution="source_scoped",condition_schema_version="synthetic/1",pressure_status="not_reported",
        temperature_role="unknown",context_sha256="1"*64,source_artifact_id=f["source"])
    return await add(db,"research_events",material_id=f["material"],state_id=state["id"],
        event_type="measurement",knowledge_origin="Observed",record_sha256="2"*64,
        context={"materials_context":{"version":"materials-context/1","composition_ids":[str(c)] if c else [],
            "protocol_id":str(p) if p else None,"relation_ids":[str(x) for x in relations]}},**kw)


async def prepared(db):
    f=await seed(db)
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    s=await sample(db,f);component=await sample(db,f)
    c=await composition(db,f,s["id"]);p=await protocol(db,f);r=await relation(db,f,component["id"],s["id"])
    e=await event(db,f,s["id"],c["id"],p["id"],[r["id"]])
    claim=await add(db,"material_claims",material_id=f["material"],work_id=f["work"],paper_id=f["paper"],
        event_id=e["id"],source_snapshot_id=f["snapshot"],result_key="pending-context",interpretation_revision=1,
        source_record_hash=uuid4().hex*2,extractor_version="synthetic/1",value_relation="exact",value_kelvin=10)
    return f,s,component,c,p,r,e,claim


async def test_selected_context_closure_preserves_conflicts_without_normalization(db_session):
    f,s,component,c,p,r,e,claim=await prepared(db_session)
    first=await capture_context_subject(db_session,result_kind="claim",result_id=claim["id"])
    assert first.version==VERSION_V3 and first.sha256==hashlib.sha256(first.text.encode()).hexdigest()
    inventory={(x["table"],x["row_id"]):x["snapshot"] for x in first.data["rows"]}
    assert inventory["sample_compositions",str(c["id"])]["formula_raw"]=="La2PrNiO7"
    assert all((table,str(row["id"])) in inventory for table,row in zip(TABLE_ORDER,(c,p,r)))
    assert ("research_samples",str(component["id"])) in inventory
    assert str(f["source"]) in first.data["support_artifact_ids"]
    # A conflicting new assertion is retained, but is not silently selected.
    second=await composition(db_session,f,s["id"],formula_raw="La2PrNi2O7",composition_basis="nominal")
    revised=await composition(db_session,f,s["id"],formula_raw="La2PrNi2O7",revision=2,supersedes_id=c["id"])
    after=await capture_context_subject(db_session,result_kind="claim",result_id=claim["id"])
    assert first==after
    assert all(x["row_id"] not in {str(second["id"]),str(revised["id"])} for x in after.data["rows"])
    assert first.data["target"]["result_kind"]=="claim"
    with pytest.raises(ScientificSubjectError,match="materials_context_review_contract_required"):
        await capture_subject(db_session,result_kind="claim",result_id=claim["id"])


async def test_revision_closure_includes_previous_selected_evidence(db_session):
    f,s,component,c,p,r,e,claim=await prepared(db_session)
    c2=await composition(db_session,f,s["id"],revision=2,supersedes_id=c["id"],formula_raw="La2PrNi2O7")
    e2=await event(db_session,f,s["id"],c2["id"],p["id"],revision=2,supersedes_id=e["id"])
    prop=await add(db_session,"event_properties",event_id=e2["id"],property_key="band_gap",relation="exact",
        value=0,unit="eV",record_sha256="3"*64)
    data=(await capture_context_subject(db_session,result_kind="property",result_id=prop["id"])).data
    ids={(x["table"],x["row_id"]) for x in data["rows"]}
    assert {("sample_compositions",str(x["id"])) for x in (c,c2)}<=ids
    assert ("research_events",str(e["id"])) in ids
    assert data["target"]["result_kind"]=="property"


@pytest.mark.parametrize("change",["null","extra","unknown_basis","bad_quantity","bad_isotope","unresolved_value","duplicate_variable"])
async def test_malformed_composition_refused(db_session,change):
    f=await seed(db_session);s=await sample(db_session,f);payload={"variables":[],"isotopes":[]};kw={}
    if change=="null":payload=None
    if change=="extra":payload["normalized_formula"]="invented"
    if change=="unknown_basis":kw["composition_basis"]="inferred"
    if change=="bad_quantity":payload["variables"]=[{"symbol":"x","site":None,"basis":"nominal","amount":quantity(value=None)}]
    if change=="bad_isotope":payload["isotopes"]=[{"element":"O","mass_number":18,"fraction":quantity(value=1.2)}]
    if change=="unresolved_value":payload["variables"]=[{"symbol":"x","site":None,"basis":"unresolved","amount":quantity(status="unresolved")}]
    if change=="duplicate_variable":payload["variables"]=[{"symbol":"x","site":None,"basis":"nominal","amount":quantity()}]*2
    with pytest.raises(DBAPIError,match="materials_composition_contract"):
        async with db_session.begin_nested():await composition(db_session,f,s["id"],composition_payload=payload,**kw)


async def test_sparse_measured_variables_uncertainties_and_unknowns_survive(db_session):
    f=await seed(db_session);s=await sample(db_session,f)
    payload={"variables":[{"symbol":"δ","site":"oxygen site","basis":"measured","amount":quantity(
        raw="δ = 0.20 ± 0.02",uncertainty={"kind":"reported_unspecified","minus":0.02,"plus":0.02,"level":None,"raw":"± 0.02"})}],
        "isotopes":[{"element":"O","mass_number":18,"fraction":quantity(raw="80–90%",relation="interval",value=None,lower=80,upper=90,unit="%")}]}
    row=await composition(db_session,f,s["id"],composition_payload=payload,composition_basis="measured")
    assert row["composition_payload"]==payload and len(row["record_sha256"])==64
    stored=await db_session.scalar(sa.text("SELECT to_jsonb(t) FROM sample_compositions t WHERE id=:id"),{"id":row["id"]})
    digest=await db_session.scalar(sa.text("SELECT sclib_scientific_adjudication_record_hash_v1(CAST(:body AS jsonb))"),{"body":json.dumps(stored)})
    assert digest==row["record_sha256"]


@pytest.mark.parametrize("change",["criterion","null","missing_method","bad_version","wrong_unit"])
async def test_protocol_does_not_own_result_criteria(db_session,change):
    f=await seed(db_session);kw={}
    if change=="criterion":kw["parameters"]=[{"kind":"resistance_fraction","name_raw":"90%","quantity":quantity(value=90,unit="%")}]
    if change=="null":kw["parameters"]=None
    if change=="missing_method":kw["method_raw"]=None
    if change=="bad_version":kw["protocol_schema_version"]="new"
    if change=="wrong_unit":kw["parameters"]=[{"kind":"frequency","name_raw":"frequency","quantity":quantity(unit="K")}]
    with pytest.raises(DBAPIError,match="materials_protocol_contract"):
        async with db_session.begin_nested():await protocol(db_session,f,**kw)
    unknown=await protocol(db_session,f,method_class="unspecified",method_raw=None)
    assert unknown["method_raw"] is None


@pytest.mark.parametrize("table",TABLE_ORDER)
@pytest.mark.parametrize("operation",["update","delete","truncate"])
async def test_context_history_is_append_only(db_session,table,operation):
    f,s,component,c,p,r,e,claim=await prepared(db_session)
    with pytest.raises(DBAPIError,match="materials_context_history_is_append_only"):
        async with db_session.begin_nested():
            sql=f"UPDATE {table} SET record_sha256=record_sha256" if operation=="update" else f"DELETE FROM {table}" if operation=="delete" else f"TRUNCATE {table} CASCADE"
            await db_session.execute(sa.text(sql))


@pytest.mark.parametrize("case",["sample","work","relation_missing","disconnected"])
async def test_wrong_owner_cannot_be_bound(db_session,case):
    f,s,component,c,p,r,e,claim=await prepared(db_session);other=await sample(db_session,f)
    c_id,p_id,rels=c["id"],p["id"],[r["id"]]
    if case=="sample":c_id=(await composition(db_session,f,other["id"]))["id"]
    if case=="work":
        work=await add(db_session,"works",canonical_title="Other study")
        p_id=(await protocol(db_session,f,work_id=work["id"]))["id"]
    if case=="relation_missing":rels=[uuid4()]
    if case=="disconnected":
        more=await sample(db_session,f);rels=[(await relation(db_session,f,other["id"],more["id"]))["id"]]
    with pytest.raises(DBAPIError,match="materials_context_"):
        async with db_session.begin_nested():await event(db_session,f,s["id"],c_id,p_id,rels)


async def test_revision_owner_branch_and_cycle_guards(db_session):
    f,s,component,c,p,r,e,claim=await prepared(db_session)
    for kw in ({"revision":3,"supersedes_id":c["id"]},{"revision":2,"supersedes_id":p["id"]}):
        with pytest.raises(DBAPIError,match="materials_context_revision_owner_mismatch"):
            async with db_session.begin_nested():await composition(db_session,f,s["id"],**kw)
    await composition(db_session,f,s["id"],revision=2,supersedes_id=c["id"])
    with pytest.raises(DBAPIError,match="successor"):
        async with db_session.begin_nested():await composition(db_session,f,s["id"],revision=2,supersedes_id=c["id"])
    with pytest.raises(DBAPIError,match="materials_component_cycle"):
        async with db_session.begin_nested():await relation(db_session,f,s["id"],component["id"])


@pytest.mark.parametrize("table",["research_samples","material_states","research_events"])
async def test_context_owners_require_new_revision(db_session,table):
    f,s,component,c,p,r,e,claim=await prepared(db_session)
    field,value,key=("sample_label","changed",s["id"]) if table=="research_samples" else ("pressure_status","ambiguous",e["state_id"]) if table=="material_states" else ("context",{},e["id"])
    t=Base.metadata.tables[table]
    with pytest.raises(DBAPIError,match="materials_context_.*revision"):
        async with db_session.begin_nested():await db_session.execute(t.update().where(t.c.id==key).values(**{field:value}))


async def test_old_subject_writer_and_release_refuse_partial_context(db_session):
    f,s,component,c,p,r,e,claim=await prepared(db_session)
    body=await db_session.scalar(sa.text("SELECT sclib_scientific_subject_capture_v2('claim',:id)"),{"id":claim["id"]})
    with pytest.raises(DBAPIError,match="materials_context_review_contract_required"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("INSERT INTO scientific_result_subjects(basis_json) VALUES(:body)"),{"body":body})
    # Only the new event is used; no result-semantics guard masks this boundary.
    fixture={"dataset":{"id":f["args"]["dataset_id"]}}
    with pytest.raises(DBAPIError,match="materials_context_release_contract_required"):
        async with db_session.begin_nested():await release(db_session,fixture,[("research_events",e["id"])])


async def migrate(db,direction):
    module=runpy.run_path(str(Path(__file__).parents[1]/"alembic/versions/0096_materials_context.py"))
    connection=await db.connection()
    def run(conn):
        with Operations.context(MigrationContext.configure(conn)):module[direction]()
    await connection.run_sync(run)


async def test_empty_downgrade_upgrade_preserves_legacy_rows(db_session):
    f=await seed(db_session)
    await db_session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    await db_session.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    before=await capture_subject(db_session,result_kind="claim",result_id=f["claim"])
    await flush_constraints(db_session)
    await migrate(db_session,"downgrade");await migrate(db_session,"upgrade")
    assert before==await capture_subject(db_session,result_kind="claim",result_id=f["claim"])
    assert (await capture_context_subject(db_session,result_kind="claim",result_id=f["claim"])).data["target"]==before.data["target"]


async def test_retained_context_refuses_downgrade_and_reserved_collision(db_session):
    f=await seed(db_session);s=await sample(db_session,f);await composition(db_session,f,s["id"])
    with pytest.raises(DBAPIError,match="materials_context_retained_history_refuses_downgrade"):
        async with db_session.begin_nested():await migrate(db_session,"downgrade")


async def test_reserved_collision_refuses_upgrade(db_session):
    f=await seed(db_session);await flush_constraints(db_session);await migrate(db_session,"downgrade")
    t=Base.metadata.tables["research_events"]
    await db_session.execute(t.update().where(t.c.id==f["event"]).values(context={"materials_context":{"legacy":"unregistered"}}))
    with pytest.raises(DBAPIError,match="materials_context_reserved_member_collision"):
        async with db_session.begin_nested():await migrate(db_session,"upgrade")


async def test_context_read_service_pins_selection_without_disclosing_raw_source(db_session):
    f,s,component,c,p,r,e,claim=await prepared(db_session);people=await actors(db_session)
    args=dict(result_kind="claim",result_id=claim["id"])
    value=await review_context(db_session,actor_user_id=people["reviewer"],**args)
    assert value["version"]==CONTEXT_VERSION and not any(value["authority"].values())
    ctx=value["scientific_context"]
    assert ctx["selection"]["composition_ids"]==[str(c["id"])]
    assert ctx["compositions"][0]["composition_basis"]=="unresolved"
    assert ctx["protocol"]["method_class"]=="resistivity"
    assert ctx["sample_relations"][0]["from_sample_id"]==str(component["id"])
    assert not value["source_text_disclosed"] and "four-probe" not in str(value) and "La2PrNiO7" not in str(value)
    with pytest.raises(ResearchAccessDenied):await review_context(db_session,actor_user_id=people["member"],**args)


async def test_dependency_context_is_included_even_when_root_is_legacy(db_session):
    f,s,component,c,p,r,e,claim=await prepared(db_session)
    await add(db_session,"event_evidence",event_id=f["event"],input_event_id=e["id"],input_claim_id=claim["id"],link_type="derives_from")
    args=dict(result_kind="claim",result_id=f["claim"])
    with pytest.raises(ScientificSubjectError,match="materials_context_review_contract_required"):
        await capture_subject(db_session,**args)
    subject=await capture_context_subject(db_session,**args)
    assert ("sample_compositions",str(c["id"])) in {(x["table"],x["row_id"]) for x in subject.data["rows"]}
    people=await actors(db_session)
    value=await review_context(db_session,actor_user_id=people["reviewer"],**args)
    assert value["scientific_context"]["selection"] is None
    assert value["scientific_context"]["compositions"]==[]


@pytest.mark.parametrize("change",["null","missing_key","extra_key","duplicate","unknown_version","bad_uuid","empty"])
async def test_event_context_has_a_closed_nonempty_shape(db_session,change):
    f,s,component,c,p,r,e,claim=await prepared(db_session)
    j={"version":"materials-context/1","composition_ids":[str(c["id"])],"protocol_id":None,"relation_ids":[]}
    if change=="null":j=None
    if change=="missing_key":del j["protocol_id"]
    if change=="extra_key":j["extra"]="unregistered"
    if change=="duplicate":j["composition_ids"]*=2
    if change=="unknown_version":j["version"]="future"
    if change=="bad_uuid":j["composition_ids"]=["not-a-uuid"]
    if change=="empty":j["composition_ids"]=[]
    with pytest.raises(DBAPIError,match="materials_event_context_contract"):
        async with db_session.begin_nested():await add(db_session,"research_events",material_id=f["material"],state_id=e["state_id"],
            event_type="measurement",knowledge_origin="Observed",record_sha256="2"*64,context={"materials_context":j})


async def test_only_literature_artifacts_can_ground_context(db_session):
    f=await seed(db_session);s=await sample(db_session,f)
    policy=await add(db_session,"evidence_artifacts",kind="policy",schema_version="synthetic/1",source="synthetic",
        record_sha256="0"*64,hash_status="not_applicable",access="unknown")
    with pytest.raises(DBAPIError,match="materials_context_literature_source_required"):
        async with db_session.begin_nested():await composition(db_session,f,s["id"],source_artifact_id=policy["id"])


async def test_unused_new_event_still_retains_immutable_context(db_session):
    f=await seed(db_session);s=await sample(db_session,f);c=await composition(db_session,f,s["id"])
    e=await event(db_session,f,s["id"],c["id"])
    with pytest.raises(DBAPIError,match="materials_context_requires_new_event_revision"):
        async with db_session.begin_nested():await db_session.execute(sa.text("DELETE FROM research_events WHERE id=:id"),{"id":e["id"]})


async def test_historical_inventory_comparison_may_only_omit_empty_context_tables(db_session):
    from migration_revision_scope import pre_materials_context_tables
    connection=await db_session.connection()
    names=["materials",*TABLE_ORDER]
    assert await connection.run_sync(lambda conn:pre_materials_context_tables(conn,names))==["materials"]
    f=await seed(db_session);s=await sample(db_session,f);await composition(db_session,f,s["id"])
    with pytest.raises(AssertionError,match="Retained Materials context"):
        await connection.run_sync(lambda conn:pre_materials_context_tables(conn,names))
