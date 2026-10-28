"""Source-field validator behavior on owned disposable PostgreSQL only."""
from copy import deepcopy
import json

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.materials_conditions_v2 import UNRESOLVED_FIELD_UNITS
from models.materials_conditions_adoption_v2 import downgrade_statements
from tests.test_materials_conditions import condition, payload
from tests.test_research_freeze import db_session


@pytest_asyncio.fixture(loop_scope='function')
async def candidate(db_session):
    yield db_session


async def valid(db, body, version=2):
    return await db.scalar(sa.text(f'SELECT public.sclib_materials_conditions_v{version}(CAST(:body AS jsonb))'),
                           {'body':json.dumps(body)})


def field(**overrides):
    c=condition('H','reported_magnetic_field',raw='9 T',unit='T',value=9)
    c.update(basis_raw='$H$',orientation_raw=r'$\perp$ $c$',**overrides)
    return c


async def test_raw_field_preserved_without_changing_v1(candidate):
    body=payload([field()]);before=deepcopy(body)
    assert not await valid(candidate,body,1) and await valid(candidate,body,2)
    assert body==before
    with pytest.raises(DBAPIError,match='magnetic_field_convention_unresolved'):
        async with candidate.begin_nested():
            await candidate.scalar(sa.text("SELECT public.sclib_materials_condition_number_v2('reported_magnetic_field',CAST(:q AS jsonb),'value')"),{'q':json.dumps(body['items'][0]['quantity'])})


@pytest.mark.parametrize('unit',UNRESOLVED_FIELD_UNITS)
async def test_source_units_are_accepted_without_conversion(candidate,unit):
    c=field();c['quantity'].update(raw='9 '+unit,unit=unit)
    assert await valid(candidate,payload([c]))


@pytest.mark.parametrize('mistake',['no_basis','blank_basis','wrong_unit','extra_key','duplicate_id','bad_window','bad_role','temperature_selection','pressure_selection','false_ambient'])
async def test_scientific_shape_and_selection_errors_are_rejected(candidate,mistake):
    c=field();body=payload([c])
    if mistake=='no_basis':c['basis_raw']=None
    elif mistake=='blank_basis':c['basis_raw']='  '
    elif mistake=='wrong_unit':c['quantity']['unit']='K'
    elif mistake=='extra_key':c['normalized_tesla']=9
    elif mistake=='duplicate_id':body['items'].append(condition('H'))
    elif mistake=='bad_window':c['window_position']='interval'
    elif mistake=='bad_role':c['role']='tc'
    elif mistake=='temperature_selection':body['temperature_condition_id']='H'
    elif mistake=='pressure_selection':body['pressure'].update(availability='reported',condition_id='H')
    else:body['pressure'].update(availability='not_reported',regime='explicit_ambient',basis_raw='ambient')
    assert not await valid(candidate,body)


@pytest.mark.parametrize('shape',['exact','interval','gt','ge','lt','le'])
async def test_bounds_and_ranges_are_retained_without_midpoints(candidate,shape):
    c=field();c['quantity'].update(relation=shape,value=9 if shape=='exact' else None,
        lower=9 if shape in {'interval','gt','ge'} else None,upper=26.42 if shape in {'interval','lt','le'} else None,
        raw='9--26.42 T' if shape=='interval' else '9 T')
    assert await valid(candidate,payload([c]))


async def test_existing_pressure_contract_and_conversion_unchanged(candidate):
    c=condition(unit='kbar',value=100,raw='100 kbar')
    body=payload([c],availability='reported',regime='nonambient',selected='P',basis='under pressure')
    assert await valid(candidate,body,1) and await valid(candidate,body,2)
    values=await candidate.execute(sa.text("SELECT public.sclib_materials_condition_number_v1('pressure',CAST(:q AS jsonb),'value'),public.sclib_materials_condition_number_v2('pressure',CAST(:q AS jsonb),'value')"),{'q':json.dumps(c['quantity'])})
    assert tuple(values.one())==(10,10)


async def test_empty_adoption_downgrade_preserves_v1_validator(candidate):
    before=await candidate.scalar(sa.text("SELECT pg_get_functiondef('public.sclib_materials_conditions_v1(jsonb)'::regprocedure)"))
    for sql in downgrade_statements():await candidate.execute(sa.text(sql))
    after=await candidate.scalar(sa.text("SELECT pg_get_functiondef('public.sclib_materials_conditions_v1(jsonb)'::regprocedure)"))
    assert before==after and await valid(candidate,payload(),1)
