"""A recovery sample must not silently admit unsampled out-of-scope siblings."""
import pytest
import materials_ner_tc_intake as intake
from materials_ner_tc_sampling import retained, RANDOM_METHOD, RECORD_ROUTE


def example():
    rows=[dict(work_id='arxiv:test',result_id=f'r{i}',run_id='run',
        projection_sha256='projection',status='eligible_for_source_audit',holds=[]) for i in (1,2)]
    return dict(projection_sha256='projection',records=rows)


@pytest.mark.parametrize('ids',[[],['r1','r1'],['missing']])
def test_invalid_recovery_scopes_are_rejected(ids):
    with pytest.raises(ValueError):intake.scoped_records(dict(included_result_ids=ids),example())


def test_frozen_recovery_population_and_both_routes_exclude_other_siblings(monkeypatch):
    projection=example()
    monkeypatch.setattr(intake,'checked_projection',lambda entry:({},projection))
    selection=intake.freeze([dict(included_result_ids=['r1'])],seed='predeclared-recovery',sampling_method=RANDOM_METHOD)
    assert [r['result_id'] for r in selection['population']]==['r1']
    assert selection['eligible_results']==1
    audit=dict(records=[dict(**r,verdict='correct',review_completed=True) for r in projection['records']])
    assert [r['result_id'] for r in retained(projection,selection,audit)]==['r1']
    assert [r['result_id'] for r in retained(projection,selection,audit,admission_route=RECORD_ROUTE)]==['r1']


def test_default_scope_preserves_existing_full_projection():
    p=example()
    assert intake.scoped_records({},p)==p['records']
