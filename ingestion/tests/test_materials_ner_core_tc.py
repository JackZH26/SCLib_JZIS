"""Core transport/source invariants; these synthetic examples are not Gold data."""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner import core_tc
from ingestion.materials_ner.sources import parse_local


def fixture(tmp_path,text='MgB2 has an onset Tc of 37 K.\nMagnetization was measured on a bulk sample.'):
    path=tmp_path/'paper.txt';path.write_text(text)
    bundle=parse_local(path,work_id='arxiv:0000.00001',title='Synthetic transport test',source_uri='local:test',processing_permission='allowed')
    block=bundle.blocks[0];scope=dict(passages=[dict(block_id=block.id,start_char=0,end_char=len(block.text),role='target')])
    views=core_tc.reading_view(bundle,scope)
    fact=dict(material_as_written='MgB2',sample_context=None,sample_form='bulk',substrate_raw=None,
        tc=dict(status='reported',raw='37 K',relation='exact',value=37.0,lower=None,upper=None,unit='K',approximate=False,uncertainty=None),
        tc_criterion='onset',criterion_raw='onset',measurement_method='magnetization',method_raw='Magnetization',
        pressure_regime='unknown',pressure=None,pressure_statement=None,measurement_context_raw=None,
        origin='measured',evidence=[dict(passage_id='p1',quote=views[0]['text'])],limitations=[])
    return bundle,scope,views,fact


def compile_one(bundle,views,fact):return core_tc.compile_fact(core_tc.Fact.model_validate(fact),0,views,bundle,[])


def test_reading_view_maps_back_to_unchanged_original_and_no_ambient_guess(tmp_path):
    bundle,_,views,f=fixture(tmp_path)
    result=compile_one(bundle,views,f);g=result['graph']
    assert g['states'][0]['pressure']['regime']=='unknown' and not g['states'][0]['conditions']
    quote=g['results'][0]['evidence'][0]
    assert '\n' in quote['quote']
    assert bundle.blocks[0].text[quote['start_char']:quote['end_char']]==quote['quote']
    assert g['samples'][0]['composition_basis']=='unresolved'
    assert g['results'][0]['quantity']['value']==37


@pytest.mark.parametrize('change',['numeric','unit','material','invented_quote'])
def test_unsupported_core_facts_are_held(tmp_path,change):
    bundle,_,views,f=fixture(tmp_path)
    if change=='numeric':f['tc']['value']=73.0
    if change=='unit':f['tc']['unit']='mK'
    if change=='material':f['material_as_written']='NbN'
    if change=='invented_quote':f['evidence'][0]['quote']='MgB2 has Tc = 73 K.'
    with pytest.raises(ValueError):compile_one(bundle,views,f)


def test_known_pressure_keeps_source_units_and_explicit_ambient_has_no_invented_zero(tmp_path):
    b,_,v,f=fixture(tmp_path,'MgB2 has an onset Tc of 37 K at 10 kbar. Magnetization was measured.')
    f.update(pressure_regime='nonambient',pressure_statement='10 kbar',pressure={**f['tc'],'raw':'10 kbar','value':10.0,'unit':'kbar'})
    g=compile_one(b,v,f)['graph'];assert g['states'][0]['conditions'][0]['quantity']['value']==10
    assert g['states'][0]['conditions'][0]['quantity']['unit']=='kbar'
    b,_,v,f=fixture(tmp_path,'MgB2 has an onset Tc of 37 K at ambient pressure. Magnetization was measured.')
    f.update(pressure_regime='explicit_ambient',pressure_statement='ambient pressure')
    g=compile_one(b,v,f)['graph'];assert not g['states'][0]['conditions']
    assert g['states'][0]['pressure']['regime']=='explicit_ambient'


def test_nonprimary_sibling_does_not_remove_primary_result(tmp_path):
    b,s,v,f=fixture(tmp_path);cited=deepcopy(f);cited['origin']='cited'
    p=core_tc.compile_output(json.dumps(dict(results=[f,cited],no_target_reason=None,limitations=[])),b,s)
    assert [r['status'] for r in p['records']]==['eligible_for_source_audit','held']
    assert p['records'][1]['holds']==['outside_initial_primary_experimental_scope']


