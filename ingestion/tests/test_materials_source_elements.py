"""Actual source structure and native mapping invariants, without model approval."""
from copy import deepcopy
import pytest
from ingestion.materials_ner.sources import Bundle,sha
from ingestion.materials_ner import source_elements as se,tc_events as tc

def bundle(text,*,tex=False):
    return Bundle.model_validate(dict(version='materials-source-bundle/1',work_id='arxiv:test',title='Test',family=None,
        source_status='unresolved',supplement_status='not_applicable',acquisition_notes=[],
        documents=[dict(id='d',source_uri='https://example.org/source',source_sha256=sha(text.encode()),
            source_kind='original_tex' if tex else 'original_text',role='main',publication_version='v1',version_status='verified',
            processing_permission='allowed',redistribution_permission='unresolved',coverage='partial',parser='fixture')],
        blocks=[dict(id='b',document_id='d',ordinal=0,locator='target:test',text=text,sha256=sha(text.encode()))]))

def choose(cat,literal):
    for k,row in cat['elements'].items():
        if k.startswith('C'):
            for a,first in enumerate(row['tokens']):
                for b,last in enumerate(row['tokens'][a:],a):
                    start=first['start_char']-row['start_char'];end=last['end_char']-row['start_char']
                    if row['text'][start:end]==literal:return dict(element_id=k,first_token=a,last_token=b)
    raise AssertionError(literal)

def fixture():
    b=bundle('Sample A of NbN has Tc = 12.30(4) K. Resistivity was measured at ambient pressure. The onset criterion was used.')
    cat=se.build(b);sel=lambda t:choose(cat,t)
    q=next(k for k,v in cat['elements'].items() if k.startswith('Q') and '12.30' in v['text'])
    exp=dict(formula=sel('NbN'),alternate_formulas=[],identity_resolution='source_scoped',form=None,target_kind='unresolved',
        substrate=None,method='resistivity',method_basis=sel('Resistivity'),criterion=dict(criterion='onset',basis=sel('onset')),
        pressure_regime='explicit_ambient',pressure_basis=sel('ambient pressure.'),conditions=[],source_role='primary',
        attribution_basis=dict(element_id='C1',first_token=None,last_token=None),citation=None)
    event=dict(experiment_index=0,numeric_id=q,unit_id=None,sample_label=sel('Sample A'),variables=[],isotope_label=None,
        isotope_fraction_id=None,preparation=None,criterion_override=None,transition_stage='unspecified',stage_basis=None,
        conditions=[],unresolved=[])
    return b,dict(schema_version=tc.DECISION_VERSION,work_id=b.work_id,experiments=[exp],events=[event],
        unread_block_ids=[],coverage_limitations=[])

def test_table_cells_do_not_lose_column_or_footnote():
    text=r'\begin{tabular}{ccc}x&$^{16}T_c$&$^{18}T_c$\\ &(K)&(K)\\ 0.2&11.25(4)\footnotemark[2]&$<1.7$\\ \end{tabular}'
    c=se.build(bundle(text,tex=True));rows=c['tables'][0]['rows']
    assert len(rows)==3 and len(rows[2]['cells'])==3
    cell=c['elements'][rows[2]['cells'][1]]
    assert cell['footnote_markers']==['2']
    q=c['elements'][cell['numeric_ids'][0]]
    unit=c['elements'][rows[1]['cells'][1]]['unit_ids'][0]
    result,_,_=se.number(c,q['id'],unit)
    assert result['value']==11.25 and result['uncertainty']['plus']==0.04
    bound=c['elements'][rows[2]['cells'][2]]['numeric_ids'][0]
    assert se.number(c,bound,unit)[0]['upper']==1.7
    assert not c['tables'][0]['footnote_applicability_inferred']

def test_approximation_attached_to_prose_is_preserved():
    c=se.build(bundle('The onset is∼42 K, followed by a value of≈6 K.'))
    numbers=[(k,v) for k,v in c['elements'].items() if k.startswith('Q')]
    assert [(v['text'],v['shape']['approximate']) for _,v in numbers]==[('∼42 K',True),('≈6 K',True)]

def test_exact_token_ranges_and_bad_range_not_relocated():
    b=bundle('A sample\n of NbN was measured.');c=se.build(b)
    pick=choose(c,'sample\n of NbN')
    assert se.select(c,pick)['quote']=='sample\n of NbN'
    with pytest.raises(ValueError,match='source_token_range_invalid'):
        se.select(c,dict(pick,last_token=999))

def test_context_numbers_remain_available_but_not_target():
    b=bundle('Tc is 4 K.');ctx=deepcopy(b.blocks[0]);ctx.id='context';ctx.locator='context:methods';ctx.text='A field of 1.0 mT was used.';ctx.sha256=sha(ctx.text.encode());ctx.ordinal=1;b.blocks.append(ctx)
    c=se.build(b);field=next(v for k,v in c['elements'].items() if k.startswith('Q') and 'mT' in v['text'])
    assert not field['target'] and field['shape']['value']==1

def test_native_contract_and_existing_validator_both_pass():
    b,data=fixture();out=tc.project_decisions(data,b)
    assert not out['held']
    row=out['rows'][0]
    assert row['validation']['valid'],row['validation']['issues']
    assert row['technical_status']=='validated'
    assert row['native_graph']['results'][0]['quantity']['uncertainty']['minus']==0.04
    assert not row['canonical_promotion'] and not row['ml_training_eligible']

def test_bad_dependency_isolated_and_ids_stable_across_order():
    b,data=fixture();bad=deepcopy(data['events'][0]);bad['experiment_index']=8
    data['events'].append(bad);one=tc.project_decisions(data,b)
    assert len(one['rows'])==1 and len(one['held'])==1
    data['events'].reverse();two=tc.project_decisions(data,b)
    assert one['rows'][0]['native_graph']['results'][0]['id']==two['rows'][0]['native_graph']['results'][0]['id']

def test_operation_is_retained_as_explicit_mapping_hold():
    b,data=fixture();c=se.build(b)
    data['events'][0]['conditions']=[dict(kind='temperature',role='operation',numeric_id=None,unit_id=None,
        basis=choose(c,'ambient pressure.'),window_position=None)]
    out=tc.project_decisions(data,b);row=out['rows'][0]
    assert row['mapping_holds']==['condition_role_not_in_native_contract:operation']
    assert row['retained_context'][0]['decision']['role']=='operation'
    assert row['technical_status']=='review_required'

def test_named_medium_cannot_become_numeric_condition():
    b,data=fixture();c=se.build(b)
    data['events'][0]['conditions']=[dict(kind='pressure_medium',role='measurement',numeric_id=data['events'][0]['numeric_id'],
        unit_id=None,basis=choose(c,'NbN'),window_position=None)]
    out=tc.project_decisions(data,b)
    assert not out['rows'] and out['held'][0]['code']=='named_medium_is_not_numeric'

def test_decision_schema_has_no_generated_values_quotes_or_database_ids():
    b,_=fixture();schema=tc.decision_schema(b)
    def walk(node):
        if isinstance(node,dict):
            assert not set(node.get('properties',{})) & {'quote','value','lower','upper','sample_id','state_id','protocol_id','evidence'}
            for v in node.values():walk(v)
        elif isinstance(node,list):
            for v in node:walk(v)
    walk(schema)
