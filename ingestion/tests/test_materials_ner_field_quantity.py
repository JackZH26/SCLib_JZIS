"""Separate original witnesses never become a manufactured single source quote."""
import pytest
from ingestion.materials_ner.contract import Evidence, Quantity
from ingestion.materials_ner.quantities import quantity_source_issues, unmapped_quantity_source_issues
from ingestion.materials_ner.field_quantity import expression, balanced


def check(raw, value=80, unit='K', bindings=None, **updates):
    q = Quantity.model_validate(dict(status='reported', raw=raw, relation='exact',
        value=value, unit=unit, **updates))
    evidence = [Evidence(block_id='B1', field='/quantity/raw', quote=raw)]
    evidence += [Evidence(block_id='B1', field='/quantity/'+key, quote=quote)
                 for key, quote in (bindings or {}).items()]
    before = q.model_dump()
    result = unmapped_quantity_source_issues(q, evidence, '/quantity')
    assert q.model_dump() == before
    return result


@pytest.mark.parametrize('raw,relation,number', [
    ('<40$ K','lt',40), ('cannot exceed\r\n40 K','le',40), ('more than 45 K','gt',45)])
def test_explicit_bounds(raw, relation, number):
    shape = dict(relation=relation, value=None)
    shape['upper' if relation in {'lt','le'} else 'lower'] = number
    q = Quantity(status='reported', raw=raw, unit='K', **shape)
    evidence = [Evidence(block_id='B1', field='/quantity/raw', quote=raw)]
    assert quantity_source_issues('tc', q, evidence, '/quantity') == []


def test_separate_approximation_and_uncertainty():
    assert check('80 K', approximate=True,
                 bindings={'approximate':'may be promoted to about 80'}) == []
    assert check('80 K', uncertainty=dict(kind='reported_unspecified',minus=5,plus=5,raw=r'$\pm5$ K'),
                 bindings={'uncertainty':r'uncertainty in temperature values being $\pm5$ K'}) == []
    assert 'field_approximation_requires_review' in check('80 K', approximate=True,
                 bindings={'approximate':'about 60 K'})
    assert 'field_uncertainty_requires_review' in check('80 K',
                 uncertainty=dict(kind='reported_unspecified',minus=5,plus=5,raw='±5 K'),
                 bindings={'uncertainty':'80 K and 40 K with ±5 K'})


@pytest.mark.parametrize('raw,number', [(r'a=3.9202\textrm{\AA}',3.9202),
                                      (r"c'=10.684\textrm{\AA}",10.684)])
def test_lattice_assignment(raw, number):
    assert check(raw, value=number, unit='angstrom') == []


@pytest.mark.parametrize('raw', [r'a=3.9202\textrm{\AA', 'a+b=3.9202 angstrom', '=3.9202 angstrom'])
def test_clipping_and_arbitrary_equations_stay_unresolved(raw):
    assert 'field_numeric_raw_requires_review' in check(raw, value=3.9202, unit='angstrom')


def test_unit_inference_and_substitution_rejected():
    assert 'field_source_unit_missing' in check('-29.7', value=-29.7)
    assert 'numeric_source_unit_mismatch' in check('80 mK')
    assert 'field_unit_witness_mismatch' in check('80', bindings={'unit':'T'})
    assert check('80', bindings={'unit':'K'}) == []


def test_never_turn_estimate_into_bound_or_borrow_neighbor():
    q = Quantity(status='reported',raw='80 K',relation='le',upper=80,unit='K')
    base = [Evidence(block_id='B1',field='/quantity/raw',quote='80 K')]
    for quote in ['estimated to reach as high as 80 K', 'cannot exceed 60 K',
                  'cannot exceed 80 K, 50 K and 40 K, respectively']:
        assert 'field_relation_requires_review' in unmapped_quantity_source_issues(q,
            base+[Evidence(block_id='B1',field='/quantity/relation',quote=quote)],'/quantity')
    assert unmapped_quantity_source_issues(q,base+[
        Evidence(block_id='B1',field='/quantity/relation',quote='cannot exceed 80 K')],'/quantity') == []


def test_unresolved_and_legacy_paths():
    q = Quantity(status='not_extracted',raw='A≈-29.7')
    assert unmapped_quantity_source_issues(q,[], '/quantity') == []
    q = Quantity(status='reported',raw='80 K',relation='exact',value=80,unit='K',
        uncertainty=dict(kind='reported_unspecified',minus=5,plus=5,raw='±5 K'))
    assert unmapped_quantity_source_issues(q,[Evidence(block_id='B1',field='/quantity',quote='80 K')],
        '/quantity') == ['uncertainty_not_in_raw_requires_review']


def test_separate_qualifier_cannot_borrow_another_unit():
    q = Quantity(status='reported',raw='80 K',relation='le',upper=80,unit='K')
    evidence = [Evidence(block_id='B1',field='/quantity/raw',quote='80 K'),
                Evidence(block_id='B1',field='/quantity/relation',quote='cannot exceed 80 eV')]
    assert 'field_relation_requires_review' in quantity_source_issues('tc',q,evidence,'/quantity')
    assert 'field_approximation_requires_review' in check('80 K',approximate=True,
        bindings={'approximate':'may reach about 80 eV'})
