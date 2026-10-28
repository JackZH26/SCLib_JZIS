"""Target-specific observations on disposable PostgreSQL; synthetic, not Gold."""
from copy import deepcopy
from pathlib import Path
import runpy

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.materials_observation_outcomes_v1 import VERSION,REGISTRY_VERSION
from services.materials_review_context import review_context,OBSERVATIONS_VERSION
from services.materials_review_subject import capture_context_subject
from tests.test_research_freeze import add,seed,db_session as db_session
from tests.test_research_release_schema import flush_constraints,release
from tests.test_research_publication import actors
from tests.test_materials_conditions import setup,claim,condition,payload,event as condition_event,thickness
from tests.test_materials_context import quantity,protocol
from tests.test_materials_claim_outcomes import conditional,window


def negative(target='supercurrent',key='N1'):
    return {'version':VERSION,'kind':'non_detection','result_key':key,'target':target,'observable':{
        'supercurrent':'supercurrent','josephson_phase_transition':'zero_pi_transition','superconductivity':'resistive_transition'}[target],
        'existence':'not_established','raw':{
            'supercurrent':'No resolvable supercurrent at the 10 nA current step.',
            'josephson_phase_transition':'No 0-pi transition in the measured series.',
            'superconductivity':'No resistive superconducting transition was resolved.'}[target],
        'window':{'availability':'not_reported','condition_ids':[]},'sensitivities':[],
        'source_role':'primary','cited_source_raw':None}


def sensitivity(role='measurement_step',unit='nA',value=10):
    return {'role':role,'quantity_kind':'electric_current','quantity':quantity(raw=f'{value} {unit}',value=value,unit=unit),
        'raw':f'{value} {unit} current step' if role=='measurement_step' else f'{value} {unit} {role}'}


async def fixture(db,body=None,**event_overrides):
    f,x,s,unused=await setup(db,body)
    p=await protocol(db,f,method_class='other',method_raw='current-voltage measurement')
    if event_overrides.get('knowledge_origin')=='Computed':
        run=await add(db,'research_runs',run_kind='dft',settings_schema_version='synthetic/1',record_sha256='a'*64)
        event_overrides['producer_run_id']=run['id']
    e=await condition_event(db,f,s,p,**event_overrides)
    return f,x,s,e,p


async def observation(db,e,body=None,**overrides):
    return await add(db,'event_properties',**{'event_id':e['id'],'property_key':'non_detection',
        'registry_version':REGISTRY_VERSION,'component_key':'not_applicable','relation':'unreported','unit':'not_applicable',
        'record_sha256':'f'*64,'raw':{'observation_outcome':body or negative()},**overrides})


@pytest.mark.parametrize('target',['supercurrent','josephson_phase_transition','superconductivity'])
async def test_target_specific_storage_and_private_read_preserve_scope_without_a_tc(db_session,target):
    f,x,s,e,p=await fixture(db_session,payload([window()]))
    body=negative(target);body['window']={'availability':'reported','condition_ids':['W']}
    body['sensitivities']=[sensitivity()]
    row=await observation(db_session,e,body)
    assert row['value'] is row['lower'] is row['upper'] is None and row['unit']=='not_applicable'
    assert row['raw']['observation_outcome']==body and row['record_sha256']!='f'*64
    subject=await capture_context_subject(db_session,result_kind='property',result_id=row['id'])
    root=next(r['snapshot'] for r in subject.data['rows'] if r['table']=='event_properties' and r['row_id']==str(row['id']))
    assert root['raw']['observation_outcome']==body
    people=await actors(db_session)
    context=await review_context(db_session,actor_user_id=people['reviewer'],result_kind='property',result_id=row['id'])
    assert context['version']==OBSERVATIONS_VERSION and not context['source_text_disclosed']
    outcome=context['result']['outcome']
    assert outcome['target']==target and outcome['sensitivities'][0]['role']=='measurement_step'
    assert outcome['sensitivities'][0]['quantity']['value']==10
    assert 'raw' not in outcome and 'raw' not in outcome['sensitivities'][0]
    assert ('device_non_detection_is_not_superconductivity_negative_label' in outcome['task_exclusions'])==(target!='superconductivity')
    assert not any(context['authority'].values())


@pytest.mark.parametrize('unit',['A','mA','uA','μA','µA','nA','pA'])
async def test_source_current_unit_is_retained_without_scalar_negative_label(db_session,unit):
    f,x,s,e,p=await fixture(db_session);body=negative();body['sensitivities']=[sensitivity(unit=unit)]
    row=await observation(db_session,e,body)
    assert row['raw']['observation_outcome']['sensitivities'][0]['quantity']['unit']==unit
    assert row['value'] is None


@pytest.mark.parametrize('mutation',['target','observable','no_raw','unknown_member','fake_tc','null_target',
    'threshold_from_step','wrong_unit','negative_sensitivity','missing_sensitivity_value','wrong_dimension',
    'duplicate_window','window_availability','no_citation','conditional_device','source_role','sc_device_wording','sc_phase_tex'])
