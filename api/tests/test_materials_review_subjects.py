"""Exact Tc/property evidence snapshots on owned disposable PostgreSQL.

All scientific assertions are synthetic fixtures. Passing these checks does
not constitute an independent paper read or an actual review decision.
"""
import hashlib
import json
from pathlib import Path
import runpy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from services import materials_review_subject as subject
from services import scientific_result_subject as legacy
from services.research_release_manifest import canonical
from services.source_registry import import_source_provenance_bundle
from tests.test_research_freeze import add, seed, state
from tests.test_research_freeze import db_session as db_session
from tests.test_source_registry import bundle as source_bundle
from tests.test_scientific_result_dossier import prepared
from tests.test_materials_result_definitions import semantics


async def claim_fixture(db):
    fixture=await seed(db)
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await add(db,"paper_work_map",paper_id=fixture["paper"],work_id=fixture["work"],
        relation_type="preprint",match_method="manual",review_status="accepted")
    data=source_bundle(fixture["paper"],fixture["work"],fixture["claim"])
    await import_source_provenance_bundle(db,data,dry_run=False)
    return fixture,data


async def capture(db,fixture,**kwargs):
    return await subject.capture_subject(db,result_kind="claim",result_id=fixture["claim"],**kwargs)


async def test_claim_subject_captures_exact_sources_and_never_creates_a_property_or_decision(db_session):
    fixture,provenance=await claim_fixture(db_session);before=await state(db_session)
    first=await capture(db_session,fixture)
    actual=await db_session.scalar(sa.text("SELECT sclib_scientific_subject_capture_v2('claim',:id)"),{"id":fixture["claim"]})
    assert first.text==actual and first.sha256==hashlib.sha256(actual.encode()).hexdigest()
    rows={(r["table"],r["row_id"]):r["snapshot"] for r in first.data["rows"]}
    assert rows["material_claims",str(fixture["claim"])]["value_kelvin"]==39
    assert ("event_properties",str(fixture["children"]["property"])) not in rows
    assert ("material_claims",str(fixture["children"]["sibling_claim"])) not in rows
    for table in ("source_revisions","source_captures","claim_source_occurrences"):
        assert (table,provenance[table][0]["id"]) in rows
    assert first.data["target"]["result_kind"]=="claim" and first.data["target"]["result_id"]==str(fixture["claim"])
    assert first.data["target"]["native_outcome_id"] is None
    assert first==await capture(db_session,fixture) and await state(db_session)==before
    value=first.data;value["rows"].clear();assert first.data["rows"]


async def test_same_uuid_in_different_result_tables_never_aliases_subject_identity(db_session):
    fixture,_=await claim_fixture(db_session)
    await add(db_session,"event_properties",id=fixture["claim"],event_id=fixture["event"],property_key="band_gap",
        component_key="typed-result",relation="exact",value=2,unit="eV",record_sha256="e"*64)
    claim=await capture(db_session,fixture)
    prop=await subject.capture_subject(db_session,result_kind="property",result_id=fixture["claim"])
    assert claim.subject_id!=prop.subject_id and claim.result_row_sha256!=prop.result_row_sha256
    assert claim.data["target"]["result_kind"]=="claim" and prop.data["target"]["result_kind"]=="property"


@pytest.mark.parametrize("change",["value","definition","state","source_raw","source_occurrence"])
async def test_scientific_change_changes_exact_subject_pin(db_session,change):
    fixture,_=await claim_fixture(db_session);before=await capture(db_session,fixture)
    claims=Base.metadata.tables["material_claims"]
    if change=="value":
        await db_session.execute(claims.update().where(claims.c.id==fixture["claim"]).values(value_kelvin=38))
    elif change=="definition":
        await db_session.execute(claims.update().where(claims.c.id==fixture["claim"]).values(
            tc_definition="zero_resistance",extraction_metadata={"result_semantics":semantics("zero_resistance",target="claim")}))
    elif change=="state":
        states=Base.metadata.tables["material_states"]
        await db_session.execute(states.update().where(states.c.id==fixture["state"]).values(conditions={"reported":"changed source context"}))
    elif change=="source_raw":
        await db_session.execute(claims.update().where(claims.c.id==fixture["claim"]).values(raw_record={"raw":"PRIVATE_EXACT_CLAIM_SOURCE"}))
    else:
        data=source_bundle(fixture["paper"],fixture["work"],fixture["claim"])
        data["source_revisions"][0].update(revision_key="arxiv-v3",provider_revision="v3")
        data["claim_source_occurrences"][0]["occurrence_key"]="new-source-version"
        await import_source_provenance_bundle(db_session,data,dry_run=False)
    after=await capture(db_session,fixture)
    assert after.sha256!=before.sha256 and after.subject_id!=before.subject_id


