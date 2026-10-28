"""Complete reported uncertainty notation from arXiv:0711.2257 Table I.

The source's table unit, result role and sample association require separate
evidence; successful numeric parsing does not decide any of them.
"""
import pytest

from ingestion.materials_ner.contract import Evidence, Quantity
from ingestion.materials_ner.field_quantity import expression, field_quantity_issues
from ingestion.materials_ner.numeric_occurrences import source_candidates
from ingestion.materials_ner.quantities import parse_source_numeric


@pytest.mark.parametrize('raw,value,error', [
    ('-3.8(1.2)', -3.8, 1.2), ('100.5(1.4)', 100.5, 1.4),
    ('116.8(1.3)', 116.8, 1.3), ('1.7(1.7)', 1.7, 1.7),
    ('3.49(2)', 3.49, .02), ('91.19(5)', 91.19, .05),
    ('0.018(5)', .018, .005), ('1.0(.25)', 1., .25),
    ('0.0(0.0)', 0., 0.), ('1.00(25)e2', 100., 25.),
    ('1.00(0.25)e2', 100., 25.), ('-3.8(1.2)e-2', -.038, .012),
])
def test_complete_shape_and_unknown_statistical_interpretation(raw,value,error):
    parsed=expression(raw)
    assert parsed['inline_unit']==''
    assert parsed['value']==pytest.approx(value)
    assert parsed['uncertainty']==pytest.approx(error)
    assert parsed['uncertainty_interpretation']=='unspecified'


@pytest.mark.parametrize('raw,value,error', [
    ('100.5(1.4)',100.5,1.4), ('116.8(1.3)',116.8,1.3)])
def test_header_unit_is_separate_evidence(raw,value,error):
    row=source_candidates(raw)[0]
    assert row['quote']==raw and row['quantity'] is None
    assert row['syntax_shape']['uncertainty']['plus']==error
    assert 'source_unit_not_stated' in row['issues']
    q=Quantity(status='reported',raw=raw,relation='exact',value=value,unit='K',
        uncertainty=dict(kind='reported_unspecified',minus=error,plus=error,level=None,raw=raw))
    refs=[Evidence(block_id='table',field='/quantity/raw',quote=raw),
          Evidence(block_id='table',field='/quantity/unit',quote='K')]
    assert field_quantity_issues(q,refs,'/quantity')==[]
    dropped=q.model_copy(update={'uncertainty':None})
    assert field_quantity_issues(dropped,refs,'/quantity')


@pytest.mark.parametrize('raw', ['100.5(1.4) K',r'$100.5(1.4)$~K','≈ 100.5(1.4) K'])
def test_occurrence_retains_whole_uncertainty_not_a_second_value(raw):
    rows=source_candidates(raw)
    assert len(rows)==1
    r=rows[0];q=Quantity.model_validate(r['quantity'])
    assert raw[r['start_char']:r['end_char']]==r['quote']
    assert q.value==100.5 and q.uncertainty.plus==q.uncertainty.minus==1.4
    assert q.approximate==raw.startswith('≈')
    refs=[Evidence(block_id='B',field='/quantity/'+k,quote=v['quote']) for k,v in r['evidence'].items()]
    assert field_quantity_issues(q,refs,'/quantity')==[]


@pytest.mark.parametrize('raw', ['5 (1.2) K','5(-1.2) K','5(1.2.3) K','5(1.2 K',
                                '5(1.2)(2.3) K','5(1e2) K'])
def test_ambiguous_or_malformed_parentheses_not_promoted(raw):
    assert not any(r['quantity'] for r in source_candidates(raw))


def test_source_bound_and_large_exponent_are_not_weakened():
    bound=expression('$<1.7$')
    assert bound['relation']=='lt' and bound['upper']==1.7 and bound['value'] is None
    invalid=parse_source_numeric('1.0(1.2)e301')
    assert invalid['status']=='invalid' and invalid['errors']==['parenthetical_numeric_bound']