def test_unbound_measurement_condition_holds_only_that_result_without_erasing_it(tmp_path):
    b,s,_,f=fixture(tmp_path,'MgB2 has an onset Tc of 37 K at 7 T. Magnetization was measured. The field is parallel to c.')
    compound=deepcopy(f);compound['measurement_context_raw']='7 T; parallel to c'
    literal=deepcopy(f);literal['measurement_context_raw']='7 T'
    compiled=core_tc.compile_output(json.dumps(dict(results=[compound,literal],no_target_reason=None,limitations=[])),b,s)
    before=deepcopy(compiled)
    result=core_tc.hold_unbound_measurement_context(compiled)
    assert [r['status'] for r in result['records']]==['held','eligible_for_source_audit']
    assert result['records'][0]['holds']==['core_measurement_context_unresolved']
    assert result['records'][0]['source_result_sha256']==before['records'][0]['source_result_sha256']
    assert result['records'][0]['graph']==before['records'][0]['graph']
    assert result['records'][1]==before['records'][1]


def test_no_range_midpoint_is_manufactured(tmp_path):
    b,_,v,f=fixture(tmp_path,'MgB2 has an onset Tc of 35 to 37 K. Magnetization was measured.')
    f['tc'].update(raw='35 to 37 K',relation='interval',value=None,lower=35.0,upper=37.0)
    g=compile_one(b,v,f)['graph'];assert g['results'][0]['quantity']['value'] is None
    f['tc'].update(relation='exact',value=36.0,lower=None,upper=None)
    with pytest.raises(ValueError):compile_one(b,v,f)


def test_malformed_quantity_does_not_discard_valid_sibling(tmp_path):
    b,s,_,f=fixture(tmp_path);bad=deepcopy(f)
    bad['pressure']={**bad['tc'],'raw':'ambient','relation':None,'value':None,'unit':None}
    p=core_tc.compile_output(json.dumps(dict(results=[bad,f],no_target_reason=None,limitations=[])),b,s)
    assert [r['status'] for r in p['records']]==['held','eligible_for_source_audit']
    assert p['records'][1]['graph']['results'][0]['id']=='r2'


def test_redundant_exact_bounds_are_logged_without_changing_source_output(tmp_path):
    b,s,_,f=fixture(tmp_path);f['tc'].update(lower=37.0,upper=37.0)
    before=deepcopy(f)
    p=core_tc.compile_output(json.dumps(dict(results=[f],no_target_reason=None,limitations=[])),b,s)
    row=p['records'][0];q=row['graph']['results'][0]['quantity']
    assert row['status']=='eligible_for_source_audit'
    assert q['value']==37.0 and q['lower'] is None and q['upper'] is None
    assert len(row['structural_normalizations'])==2 and f==before
    assert row['source_result_sha256']==core_tc.digest(before)
    f['tc']['upper']=38.0
    p=core_tc.compile_output(json.dumps(dict(results=[f],no_target_reason=None,limitations=[])),b,s)
    assert p['records'][0]['status']=='held'
    assert not p['records'][0]['structural_normalizations']


def test_sample_description_survives_for_semantic_audit_and_old_policy_replays(tmp_path):
    b,s,v,f=fixture(tmp_path,'MgB2 with x=0 has an onset Tc of 37 K. Magnetization was measured.')
    f['sample_context']='Undoped sample; x = 0'
    current=core_tc.compile_output(json.dumps(dict(results=[f],no_target_reason=None,limitations=[])),b,s)
    assert current['records'][0]['graph']['samples'][0]['label']==f['sample_context']
    assert 'scientific ownership requires source audit' in current['records'][0]['validation']['validation_scope']
    old=core_tc.compile_output(json.dumps(dict(results=[f],no_target_reason=None,limitations=[])),b,s,preserve_sample_context=False)
    assert old['records'][0]['graph']['samples'][0]['label'] is None


def test_known_criterion_rebinds_pdf_line_breaks_without_changing_words(tmp_path):
    b,_,v,f=fixture(tmp_path,'MgB2 has an onset\ncriterion Tc of 37 K. Magnetization was measured.')
    f['criterion_raw']='onset criterion'
    g=compile_one(b,v,f)['graph']
    assert g['results'][0]['definition']['criterion_raw']=='onset\ncriterion'
    f['criterion_raw']='zero resistance'
    with pytest.raises(ValueError,match='core_criterion_literal_unresolved'):compile_one(b,v,f)


def test_token_alignment_never_joins_numbers_or_changes_words():
    assert core_tc.token_span('Fig.~x', 'Fig. ~x')==(0,7)
    assert core_tc.token_span('12 K', '1 2 K') is None
    assert core_tc.token_span('35 K', '135 K') is None
    assert core_tc.token_span('35 K', '35 K and 35 K') is None
    assert core_tc.token_span('MgB2 has Tc', 'MgB2 always has Tc') is None


