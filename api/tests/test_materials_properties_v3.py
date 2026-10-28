"""0102 on disposable PostgreSQL; authored records are never scientific Gold."""
from copy import deepcopy
from pathlib import Path
import json
import runpy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from alembic.operations import Operations
from alembic.migration import MigrationContext

from models.db import Base
from models import materials_properties_v3 as adopted
from services.materials_review_subject import capture_context_subject
from services.materials_review_context import review_context, PROPERTIES_VERSION
from tests.test_research_freeze import add, seed, db_session as db_session
from tests.test_research_release_schema import flush_constraints, release
from tests.test_materials_conditions import setup, thickness
from tests.test_materials_conditions_adoption_v2 import fixture
from tests.test_materials_context import quantity
from tests.test_materials_result_definitions import semantics
from tests.test_research_publication import actors

CASES=json.loads((Path(__file__).parents[2]/'ingestion/tests/fixtures/materials_ner_quantity_adoption_source_cases.json').read_bytes())['cases']


async def prop(db,e,case=None,**overrides):
    case=case or CASES[0]
    return await add(db,'event_properties',**dict(dict(event_id=e['id'],property_key=case['kind'],
        registry_version=adopted.REGISTRY_VERSION,relation=case['quantity']['relation'],
        value=case['expected_value'],unit=case['expected_unit'],record_sha256=uuid4().hex*2,
        raw=dict(result_semantics=semantics('unspecified',key='authored-'+uuid4().hex),
            source_quantity=dict(version='materials-source-quantity/1',quantity=deepcopy(case['quantity'])))),**overrides))


async def migrate(db,direction):
    module=runpy.run_path(str(Path(__file__).parents[1]/'alembic/versions/0102_materials_properties_v3.py'))
    connection=await db.connection()
    def run(conn):
        with Operations.context(MigrationContext.configure(conn)):module[direction]()
    await connection.run_sync(run)


@pytest.mark.parametrize('case',CASES,ids=['negative-slope-a','negative-slope-b','rho-reference'])
@pytest.mark.parametrize('version',[1,2])
async def test_actual_source_shapes_retain_raw_units_and_do_not_become_tc(db_session,case,version):
    f,x,s,e=await (setup(db_session) if version==1 else fixture(db_session))
    row=await prop(db_session,e,case)
    assert row['value']==pytest.approx(case['expected_value'])
    assert row['unit']==case['expected_unit'] and row['uncertainty']=={}
    assert row['raw']['source_quantity']['quantity']==case['quantity']
    subject=await capture_context_subject(db_session,result_kind='property',result_id=row['id'])
    captured=next(r['snapshot'] for r in subject.data['rows'] if r['table']=='event_properties' and r['row_id']==str(row['id']))
    assert captured['raw']==row['raw']
    people=await actors(db_session)
    view=await review_context(db_session,actor_user_id=people['reviewer'],result_kind='property',result_id=row['id'])
    assert view['version']==PROPERTIES_VERSION and not any(view['authority'].values())
    assert not view['source_text_disclosed'] and not view['review_write_available']
    q=view['result'];assert q['source_quantity']['unit']==case['quantity']['unit']
    assert q['source_quantity']['uncertainty']['plus']==case['quantity']['uncertainty']['plus']
    assert q['normalized_uncertainty']['plus']==pytest.approx(case['expected_error'])
    assert q['approximate']==case['quantity']['approximate']
    assert 'raw' not in q['normalized_uncertainty'] and 'raw' not in q['source_quantity']
    assert 'not_point_tc' in q['task_exclusions']


@pytest.mark.parametrize('relation,lower,upper',[('interval',-1.2,-.8),('lt',None,-.8),('ge',-1.2,None)])
async def test_bounds_do_not_create_a_midpoint(db_session,relation,lower,upper):
    f,x,s,e=await setup(db_session);case=deepcopy(CASES[0])
    case['quantity'].update(relation=relation,value=None,lower=lower,upper=upper,uncertainty=None)
    row=await prop(db_session,e,case,value=None,lower=lower,upper=upper)
    assert row['value'] is None and row['lower']==lower and row['upper']==upper