async def test_sibling_claim_does_not_change_subject_unless_an_explicit_dependency_reaches_it(db_session):
    fixture,_=await claim_fixture(db_session);before=await capture(db_session,fixture)
    claims=Base.metadata.tables["material_claims"];sibling=fixture["children"]["sibling_claim"]
    await db_session.execute(claims.update().where(claims.c.id==sibling).values(value_upper_kelvin=17))
    assert before==await capture(db_session,fixture)
    # A source dependency is intentionally captured, not inferred from equal formulas.
    upstream=await seed(db_session,with_children=False)
    await add(db_session,"event_evidence",event_id=fixture["event"],link_type="derives_from",
        input_event_id=upstream["event"],input_claim_id=upstream["claim"],locator={})
    after=await capture(db_session,fixture)
    assert after.sha256!=before.sha256
    assert any(r["table"]=="material_claims" and r["row_id"]==str(upstream["claim"]) for r in after.data["rows"])


async def test_native_property_v1_bytes_and_ancestry_are_preserved(db_session):
    _,ids=await prepared(db_session)
    old=await legacy.capture_result_subject(db_session,ids["property"])
    new=await subject.capture_subject(db_session,result_kind="property",result_id=ids["property"])
    assert new.data["rows"]==old.data["rows"] and new.data["native_import"]==old.data["native_import"]
    assert new.result_row_sha256==old.property_row_sha256 and new.subject_id!=old.subject_id
    assert old==await legacy.capture_result_subject(db_session,ids["property"])


@pytest.mark.parametrize("kind,key",[("event",str(uuid4())),("claim",None),(None,str(uuid4())),("claim",True)])
async def test_invalid_typed_target_fails_before_database_access(kind,key):
    with pytest.raises(legacy.ScientificSubjectError):
        await subject.capture_subject(None,result_kind=kind,result_id=key)


async def test_unassigned_legacy_claim_is_not_silently_linked_to_a_material_event(db_session):
    fixture,_=await claim_fixture(db_session)
    claims=Base.metadata.tables["material_claims"]
    fresh=await add(db_session,"material_claims",material_id=fixture["material"],
        source_snapshot_id=fixture["snapshot"],source_record_hash=uuid4().hex*2,extractor_version="synthetic-unassigned")
    fixture=dict(fixture,claim=fresh["id"])
    with pytest.raises(legacy.ScientificSubjectUnavailable):
        async with db_session.begin_nested():await capture(db_session,fixture)


@pytest.mark.parametrize("change",["kind","result_id","event_id","version","claim_material"])
async def test_detached_snapshot_parser_rejects_target_substitution(db_session,change):
    fixture,_=await claim_fixture(db_session);body=(await capture(db_session,fixture)).data
    if change=="kind":body["target"]["result_kind"]="property"
    elif change in {"result_id","event_id"}:body["target"][change]=str(uuid4())
    elif change=="version":body["version"]=legacy.VERSION
    else:
        next(r for r in body["rows"] if r["table"]=="material_claims" and r["row_id"]==str(fixture["claim"]))["snapshot"]["material_id"]="another-material"
    with pytest.raises(legacy.ScientificSubjectError):legacy._json(canonical(body).decode(),version=subject.VERSION)


async def test_migration_roundtrip_preserves_every_stored_row_and_legacy_subject(db_session):
    fixture,_=await claim_fixture(db_session);old=await legacy.capture_result_subject(db_session,fixture["children"]["property"])
    new=await capture(db_session,fixture);before=await state(db_session)
    module=runpy.run_path(str(Path(__file__).parents[1]/"alembic/versions/0094_materials_review_subjects.py"))
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    conn=await db_session.connection()
    def apply(connection,action):
        with Operations.context(MigrationContext.configure(connection)):module[action]()
    await conn.run_sync(lambda c:apply(c,"downgrade"))
    assert await legacy.capture_result_subject(db_session,fixture["children"]["property"])==old
    assert await db_session.scalar(sa.text("SELECT to_regprocedure('sclib_scientific_subject_capture_v2(text,uuid)')")) is None
    await conn.run_sync(lambda c:apply(c,"upgrade"))
    assert await capture(db_session,fixture)==new and await state(db_session)==before


async def test_non_detection_keeps_missing_tc_and_window_information_unknown(db_session):
    fixture,_=await claim_fixture(db_session)
    row=await add(db_session,"material_claims",material_id=fixture["material"],source_snapshot_id=fixture["snapshot"],
        event_id=fixture["event"],result_key="explicit-non-detection",interpretation_revision=1,
        property_type="non_transition",result_status="not_detected",value_relation="unreported",
        source_record_hash=uuid4().hex*2,extractor_version="synthetic-non-detection")
    data=(await capture(db_session,dict(fixture,claim=row["id"]))).data
    claim=next(r["snapshot"] for r in data["rows"] if r["table"]=="material_claims" and r["row_id"]==str(row["id"]))
    assert claim["value_kelvin"] is None and claim["minimum_temperature_k"] is None
    assert claim["result_status"]=="not_detected" and claim["pressure_state"]=="not_reported"
