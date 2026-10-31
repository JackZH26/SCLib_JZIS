"""Canonical v2 conditions on disposable PostgreSQL; synthetic, not Gold."""
from copy import deepcopy
from pathlib import Path
import runpy

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.materials_conditions_v2 import VERSION
from models.materials_conditions_adoption_v2 import historical_triggers
from services.materials_review_context import review_context, REPORTED_FIELD_VERSION
from services.materials_review_subject import capture_subject, capture_context_subject
from services.scientific_result_subject import ScientificSubjectError
from tests.test_research_freeze import seed, db_session as db_session
from tests.test_research_release_schema import flush_constraints, release
from tests.test_research_publication import actors
from tests.test_materials_context import sample, protocol, composition, quantity
from tests.test_materials_conditions import state, event, claim, condition, payload, thickness
from tests.test_materials_conditions_v2 import field
from tests.test_materials_claim_outcomes import outcome, tc, negative, window
from tests.test_materials_observation_outcomes import observation, negative as device_negative


async def fixture(db, body=None, *, with_method=False):
    f=await seed(db)
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    x=await sample(db,f)
    s=await state(db,f,x['id'],body or payload([field()]),condition_schema_version=VERSION)
    p=await protocol(db,f) if with_method else None
    e=await event(db,f,s,p)
    return f,x,s,e


async def migrate(db, direction):
    module=runpy.run_path(str(Path(__file__).parents[1]/'alembic/versions/0101_materials_conditions_v2.py'))
    connection=await db.connection()
    def run(conn):
        with Operations.context(MigrationContext.configure(conn)):module[direction]()
    await connection.run_sync(run)


async def test_actual_state_claim_and_private_projection_preserve_unresolved_field(db_session):
    f,x,s,e=await fixture(db_session);c=await outcome(db_session,f,e,tc())
    assert s['conditions']==payload([field()])
    assert s['pressure_gpa'] is c['pressure_gpa'] is None
    assert c['value_kelvin']==6.61 and c['measurement_method'] is None
    assert s['context_sha256']!='0'*64
    subject=await capture_context_subject(db_session,result_kind='claim',result_id=c['id'])
    root=next(v['snapshot'] for v in subject.data['rows'] if v['table']=='material_states' and v['row_id']==str(s['id']))
    assert root['conditions']==s['conditions'] and root['condition_schema_version']==VERSION
    people=await actors(db_session)
    view=await review_context(db_session,actor_user_id=people['reviewer'],result_kind='claim',result_id=c['id'])
    assert view['version']==REPORTED_FIELD_VERSION and not any(view['authority'].values())
    item=view['state']['conditions']['items'][0]
    assert item['field_convention']=='unresolved' and item['normalized_quantity'] is None
    assert item['quantity']['value']==9 and item['quantity']['unit']=='T'
    assert item['source_context']['basis_raw']=={'availability':'retained','disclosed':False}
    assert item['source_context']['orientation_raw']=={'availability':'retained','disclosed':False}
    assert view['state']['condition_evidence']['context_sha256']==s['context_sha256']
    assert '$H$' not in str(view) and not view['source_text_disclosed']
    with pytest.raises(ScientificSubjectError,match='materials_conditions_review_contract_required'):
        await capture_subject(db_session,result_kind='claim',result_id=c['id'])


@pytest.mark.parametrize('availability',['not_reported','not_extracted','not_accessible','ambiguous','conflicted','not_applicable'])
async def test_v2_unknown_pressure_remains_null(db_session,availability):
    f,x,s,e=await fixture(db_session,payload([field()],availability=availability))
    c=await claim(db_session,f,e,pressure_state='explicit_ambient',pressure_gpa=0)
    assert s['pressure_status']==c['pressure_state']==availability
    assert s['pressure_gpa'] is c['pressure_gpa'] is None