@pytest.mark.parametrize('error',[
    'sign','wrong_projection','old_registry','unknown_registry','resistance_unit','negative_rho',
    'normalized_unit','missing_source','untyped_uncertainty','wrong_kind','scalar_from_range'])
async def test_quantity_and_version_corruption_is_rejected(db_session,error):
    f,x,s,e=await setup(db_session);case=deepcopy(CASES[2] if error in {'resistance_unit','negative_rho'} else CASES[0]);overrides={}
    if error=='sign':overrides['value']=1.1
    elif error=='wrong_projection':overrides['value']=-.11
    elif error=='old_registry':overrides['registry_version']='materials-properties/2'
    elif error=='unknown_registry':overrides['registry_version']='materials-properties/4'
    elif error=='resistance_unit':case['quantity']['unit']='Ω'
    elif error=='negative_rho':case['quantity']['value']=-300;overrides['value']=-3e-6
    elif error=='normalized_unit':overrides['unit']='K/kbar'
    elif error=='missing_source':overrides['raw']={'result_semantics':semantics('unspecified',key='authored')}
    elif error=='untyped_uncertainty':overrides['uncertainty']={'plus':.1}
    elif error=='wrong_kind':overrides['property_key']='tc'
    else:case['quantity'].update(relation='interval',value=None,lower=-1.2,upper=-.8,uncertainty=None)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():await prop(db_session,e,case,**overrides)


@pytest.mark.parametrize('operation',['update_value','relabel','erase_source','delete','change_event'])
async def test_retained_result_is_immutable(db_session,operation):
    f,x,s,e=await setup(db_session);row=await prop(db_session,e)
    sql={
        'update_value':'UPDATE event_properties SET value=-2 WHERE id=:id',
        'relabel':"UPDATE event_properties SET registry_version='materials-properties/2' WHERE id=:id",
        'erase_source':"UPDATE event_properties SET raw='{}'::jsonb WHERE id=:id",
        'delete':'DELETE FROM event_properties WHERE id=:id',
        'change_event':"UPDATE research_events SET knowledge_origin='Computed' WHERE id=:id",
    }[operation]
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():await db_session.execute(sa.text(sql),{'id':e['id'] if operation=='change_event' else row['id']})


async def test_retained_result_refuses_rollback_and_unqualified_release(db_session):
    f,x,s,e=await setup(db_session);row=await prop(db_session,e);await flush_constraints(db_session)
    with pytest.raises(DBAPIError,match='materials_properties_v3_retained_history_refuses_downgrade'):
        async with db_session.begin_nested():await migrate(db_session,'downgrade')
    with pytest.raises(DBAPIError,match='materials_.*release_contract_required'):
        async with db_session.begin_nested():await release(db_session,{'dataset':{'id':f['args']['dataset_id']}},[('event_properties',row['id'])])


async def test_actual_migration_roundtrip_preserves_previous_result_and_subject(db_session):
    await migrate(db_session,'downgrade')
    f,x,s,e=await setup(db_session);row=await thickness(db_session,f,e,s,support=False)
    before=await capture_context_subject(db_session,result_kind='property',result_id=row['id'])
    await flush_constraints(db_session);await migrate(db_session,'upgrade')
    assert before==await capture_context_subject(db_session,result_kind='property',result_id=row['id'])
    table=Base.metadata.tables['event_properties']
    actual=(await db_session.execute(sa.select(table).where(table.c.id==row['id']))).mappings().one()
    assert actual==row
    await migrate(db_session,'downgrade')
    assert before==await capture_context_subject(db_session,result_kind='property',result_id=row['id'])
    await migrate(db_session,'upgrade')
