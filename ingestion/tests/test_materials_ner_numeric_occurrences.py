"""Source syntax regression cases from the two original development manuscripts."""
from copy import deepcopy
import pytest
from ingestion.materials_ner.contract import Quantity,Evidence
from ingestion.materials_ner.numeric_occurrences import source_candidates,shared_prefix_shape
from ingestion.materials_ner.field_quantity import field_quantity_issues
from ingestion.materials_ner.sources import sha


def rows(text):
    result=source_candidates(text)
    for row in result:
        assert text[row['start_char']:row['end_char']]==row['quote']
        assert sha(row['quote'].encode())==row['quote_sha256']
        for item in row['evidence'].values():
            assert text[item['start_char']:item['end_char']]==item['quote']
        if row['quantity']:
            quantity=Quantity.model_validate(row['quantity']);before=deepcopy(quantity.model_dump())
            evidence=[Evidence(block_id='B1',field='/quantity/'+k,quote=v['quote']) for k,v in row['evidence'].items()]
            assert field_quantity_issues(quantity,evidence,'/quantity')==[]
            assert quantity.model_dump()==before
    return result


@pytest.mark.parametrize('source,value,unit',[
    (r'$-$ 3.1 kG/$\mu_{B}$',-3.1,'kG/μ_{B}'),
    (r'+ 6.2 kG/$\mu_{B}$',6.2,'kG/μ_{B}'),
    (r'$\approx$ 4 $\times$ 10$^{-5}$ (emu/mol-Cu.Oe)',.00004,'(emu/mol-Cu.Oe)'),
    (r'$\approx$ 1.17 $\times$ 10$^{3}$ [(kHz/T).(mol.Pr.Oe/emu)]',1170,'[(kHz/T).(mol.Pr.Oe/emu)]'),
    (r'$C_{orb}$ $\sim$ 15.8 kHz/T',15.8,'kHz/T'),
    (r'$a=3.9202\textrm{\AA}$',3.9202,'Å'),
])
def test_complete_signed_exponent_and_compound_unit(source,value,unit):
    found=[r for r in rows(source) if r['quantity']]
    assert len(found)==1
    assert found[0]['quantity']['value']==value and found[0]['quantity']['unit']==unit


@pytest.mark.parametrize('source,value,error',[
    (r'(0.18 $\pm$ 0.01)$\%$',.18,.01),
    (r'($-$ 4.25 $\pm$ 0.1) kG/$\mu_{B}$',-4.25,.1),
    (r'2.17 $\pm$ 0.03 MHz',2.17,.03),
    ('0.50(3) K',.5,.03),
])
def test_adjacent_error_is_part_of_the_quantity(source,value,error):
    found=[r for r in rows(source) if r['quantity']]
    assert len(found)==1
    q=found[0]['quantity'];assert q['value']==value
    assert q['uncertainty']['minus']==q['uncertainty']['plus']==error


def test_separate_uncertainty_is_not_a_nominal_value_or_joined_quote():
    source=r'around 80 K with the uncertainty in temperature values being $\pm5$ K'
    nominal,error=rows(source)
    assert nominal['quantity']['value']==80 and nominal['quantity']['approximate']
    assert error['kind']=='uncertainty' and error['quantity'] is None and error['syntax_shape']['value']==5
    assert nominal['quantity']['raw']=='around 80 K'
    q=Quantity.model_validate(dict(nominal['quantity'],uncertainty=dict(kind='reported_unspecified',minus=5,plus=5,raw=error['quote'])))
    evidence=[Evidence(block_id='B1',field='/quantity/raw',quote=nominal['quote']),
              Evidence(block_id='B1',field='/quantity/uncertainty',quote=error['quote'])]
    assert field_quantity_issues(q,evidence,'/quantity')==[]


def test_shared_non_strict_limit_retains_each_original_value_and_relation_witness():
    source='cannot exceed 60 K, 50 K and 40 K'
    found=rows(source);assert [r['quantity']['upper'] for r in found]==[60,50,40]
    assert all(r['quantity']['relation']=='le' for r in found)
    middle=found[1];assert middle['quantity']['raw']=='50 K'
    assert middle['evidence']['relation']['quote']==source
    q=Quantity(status='reported',raw='50 K',relation='exact',value=50,unit='K')
    evidence=[Evidence(block_id='B1',field='/quantity/raw',quote='50 K'),
              Evidence(block_id='B1',field='/quantity/relation',quote=source)]
    assert 'field_relation_disagrees_with_evidence' in field_quantity_issues(q,evidence,'/quantity')


@pytest.mark.parametrize('source,relation,number',[
    ('more than 45 K','gt',45),('<40$ K','lt',40),('cannot exceed\r\n40 K','le',40),
    (r'\lesssim40 K','le',40)])
def test_strict_and_nonstrict_bounds(source,relation,number):
    q=rows(source)[0]['quantity'];assert q['relation']==relation
    assert q['lower' if relation=='gt' else 'upper']==number
    assert q['approximate']==source.startswith('\\lesssim')


def test_approximation_cannot_be_lost_in_a_bare_value_fragment():
    source=r'$\sim$ 14.5$\%$ and 7.2$\%$'
    first,second=rows(source)
    assert first['quantity']['approximate'] and '\\sim' in first['quantity']['raw']
    assert second['quantity'] is None and 'shared_approximation_scope_requires_review' in second['issues']


def test_fitted_zero_without_source_unit_is_retained_but_unresolved():
    row=rows(r'$\delta f(T)$ $\sim$ 0')[0]
    assert row['syntax_shape']['value']==0 and row['syntax_shape']['approximate']
    assert row['quantity'] is None and row['unresolved_quantity']['status']=='not_extracted'
    assert row['unresolved_quantity']['value'] is None


@pytest.mark.parametrize('source',['5-10 K','5 -- 10 K','between 5 and 10 K','5 to 10 K'])
def test_intervals_never_become_independent_endpoints(source):
    found=rows(source);assert len(found)==1
    q=found[0]['quantity'];assert q['relation']=='interval' and q['lower']==5 and q['upper']==10


@pytest.mark.parametrize('source',[
    'between 5 K and 10 K','5 K to 10 K','5 (3) K',r'$-$(0.85 $\pm$ 0.02) (T)',
    '5 K/unsupported',r'$\sim$ 55/45','5 + 2 - 1 K',r'$A\approx-29.7$'])
def test_unsupported_fragments_cannot_be_promoted_as_complete_points(source):
    assert not any(r['quantity'] for r in rows(source))


def test_shared_bound_cannot_use_an_ambiguous_equal_member():
    assert shared_prefix_shape('cannot exceed 60 K, 50 K and 50 K','50 K') is None
    assert shared_prefix_shape('estimated to reach as high as 80 K','80 K') is None
