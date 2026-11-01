"""Ceiling, raw-source retention and SQL pagination on an owned test database."""
import json

import pytest
from sqlalchemy import text

from services.materials_admission_scope import CURRENT_ADMISSION_WHERE
from services.materials_display_policy import TC_DISPLAY_EXCLUSION_SQL, tc_display_exclusion
from services.materials_vnext_read import BASE_WHERE
from tests.test_research_freeze import db_session as db_session


@pytest.mark.asyncio
async def test_public_ceiling_flags_before_counts_and_pagination_without_revoking_admission(db_session):
    base = dict(value_kelvin=None, value_lower_kelvin=None, value_upper_kelvin=None, value_relation='exact',
        pressure_gpa=800, extraction_metadata={'production_admission': {'policy': 'production90/1', 'batch_qualified': True}},
        property_type='tc', result_status='observed', validity_status='pending')
    cases = [
        ({'value_kelvin': 300}, None),
        ({'value_kelvin': 300.0001}, 'tc_above_300k'),
        ({'value_relation': 'interval', 'value_lower_kelvin': 290, 'value_upper_kelvin': 300}, None),
        ({'value_relation': 'interval', 'value_lower_kelvin': 290, 'value_upper_kelvin': 301}, 'tc_above_300k'),
        ({'value_relation': 'gt', 'value_lower_kelvin': 300}, 'tc_above_300k'),
        ({'value_relation': 'ge', 'value_lower_kelvin': 300}, None),
        ({'value_relation': 'lt', 'value_upper_kelvin': 400}, 'tc_above_300k'),
        ({'value_kelvin': 0}, None),
        ({'value_kelvin': 210, 'validity_status': 'rejected'}, None),
    ]
    records = [dict(base, id=i, **changes) for i, (changes, _) in enumerate(cases)]
    source = '''FROM jsonb_to_recordset(CAST(:records AS jsonb)) AS c(
        id integer,value_kelvin double precision,value_lower_kelvin double precision,
        value_upper_kelvin double precision,value_relation text,pressure_gpa double precision,
        extraction_metadata jsonb,property_type text,result_status text,validity_status text)
        CROSS JOIN (SELECT 'published'::text AS status) p
        CROSS JOIN (SELECT 'unknown'::text AS publication_status) w'''
    params = {'records': json.dumps(records)}
    flags = (await db_session.execute(text(f'SELECT c.id, ({TC_DISPLAY_EXCLUSION_SQL}) AS flag, '
        f'({CURRENT_ADMISSION_WHERE}) AS admitted, ({BASE_WHERE}) AS visible ' + source), params)).mappings().all()
    for row in flags:
        original = records[row['id']]
        expected = cases[row['id']][1]
        assert row['flag'] == tc_display_exclusion(original) == expected
        assert row['visible'] is (expected is None and row['admitted'])
        if expected:
            assert row['admitted'] is True  # Hiding a value does not delete or scientifically reject it.
    count = (await db_session.execute(text('SELECT count(*) ' + source + ' WHERE ' + BASE_WHERE), params)).scalar_one()
    assert count == 4
    page = (await db_session.execute(text('SELECT c.id ' + source + ' WHERE ' + BASE_WHERE + ' ORDER BY c.id LIMIT 2 OFFSET 1'), params)).scalars().all()
    assert page == [2, 5]