def test_optional_unbound_quote_is_logged_but_core_evidence_still_required(tmp_path):
    b,s,v,f=fixture(tmp_path)
    f['evidence'].append(dict(passage_id='p1',quote='Invented sentence.'))
    out=core_tc.compile_output(json.dumps(dict(results=[f],no_target_reason=None,limitations=[])),b,s)
    row=out['records'][0]
    assert row['status']=='eligible_for_source_audit'
    assert row['evidence_binding_notes'][0]['action']=='omitted'
    old=core_tc.compile_output(json.dumps(dict(results=[f],no_target_reason=None,limitations=[])),b,s,format_binding=False)
    assert old['records'][0]['status']=='held'
    f['evidence']=f['evidence'][1:]
    out=core_tc.compile_output(json.dumps(dict(results=[f],no_target_reason=None,limitations=[])),b,s)
    assert out['records'][0]['status']=='held'


def test_shared_unit_list_preserves_literal_list_and_never_creates_mean(tmp_path):
    b,s,v,f=fixture(tmp_path,'MgB2 samples have onset Tc values 35, 37 and 39 K, respectively. Magnetization was measured.')
    g=core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True)
    binding=g['quantity_evidence_bindings'][0]
    assert binding['source_list']=='35, 37 and 39 K' and binding['matching_positions']==[1]
    assert b.blocks[0].text[binding['start_char']:binding['end_char']]==binding['source_list']
    for changes in [dict(raw='36 K',value=36),dict(raw='37 mK',unit='mK'),dict(value=38)]:
        bad=deepcopy(f);bad['tc'].update(changes)
        with pytest.raises(ValueError):core_tc.compile_fact(core_tc.Fact.model_validate(bad),0,v,b,[],format_binding=True)
    b,s,v,f=fixture(tmp_path,'MgB2 has an onset Tc of 35 to 39 K. Magnetization was measured.')
    with pytest.raises(ValueError):core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True)


def test_explicit_tc_label_keeps_raw_approximation_and_validates_value(tmp_path):
    b,s,v,f=fixture(tmp_path,r'MgB2 has an onset T$_C \simeq$ 35 K. Magnetization was measured.')
    f['tc'].update(raw=r'T$_C \simeq$ 35 K',value=35,approximate=True)
    row=core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True)
    assert row['graph']['results'][0]['quantity']==f['tc']
    assert row['quantity_evidence_bindings'][0]['mode']=='explicit_tc_label'
    f['tc']['value']=37
    with pytest.raises(ValueError):core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True)


def test_tex_quantity_binding_preserves_original_and_rejects_partial_numbers(tmp_path):
    b,s,v,f=fixture(tmp_path,r'MgB2 has onset $T_c=37$~K. Magnetization was measured.')
    f['tc']['raw']='37~K'
    row=core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True,scope_binding=True)
    assert row['graph']['results'][0]['quantity']==f['tc']
    assert row['quantity_evidence_bindings'][0]['mode']=='numeric_tex_presentation'
    for text in [r'MgB2 has onset $T_c=137$~K. Magnetization was measured.',
                 r'MgB2 has onset $T_c=35$ to $37$~K. Magnetization was measured.',
                 r'MgB2 has onset $T_c\geq 37$~K. Magnetization was measured.',
                 r'MgB2 has onset $T_c\approx 37$~K. Magnetization was measured.']:
        b,s,v,f=fixture(tmp_path,text);f['tc']['raw']='37~K'
        with pytest.raises(ValueError):core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True,scope_binding=True)


def test_tc_table_unit_requires_an_explicit_header_and_a_real_value(tmp_path):
    text='MgB2 has onset measured by Magnetization. Table 1: sample Tc (K) A 37 B 39.'
    b,s,v,f=fixture(tmp_path,text)
    row=core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True,scope_binding=True)
    assert row['quantity_evidence_bindings'][0]['mode']=='explicit_tc_table_unit'
    for replacement in ['Tc (mK)','field (K)','Tc']:
        b,s,v,f=fixture(tmp_path,text.replace('Tc (K)',replacement))
        with pytest.raises(ValueError):core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True,scope_binding=True)
    b,s,v,f=fixture(tmp_path,text);f['tc'].update(raw='38 K',value=38)
    with pytest.raises(ValueError):core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True,scope_binding=True)


def test_material_context_can_only_come_from_the_supplied_scope(tmp_path):
    b,s,v,f=fixture(tmp_path,'MgB2 was prepared. Its onset Tc is 37 K. Magnetization was measured.')
    f['evidence']=[dict(passage_id='p1',quote='Its onset Tc is 37 K. Magnetization was measured.')]
    with pytest.raises(ValueError,match='core_material_not_in_evidence'):compile_one(b,v,f)
    row=core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True,scope_binding=True)
    assert row['evidence_binding_notes'][0]['mode']=='material_literal_in_supplied_scope'
    start=b.blocks[0].text.index('Its onset')
    limited=core_tc.reading_view(b,dict(passages=[dict(block_id=b.blocks[0].id,start_char=start,end_char=len(b.blocks[0].text),role='target')]))
    with pytest.raises(ValueError,match='core_material_not_in_evidence'):
        core_tc.compile_fact(core_tc.Fact.model_validate(f),0,limited,b,[],format_binding=True,scope_binding=True)