async def test_invalid_scientific_shapes_are_refused(db_session,mutation):
    f,x,s,e,p=await fixture(db_session);body=negative();body['sensitivities']=[sensitivity()]
    if mutation=='target':body['target']='ferromagnetism'
    if mutation=='observable':body['observable']='resistive_transition'
    if mutation=='no_raw':body['raw']=None
    if mutation=='unknown_member':body['unexpected']=True
    if mutation=='fake_tc':body['tc_value']=0
    if mutation=='null_target':body['target']=None
    if mutation=='threshold_from_step':body['sensitivities'][0]['role']='detection_threshold'
    if mutation=='wrong_unit':body['sensitivities'][0]['quantity']['unit']='K'
    if mutation=='negative_sensitivity':body['sensitivities'][0]['quantity']['value']=-1
    if mutation=='missing_sensitivity_value':body['sensitivities'][0]['quantity']['value']=None
    if mutation=='wrong_dimension':body['sensitivities'][0]['quantity_kind']='temperature'
    if mutation=='duplicate_window':body['window']={'availability':'reported','condition_ids':['W','W']}
    if mutation=='window_availability':body['window']={'availability':'reported','condition_ids':[]}
    if mutation=='no_citation':body['source_role']='cited'
    if mutation=='conditional_device':body['conditional']=conditional()
    if mutation=='source_role':body['source_role']='computed'
    if mutation=='sc_device_wording':body.update(target='superconductivity',observable='unspecified')
    if mutation=='sc_phase_tex':body.update(target='superconductivity',observable='unspecified',raw=r'No $0$--$\pi$ transition is resolved.')
    with pytest.raises(DBAPIError,match='materials_observation_contract'):
        async with db_session.begin_nested():await observation(db_session,e,body)


@pytest.mark.parametrize('mutation',['numeric','bound','uncertainty','unit','registry','property','parallel_semantics'])
async def test_no_second_scalar_or_semantic_authority(db_session,mutation):
    f,x,s,e,p=await fixture(db_session)
    changes={'numeric':{'relation':'exact','value':0},'bound':{'relation':'lt','upper':10},
        'uncertainty':{'uncertainty':{'plus':1}},'unit':{'unit':'K'},'registry':{'registry_version':'rv2/1'},
        'property':{'property_key':'tc'},'parallel_semantics':{'raw':{'observation_outcome':negative(),'result_semantics':{}}}}[mutation]
    with pytest.raises(DBAPIError,match='materials_'):
        async with db_session.begin_nested():await observation(db_session,e,**changes)


@pytest.mark.parametrize('role',['sample_geometry','fit_window','synthesis'])
async def test_unrelated_condition_role_cannot_be_a_detection_scan(db_session,role):
    c=condition('D','thickness',role,raw='4.5 nm',value=4.5,unit='nm')
    f,x,s,e,p=await fixture(db_session,payload([c]));body=negative();body['window']={'availability':'reported','condition_ids':['D']}
    with pytest.raises(DBAPIError,match='materials_observation_window_role'):
        async with db_session.begin_nested():await observation(db_session,e,body)


async def test_device_study_extent_is_not_superconductivity_detection_window(db_session):
    c=condition('D','thickness','study_extent',raw='2 to 4 nm',relation='interval',value=None,lower=2,upper=4,unit='nm')
    f,x,s,e,p=await fixture(db_session,payload([c]));body=negative();body['window']={'availability':'reported','condition_ids':['D']}
    row=await observation(db_session,e,body)
    assert row['raw']['observation_outcome']['window']['condition_ids']==['D']
    other=negative('superconductivity','N2');other['window']=body['window']
    with pytest.raises(DBAPIError,match='materials_observation_window_role'):
        async with db_session.begin_nested():await observation(db_session,e,other)


async def test_window_must_belong_to_exact_event_state(db_session):
    f,x,s,e,p=await fixture(db_session);body=negative();body['window']={'availability':'reported','condition_ids':['foreign-W']}
    with pytest.raises(DBAPIError,match='materials_observation_window_state_ownership'):
        async with db_session.begin_nested():await observation(db_session,e,body)


@pytest.mark.parametrize('role',['detection_window','study_extent'])
@pytest.mark.parametrize('kind,unit',[('temperature','K'),('thickness','nm')])
async def test_an_exact_measurement_point_does_not_become_scan_extent(db_session,role,kind,unit):
    c=condition('W',kind,role,raw=f'4.5 {unit}',value=4.5,unit=unit)
    if role=='detection_window':c['window_position']='unspecified'
    f,x,s,e,p=await fixture(db_session,payload([c]));body=negative();body['window']={'availability':'reported','condition_ids':['W']}
    with pytest.raises(DBAPIError,match='materials_observation_point_is_not_scan_window'):
        async with db_session.begin_nested():await observation(db_session,e,body)