async def test_v2_ambient_and_temperature_interval_do_not_create_zero_or_midpoint(db_session):
    t=condition('T','temperature','study_extent',raw='1.75 to 100 K',unit='K',value=None,lower=1.75,upper=100,relation='interval')
    f,x,s,e=await fixture(db_session,payload([field(),t],availability='reported',regime='explicit_ambient',basis='ambient pressure'))
    c=await claim(db_session,f,e)
    assert s['pressure_status']==c['pressure_state']=='explicit_ambient'
    assert s['pressure_gpa'] is s['temperature_k'] is c['pressure_gpa'] is None
    assert s['conditions']['items'][1]==t


@pytest.mark.parametrize('operation',['state_update','state_delete','state_relabel','event_update','event_delete','claim_unlink'])
async def test_v2_history_cannot_be_relabelled_or_rebound(db_session,operation):
    f,x,s,e=await fixture(db_session);c=await claim(db_session,f,e)
    statements={
        'state_update':('UPDATE material_states SET conditions=\'{}\'::jsonb WHERE id=:id',s['id']),
        'state_delete':('DELETE FROM material_states WHERE id=:id',s['id']),
        'state_relabel':("UPDATE material_states SET condition_schema_version='legacy' WHERE id=:id",s['id']),
        'event_update':("UPDATE research_events SET knowledge_origin='Inferred' WHERE id=:id",e['id']),
        'event_delete':('DELETE FROM research_events WHERE id=:id',e['id']),
        'claim_unlink':("UPDATE material_claims SET extraction_metadata='{}'::jsonb WHERE id=:id",c['id']),
    }
    sql,rid=statements[operation]
    with pytest.raises(DBAPIError,match='materials_'):
        async with db_session.begin_nested():await db_session.execute(sa.text(sql),{'id':rid})


@pytest.mark.parametrize('version',['materials-conditions/0','materials-conditions/4','materials-conditions/future'])
async def test_reserved_unknown_version_cannot_bypass_guards(db_session,version):
    f=await seed(db_session);x=await sample(db_session,f)
    with pytest.raises(DBAPIError,match='materials_state_condition_version_unsupported'):
        async with db_session.begin_nested():await state(db_session,f,x['id'],payload(),condition_schema_version=version)


async def test_geometry_and_nondetection_use_same_typed_state_without_false_tc(db_session):
    d=condition('D','thickness','sample_geometry',raw='8 nm',unit='nm',value=8)
    f,x,s,e=await fixture(db_session,payload([field(),d,window()]),with_method=True)
    prop=await thickness(db_session,f,e,s)
    c=await outcome(db_session,f,e,negative('reported',['W']))
    assert prop['value']==8 and c['minimum_temperature_k']==1.8
    assert c['value_kelvin'] is None and c['result_status']=='not_detected'


@pytest.mark.parametrize('target',['supercurrent','josephson_phase_transition'])
async def test_device_raw_field_scan_retained_without_conversion(db_session,target):
    c=field(role='detection_window',window_position='interval')
    c['quantity'].update(raw='9 to 26.42 T',value=None,lower=9,upper=26.42,relation='interval')
    f,x,s,e=await fixture(db_session,payload([c]),with_method=True)
    body=device_negative(target);body['window']={'availability':'reported','condition_ids':['H']}
    row=await observation(db_session,e,body)
    assert row['value'] is None and row['raw']['observation_outcome']==body
    assert s['conditions']['items'][0]==c


@pytest.mark.parametrize('error',['point','superconductivity','wrong_owner','wrong_role'])
async def test_raw_field_cannot_bypass_window_scope(db_session,error):
    c=field(role='detection_window',window_position='interval')
    c['quantity'].update(value=None,lower=9,upper=26.42,relation='interval')
    if error=='point':c['quantity'].update(value=9,lower=None,upper=None,relation='exact');c['window_position']='unspecified'
    if error=='wrong_role':c.update(role='measurement',window_position=None)
    f,x,s,e=await fixture(db_session,payload([c]),with_method=True)
    body=device_negative('superconductivity' if error=='superconductivity' else 'supercurrent')
    body['window']={'availability':'reported','condition_ids':['other' if error=='wrong_owner' else 'H']}
    with pytest.raises(DBAPIError,match='materials_observation_'):
        async with db_session.begin_nested():await observation(db_session,e,body)