def test_quoted_tex_row_gets_its_original_table_header(tmp_path):
    text=r'''MgB2 has onset measured by Magnetization.
\begin{table}
\begin{tabular}{cc}
sample & $T_c$ (K) \\
A & 37 \\
B & 39 \\
\end{tabular}
\end{table}'''
    b,s,v,f=fixture(tmp_path,text)
    f['evidence']=[dict(passage_id='p1',quote='MgB2 has onset measured by Magnetization.'),dict(passage_id='p1',quote=r'A & 37 \\')]
    row=core_tc.compile_fact(core_tc.Fact.model_validate(f),0,v,b,[],format_binding=True,scope_binding=True)
    assert row['quantity_evidence_bindings'][0]['mode']=='explicit_tc_table_unit'
    table=next(e for e in row['graph']['results'][0]['evidence'] if r'\begin{table}' in e['quote'])
    assert b.blocks[0].text[table['start_char']:table['end_char']]==table['quote']


def empty_optional_pressure():
    return dict(status='not_reported',raw=None,relation=None,value=None,lower=None,
        upper=None,unit=None,approximate=False,uncertainty=None)


def test_empty_optional_pressure_keeps_unknown_and_replays_legacy_policy(tmp_path):
    b,s,_,f=fixture(tmp_path);f['pressure']=empty_optional_pressure();before=deepcopy(f)
    raw=json.dumps(dict(results=[f],no_target_reason=None,limitations=[]))
    row=core_tc.compile_output(raw,b,s)['records'][0]
    assert row['status']=='eligible_for_source_audit'
    state=row['graph']['states'][0]
    assert state['pressure']==dict(availability='not_reported',regime='unknown',condition_id=None,basis_raw=None)
    assert not state['conditions']
    assert row['graph']['results'][0]['quantity']==before['tc']
    assert row['structural_normalizations']==[dict(path='/pressure',before=before['pressure'],after=None,reason='empty_not_reported_optional_pressure')]
    assert row['source_result_sha256']==core_tc.digest(before) and f==before
    old=core_tc.compile_output(raw,b,s,empty_pressure_as_missing=False)['records'][0]
    assert old['status']=='held' and old['holds']==['core_explicit_quantity_required']
    assert old['source_result_sha256']==row['source_result_sha256']


def test_empty_pressure_explicit_ambient_requires_unchanged_source_statement(tmp_path):
    b,s,_,f=fixture(tmp_path,'MgB2 has an onset Tc of 37 K at ambient pressure. Magnetization was measured.')
    f.update(pressure=empty_optional_pressure(),pressure_regime='explicit_ambient',pressure_statement='ambient pressure')
    raw=lambda:json.dumps(dict(results=[f],no_target_reason=None,limitations=[]))
    row=core_tc.compile_output(raw(),b,s)['records'][0]
    assert row['status']=='eligible_for_source_audit'
    state=row['graph']['states'][0]
    assert state['pressure']['regime']=='explicit_ambient' and state['pressure']['basis_raw']=='ambient pressure'
    assert not state['conditions']
    f['pressure_statement']='standard atmospheric conditions'
    row=core_tc.compile_output(raw(),b,s)['records'][0]
    assert row['status']=='held' and row['holds']==['core_ambient_statement_required']


@pytest.mark.parametrize('case',['nonambient','unknown_statement','populated_raw','populated_value','conflicted','not_applicable','approximate','wrong_tc'])
def test_empty_pressure_normalization_never_erases_ambiguity_or_bad_tc(tmp_path,case):
    b,s,_,f=fixture(tmp_path);f['pressure']=empty_optional_pressure()
    if case=='nonambient':f['pressure_regime']='nonambient'
    elif case=='unknown_statement':f['pressure_statement']='pressure varied'
    elif case=='populated_raw':f['pressure']['raw']='pressure not specified'
    elif case=='populated_value':f['pressure']['value']=2
    elif case in {'conflicted','not_applicable'}:f['pressure']['status']=case
    elif case=='approximate':f['pressure']['approximate']=True
    else:f['tc']['value']=38
    before=deepcopy(f)
    row=core_tc.compile_output(json.dumps(dict(results=[f],no_target_reason=None,limitations=[])),b,s)['records'][0]
    assert row['status']=='held'
    assert row['source_result_sha256']==core_tc.digest(before) and f==before
    if case!='wrong_tc':assert not row['structural_normalizations']
