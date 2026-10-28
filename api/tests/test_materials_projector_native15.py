"""Synthetic /15 pipeline on owned disposable PostgreSQL; no scientific data."""
from copy import deepcopy
from datetime import datetime, timezone
import csv
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest
import sqlalchemy as sa

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ingestion'),str(ROOT/'ingestion/tests'),str(ROOT/'scripts')]
from test_materials_ner_projector_native15 import native15_case, synthetic_packet, synthetic_amendment
from ingestion.materials_ner.review_amendments import review_mapping
import materials_ner_amendment_bridge as bridge
from services import materials_proposal_review as review, materials_proposal_export as export
from services import materials_proposal_amendments as amendments
from models import materials_ner_proposals_v1 as proposal_schema, materials_ner_proposals_v2 as relation_schema
from models import materials_ner_amendments_v1 as amendment_schema
from tests.test_research_freeze import db_session as db_session, state as snapshot
from tests.test_research_publication import actors


@pytest.fixture
def native15_packet(native15_case,tmp_path):
    parent,_=synthetic_packet(native15_case,tmp_path)
    a=synthetic_amendment(parent)
    return parent,a,review_mapping(a)


def test_native15_export_keeps_roles_units_and_definition(native15_packet):
    p,a,m=native15_packet;before=deepcopy(p)
    descriptor,raw=export.package(p,datetime(2026,10,26,tzinfo=timezone.utc))
    assert descriptor['version']==export.DEVICE_VERSION and p==before
    with ZipFile(io.BytesIO(raw)) as z:
        row=next(csv.DictReader(io.StringIO(z.read('results.csv').decode())))
        assert z.read('raw-model-graph.json')==p['raw_output'].encode()
        conditions=p['receipt']['extraction']['states'][0]['conditions']
        assert json.loads(row['state_conditions_json'])==conditions
        assert json.loads(row['measurement_conditions_json'])==[conditions[1]]
        assert row['criterion']=='linear_fit_intersection'
        assert json.loads(row['pressure_declaration_json'])['regime']=='unknown'
    raw,_=amendments.export(a,m);row=next(csv.DictReader(io.StringIO(raw.decode())))
    assert json.loads(row['conditions_json'])==conditions
    assert json.loads(row['definition_json'])==a['graph']['results'][0]['definition']
    assert 'canonical_result_mapping_required' in json.loads(row['holds_json'])


@pytest.mark.parametrize('mutation',['registry','validator','semantics','definition','admission'])
def test_native15_mixed_versions_and_coercion_are_rejected(native15_packet,mutation):
    _,a,m=deepcopy(native15_packet)
    if mutation=='registry':a['validation']['registry_version']='materials-quantities/3.0.0'
    elif mutation=='validator':a['validation']['validator_version']='materials-ner-validation/1.26.0'
    elif mutation=='semantics':m['records'][0]['result_semantics']['version']='materials-result-semantics/1'
    elif mutation=='definition':m['records'][0]['result_semantics']['definition']['criterion']='onset'
    else:m['records'][0]['scientific_acceptance']=True
    with pytest.raises(review.ProposalIntegrityError):amendments.export(a,m)


async def test_native15_postgres_idempotency_private_read_and_export(native15_packet,db_session,record_property):
    parent,a,m=native15_packet
    await db_session.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    await db_session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    people=await actors(db_session);before=await snapshot(db_session)
    connection=await db_session.connection()
    if (await connection.execute(sa.text("SELECT to_regclass('materials_ner_v1.schema_version')"))).scalar() is None:
        for statement in proposal_schema.initialize_statements():
            await connection.execute(sa.text(statement))
    for schema in (relation_schema,amendment_schema):
        await connection.run_sync(schema.upgrade)
    first=await bridge.apply(connection,parent,a);second=await bridge.apply(connection,parent,a)
    assert first['inserted'] and not second['inserted']
    assert all(first[k] is False for k in ['scientific_acceptance','ml_training_eligible','canonical_writes'])
    detail=await review.run_detail(db_session,people['reviewer'],parent['run_id'])
    listing=await amendments.list_for_run(db_session,people['reviewer'],parent['run_id'])
    dto=await amendments.detail(db_session,people['reviewer'],parent['run_id'],a['amendment_id'])
    assert dto['amendment']==a and dto['mapping']==m
    assert detail['run']['extraction_version']=='materials-ner/15'
    assert detail['entities']['states'][0]['payload']['conditions']==a['graph']['states'][0]['conditions']
    assert await snapshot(db_session)==before
    with pytest.raises(review.ProposalUnavailable,match='canonical_result_mapping_unavailable'):
        await amendments.canonical_targets(db_session,people['reviewer'],parent['run_id'],a['amendment_id'],'r')
    # Standard pytest report channel; the disposable runner keeps its environment allowlist.
    record_property('native15_review_capture',json.dumps(dict(
        authorship='Synthetic test provider and synthetic source only',detail=detail,
        summary=listing['items'][0],dto=dto),ensure_ascii=False,sort_keys=True))