async def test_exact_event_selects_only_its_composition_assertion(db_session):
    f,x,s,e=await fixture(db_session)
    c16=await composition(db_session,f,x['id'],formula_raw='16O sample',composition_payload={'variables':[],
        'isotopes':[{'element':'O','mass_number':16,'fraction':quantity(status='not_reported',raw=None,value=None,relation=None,unit=None)}]})
    c18=await composition(db_session,f,x['id'],formula_raw='18O sample',composition_payload={'variables':[],
        'isotopes':[{'element':'O','mass_number':18,'fraction':quantity(raw='80(5)%',value=80,unit='%',
            uncertainty={'kind':'reported_unspecified','minus':5,'plus':5,'level':None,'raw':'(5)'})}]})
    for selected,other in ((c16,c18),(c18,c16)):
        ctx={'materials_context':{'version':'materials-context/1','composition_ids':[str(selected['id'])],'protocol_id':None,'relation_ids':[]}}
        ev=await event(db_session,f,s,context=ctx)
        c=await claim(db_session,f,ev,result_key=str(selected['id']))
        subject=await capture_context_subject(db_session,result_kind='claim',result_id=c['id'])
        ids={v['row_id'] for v in subject.data['rows'] if v['table']=='sample_compositions'}
        assert ids=={str(selected['id'])} and str(other['id']) not in ids
    # This verifies explicit selection, not scientific truth of the selection.


async def test_old_review_and_release_gates_cover_v2(db_session):
    f,x,s,e=await fixture(db_session);c=await claim(db_session,f,e)
    body=await db_session.scalar(sa.text("SELECT sclib_scientific_subject_capture_v2('claim',:id)"),{'id':c['id']})
    with pytest.raises(DBAPIError,match='materials_conditions_review_contract_required'):
        async with db_session.begin_nested():await db_session.execute(sa.text('INSERT INTO scientific_result_subjects(basis_json) VALUES(:body)'),{'body':body})
    with pytest.raises(DBAPIError,match='materials_conditions_release_contract_required'):
        async with db_session.begin_nested():await release(db_session,{'dataset':{'id':f['args']['dataset_id']}},[('material_states',s['id'])])
    with pytest.raises(DBAPIError,match='materials_conditions_v2_retained_history_refuses_downgrade'):
        async with db_session.begin_nested():await migrate(db_session,'downgrade')


async def test_v1_subject_and_validator_unchanged_across_actual_migration(db_session):
    await migrate(db_session,'downgrade')
    f=await seed(db_session)
    await db_session.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    await db_session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    x=await sample(db_session,f);s=await state(db_session,f,x['id'],payload())
    e=await event(db_session,f,s);c=await claim(db_session,f,e)
    before=await capture_context_subject(db_session,result_kind='claim',result_id=c['id'])
    definition=await db_session.scalar(sa.text("SELECT pg_get_functiondef('sclib_materials_conditions_v1(jsonb)'::regprocedure)"))
    await flush_constraints(db_session);await migrate(db_session,'upgrade')
    after=await capture_context_subject(db_session,result_kind='claim',result_id=c['id'])
    assert before==after
    assert definition==await db_session.scalar(sa.text("SELECT pg_get_functiondef('sclib_materials_conditions_v1(jsonb)'::regprocedure)"))
    await migrate(db_session,'downgrade')
    assert before==await capture_context_subject(db_session,result_kind='claim',result_id=c['id'])
    await migrate(db_session,'upgrade')


async def test_upgrade_refuses_preexisting_reserved_state(db_session):
    await migrate(db_session,'downgrade')
    f,x,s,e=await fixture(db_session)
    await flush_constraints(db_session)
    with pytest.raises(DBAPIError,match='materials_conditions_v2_reserved_collision'):
        async with db_session.begin_nested():await migrate(db_session,'upgrade')
