"""Owned disposable PostgreSQL; source-shaped values in synthetic identities."""
from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from alembic.migration import MigrationContext
from alembic.operations import Operations

from models.materials_device_descriptors_v3 import VERSION, DEFINITION_VERSION
from services.materials_review_context import review_context, DEVICE_DESCRIPTORS_VERSION
from services.materials_review_subject import capture_context_subject
from tests.test_research_freeze import db_session as db_session, seed
from tests.test_materials_context import sample, quantity
from tests.test_materials_conditions import state, event, claim, condition, payload, LINK_VERSION
from tests.test_materials_claim_outcomes import tc
from tests.test_materials_result_definitions import semantics
from tests.test_research_publication import actors

CASE=json.loads((Path(__file__).parents[2]/'ingestion/tests/fixtures/materials_ner_device_descriptors_source_case.json').read_bytes())


def angle():
    c=condition('angle','twist_angle','sample_geometry',value=1.27,unit='°',raw=r'\sim$1.27$^{\circ}',approximate=True)
    c['basis_raw']=CASE['twist']['quote'];return c


def displacement():
    c=condition('D','reported_displacement_field','measurement',value=.61,unit='V/nm',raw='+0.61')
    c['basis_raw']=CASE['displacement']['quote'];return c


def definition():
    d=semantics('linear_fit_intersection',target='claim');d['version']=DEFINITION_VERSION
    d['definition']['criterion_raw']=CASE['criterion'];return d


async def fixture(db,items=None):
    f=await seed(db)
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    x=await sample(db,f)
    s=await state(db,f,x['id'],payload([angle()] if items is None else items),condition_schema_version=VERSION)
    e=await event(db,f,s)
    return f,x,s,e


async def migrate(db,direction):
    m=runpy.run_path(str(Path(__file__).parents[1]/'alembic/versions/0104_materials_device_context.py'))
    conn=await db.connection()
    def apply(c):
        with Operations.context(MigrationContext.configure(c)):m[direction]()
    await conn.run_sync(apply)


async def test_source_values_roundtrip_state_definition_subject_and_private_api(db_session):
    f,x,s,e=await fixture(db_session)
    meta=dict(state_semantics=dict(version=LINK_VERSION),materials_outcome=tc(quantity(raw='3.1 K',value=3.1,unit='K',approximate=True)),result_semantics=definition())
    c=await claim(db_session,f,e,extraction_metadata=meta)
    assert c['tc_definition']=='linear_fit_intersection' and c['value_kelvin']==3.1
    assert s['conditions']['items']==[angle()] and s['pressure_gpa'] is c['pressure_gpa'] is None
    subject=await capture_context_subject(db_session,result_kind='claim',result_id=c['id'])
    snap=next(r['snapshot'] for r in subject.data['rows'] if r['table']=='material_states')
    assert snap['conditions']==s['conditions']
    people=await actors(db_session)
    view=await review_context(db_session,actor_user_id=people['reviewer'],result_kind='claim',result_id=c['id'])
    assert view['version']==DEVICE_DESCRIPTORS_VERSION and not any(view['authority'].values())
    assert view['state']['conditions']['items'][0]['quantity']['value']==1.27
    assert view['result']['definition']['criterion']=='linear_fit_intersection'
    # D1 field scans are a separate state, never attached to this D2 Tc by value alone.
    other_sample=await sample(db_session,f)
    other=await state(db_session,f,other_sample['id'],payload([displacement()]),condition_schema_version=VERSION)
    assert other['id']!=s['id'] and other['conditions']['items']==[displacement()]


async def test_reported_displacement_has_no_inferred_canonical_scalar(db_session):
    f,x,s,e=await fixture(db_session,[displacement()]);c=await claim(db_session,f,e)
    people=await actors(db_session)
    view=await review_context(db_session,actor_user_id=people['reviewer'],result_kind='claim',result_id=c['id'])
    d=view['state']['conditions']['items'][0]
    assert d['quantity']['value']==.61 and d['quantity']['unit']=='V/nm'
    assert d['normalized_quantity'] is None and d['field_convention']=='unresolved'
    assert d['task_exclusions']==['displacement_field_convention_unresolved']
    with pytest.raises(DBAPIError,match='displacement_field_convention_unresolved'):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SELECT sclib_materials_condition_number_v3('reported_displacement_field',CAST(:q AS jsonb),'value')"),{'q':json.dumps(displacement()['quantity'])})


@pytest.mark.parametrize('change',['unit','basis','extra','pressure_selector','temperature_selector','duplicate_id'])
async def test_invalid_descriptor_payload_cannot_enter_state(db_session,change):
    body=payload([angle(),displacement()])
    if change=='unit':body['items'][1]['quantity']['unit']='V'
    if change=='basis':body['items'][0]['basis_raw']=None
    if change=='extra':body['items'][0]['unreviewed_convention']='SI'
    if change=='duplicate_id':body['items'][1]['id']='angle'
    if change=='pressure_selector':body['pressure'].update(availability='reported',condition_id='angle')
    if change=='temperature_selector':body['temperature_condition_id']='angle'
    f=await seed(db_session);x=await sample(db_session,f)
    with pytest.raises(DBAPIError,match='materials_state_condition_contract'):
        async with db_session.begin_nested():await state(db_session,f,x['id'],body,condition_schema_version=VERSION)


async def test_new_criterion_does_not_change_old_validator_or_admit_missing_definition(db_session):
    d=definition()
    for version,expected in [('materials-result-semantics/1',False),(DEFINITION_VERSION,True)]:
        d['version']=version
        row=(await db_session.execute(sa.text("SELECT sclib_materials_result_semantics_v1(CAST(:d AS jsonb),'claim'), sclib_materials_result_semantics_v2(CAST(:d AS jsonb),'claim')"),{'d':json.dumps(d)})).one()
        assert row[0] is False and row[1] is expected
    d['definition']['criterion_raw']=None
    assert (await db_session.execute(sa.text("SELECT sclib_materials_result_semantics_v2(CAST(:d AS jsonb),'claim')"),{'d':json.dumps(d)})).scalar() is False


async def test_empty_upgrade_downgrade_and_retained_history_gate(db_session):
    await migrate(db_session,'downgrade');await migrate(db_session,'upgrade')
    f,x,s,e=await fixture(db_session)
    with pytest.raises(DBAPIError,match='retained_history_refuses_downgrade'):
        async with db_session.begin_nested():await migrate(db_session,'downgrade')
    with pytest.raises(DBAPIError,match='materials_state_history_is_immutable'):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("UPDATE material_states SET condition_schema_version='legacy' WHERE id=:id"),{'id':s['id']})