@pytest.mark.parametrize('event_overrides',[{'event_type':'calculation','knowledge_origin':'Computed'}, {'knowledge_origin':'Inferred'}])
async def test_non_observed_events_cannot_be_negative_experimental_labels(db_session,event_overrides):
    f,x,s,e,p=await fixture(db_session,**event_overrides)
    with pytest.raises(DBAPIError,match='materials_observation_source_scoped_measurement_required'):
        async with db_session.begin_nested():await observation(db_session,e)


async def test_missing_method_remains_unpromotable(db_session):
    f,x,s,e=await setup(db_session)
    with pytest.raises(DBAPIError,match='materials_observation_source_scoped_measurement_required'):
        async with db_session.begin_nested():await observation(db_session,e)


async def test_conditional_superconductivity_is_retained_without_tc_or_scan_floor(db_session):
    f,x,s,e,p=await fixture(db_session);body=negative('superconductivity');body['conditional']=conditional()
    row=await observation(db_session,e,body)
    assert row['raw']['observation_outcome']['conditional']['tc_bound']['upper']==1.9
    assert row['value'] is row['lower'] is row['upper'] is None
    assert row['raw']['observation_outcome']['window']['condition_ids']==[]


@pytest.mark.parametrize('action',['update','delete','approve_event','accept_event'])
async def test_observation_history_and_scientific_authority_stay_guarded(db_session,action):
    f,x,s,e,p=await fixture(db_session);row=await observation(db_session,e)
    table=Base.metadata.tables['event_properties'];events=Base.metadata.tables['research_events']
    if action=='update':statement=table.update().where(table.c.id==row['id']).values(raw={'observation_outcome':negative(key='changed')})
    if action=='delete':statement=table.delete().where(table.c.id==row['id'])
    if action=='approve_event':statement=events.update().where(events.c.id==e['id']).values(review_status='approved')
    if action=='accept_event':statement=events.update().where(events.c.id==e['id']).values(validity_status='accepted')
    with pytest.raises(DBAPIError,match='materials_observation_'):
        async with db_session.begin_nested():await db_session.execute(statement)


async def test_unique_result_key_preserves_distinct_targets_and_rejects_double_storage(db_session):
    f,x,s,e,p=await fixture(db_session)
    a=await observation(db_session,e);b=await observation(db_session,e,negative('josephson_phase_transition','N2'))
    assert a['id']!=b['id']
    with pytest.raises(DBAPIError,match='uq_mrd93_event_result_key'):
        async with db_session.begin_nested():await observation(db_session,e,negative('josephson_phase_transition'))


async def test_preapproved_event_does_not_approve_a_new_observation(db_session):
    f,x,s,e,p=await fixture(db_session,validity_status='accepted')
    with pytest.raises(DBAPIError,match='materials_observation_review_policy_required'):
        async with db_session.begin_nested():await observation(db_session,e)


async def test_new_observation_cannot_use_legacy_release_policy(db_session):
    f,x,s,e,p=await fixture(db_session);row=await observation(db_session,e)
    with pytest.raises(DBAPIError,match='materials_observation_release_policy_required'):
        async with db_session.begin_nested():
            await release(db_session,{'dataset':{'id':f['args']['dataset_id']}},[('event_properties',row['id'])])


async def migration(db,action):
    module=runpy.run_path(str(Path(__file__).parents[1]/'alembic/versions/0099_materials_observation_outcomes.py'))
    connection=await db.connection()
    def run(conn):
        with Operations.context(MigrationContext.configure(conn)):module[action]()
    await connection.run_sync(run)


async def test_empty_migration_roundtrip_preserves_legacy_claim(db_session):
    f,x,s,e=await setup(db_session);old=await claim(db_session,f,e);await flush_constraints(db_session)
    properties=Base.metadata.tables['event_properties']
    old_property=(await db_session.execute(sa.select(properties).where(properties.c.id==f['children']['property']))).mappings().one()
    await migration(db_session,'downgrade');await migration(db_session,'upgrade')
    table=Base.metadata.tables['material_claims']
    actual=(await db_session.execute(sa.select(table).where(table.c.id==old['id']))).mappings().one()
    assert actual==old
    assert (await db_session.execute(sa.select(properties).where(properties.c.id==old_property['id']))).mappings().one()==old_property


async def test_retained_observation_refuses_downgrade(db_session):
    f,x,s,e,p=await fixture(db_session);await observation(db_session,e)
    with pytest.raises(DBAPIError,match='materials_observation_retained_history_refuses_downgrade'):
        async with db_session.begin_nested():await migration(db_session,'downgrade')


async def test_reserved_legacy_raw_member_stops_upgrade_without_reinterpretation(db_session):
    f,x,s,e=await setup(db_session);await flush_constraints(db_session)
    await migration(db_session,'downgrade')
    await add(db_session,'event_properties',event_id=e['id'],property_key='band_gap',relation='exact',value=0,
        unit='eV',record_sha256='b'*64,raw={'observation_outcome':{'legacy_arbitrary_json':True}})
    await flush_constraints(db_session)
    with pytest.raises(DBAPIError,match='materials_observation_reserved_member_collision'):
        async with db_session.begin_nested():await migration(db_session,'upgrade')
