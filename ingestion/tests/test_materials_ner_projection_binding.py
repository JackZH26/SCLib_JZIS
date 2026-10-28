"""Evidence metadata adaptation must preserve science and reject guessing."""
from copy import deepcopy
import json
import pytest
from ingestion.materials_ner import projection_binding as binding
from test_materials_ner_reviewed_proposals import prepared, graph


def case(prepared):
    _,_,path,bundle,manifest=prepared
    return graph(bundle),bundle,json.loads(path.read_text()),manifest


def test_entity_address_and_original_coordinates_compile_without_scientific_edits(prepared):
    g,b,s,m=case(prepared)
    for e in g['results'][0]['evidence']:e['field']='/results/r'+e['field']
    before=deepcopy(g);out=binding.compile_bindings(g,b,s,m)
    assert g==before and out['scientific_payload_unchanged']
    assert not out['holds'],out['holds']
    assert binding.scientific_payload(out['graph'])==binding.scientific_payload(g)
    for e in out['graph']['results'][0]['evidence']:
        assert not e['field'].startswith('/results/')
        assert b.blocks[0].text[e['start_char']:e['end_char']]==e['quote']


@pytest.mark.parametrize('field', ['/results/other/quantity','/results/r/conditions/pressure','/results/r','/quantity/unknown'])
def test_wrong_entity_root_and_named_array_paths_remain_held(prepared,field):
    g,b,s,m=case(prepared);g['results'][0]['evidence'][0]['field']=field
    out=binding.compile_bindings(g,b,s,m)
    assert any(x['code']=='evidence_field_address_unresolved' for x in out['holds'])


def test_bad_explicit_coordinate_is_never_relocated(prepared):
    g,b,s,m=case(prepared);e=g['results'][0]['evidence'][0];e.update(start_char=1,end_char=2)
    out=binding.compile_bindings(g,b,s,m)
    assert any(x['code']=='explicit_evidence_selector_invalid' for x in out['holds'])
    assert out['graph']['results'][0]['evidence'][0]['start_char']==1


def test_wrong_quote_is_held_and_scientific_values_are_never_repaired(prepared):
    g,b,s,m=case(prepared);g['results'][0]['evidence'][0]['quote']='fabricated source quote'
    g['results'][0]['quantity']['value']=777
    out=binding.compile_bindings(g,b,s,m)
    assert any(x['code']=='evidence_quote_unresolved_in_scope' for x in out['holds'])
    assert out['graph']['results'][0]['quantity']['value']==777


def test_result_quantity_does_not_borrow_context(prepared):
    g,b,s,m=case(prepared);s['passages'][0]['role']='context'
    out=binding.compile_bindings(g,b,s,m)
    assert any(x['code']=='evidence_quote_unresolved_in_scope' and x['path'].startswith('/results/') for x in out['holds'])


def test_shared_unit_can_come_from_context_while_value_requires_target(prepared):
    g,b,s,m=case(prepared);block=b.blocks[0];a=block.text.index('5 K')
    for group in binding.GROUPS:
        for entity in g[group]:entity['evidence']=[]
    g['results'][0]['evidence']=[dict(field='/quantity/raw',block_id=block.id,quote='5'),
        dict(field='/quantity/unit',block_id=block.id,quote='K')]
    s['passages']=[dict(block_id=block.id,start_char=0,end_char=a+1,role='target'),
        dict(block_id=block.id,start_char=a+1,end_char=len(block.text),role='context')]
    out=binding.compile_bindings(g,b,s,m)
    assert not out['holds'],out['holds']
    assert out['graph']['results'][0]['evidence'][1]['quote']=='K'


def test_missing_block_never_creates_an_unlogged_partial_edit(prepared):
    g,b,s,m=case(prepared);e=g['results'][0]['evidence'][0]
    e.update(field='/results/r/quantity',block_id='missing')
    out=binding.compile_bindings(g,b,s,m)
    assert out['graph']['results'][0]['evidence'][0]==e
    assert any(x['code']=='evidence_source_block_missing' for x in out['holds'])


def test_context_quote_locates_short_unit_and_preserves_raw_model(prepared):
    g,b,s,m=case(prepared)
    for group in binding.GROUPS:
        for entity in g[group]:entity['evidence']=[]
    e=dict(field='/quantity/unit',block_id=b.blocks[0].id,quote='K',context_quote='The sample showed a resistive onset at 5 K.')
    g['results'][0]['evidence']=[e];before=deepcopy(g)
    out=binding.compile_bindings(g,b,s,m)
    assert not out['holds'],out['holds']
    final=out['graph']['results'][0]['evidence'][0]
    assert final['quote']=='K' and 'context_quote' not in final
    assert b.blocks[0].text[final['start_char']:final['end_char']]=='K'
    assert g==before and binding.scientific_payload(out['graph'])==binding.scientific_payload(g)
    assert out['edits'][0]['before']['context_quote']==e['context_quote']


@pytest.mark.parametrize('quote,context,code', [
    ('K','missing context','evidence_quote_unresolved_in_scope'),
    ('K','The criterion is onset.','evidence_quote_unresolved_in_scope'),
    ('set','The criterion is onset.','contextual_selector_clips_token'),
])
def test_context_locator_never_searches_elsewhere_or_clips_words(prepared,quote,context,code):
    g,b,s,m=case(prepared)
    g['results'][0]['evidence']=[dict(field='/quantity/unit',block_id=b.blocks[0].id,quote=quote,context_quote=context)]
    out=binding.compile_bindings(g,b,s,m)
    assert any(h['code']==code for h in out['holds'])
    assert 'context_quote' not in out['graph']['results'][0]['evidence'][0]
    assert out['edits'] # selector removal is logged even when resolution fails


@pytest.mark.parametrize('text,start,end,field,valid', [
    ('14.4',1,4,'/quantity/raw',False),('-1.16',1,5,'/quantity/raw',False),
    ('4.44',0,3,'/quantity/raw',False),('Tc / mK',6,7,'/quantity/unit',False),
    ('H / T/K',4,5,'/quantity/unit',False),('H / (T/K)',5,8,'/quantity/unit',True),
    ('Tc / K',5,6,'/quantity/unit',True),('Tc = 4.4.',5,8,'/quantity/raw',True),
])
def test_context_selector_token_boundaries(text,start,end,field,valid):
    assert binding.isolated_selector(text,start,end,field)==valid


def test_native_view_leaves_malformed_shapes_for_native_rejection():
    for value in [[],None,dict(results='bad'),dict(results=[None,dict(evidence=[None])])]:
        assert binding.native_graph(value)==value


@pytest.mark.parametrize('text,quote,field,expected', [
    ('Tc / K Hc2 / T slope / T/K','K','/quantity/unit',[(5,6)]),
    ('Tc / K Hc2 / T slope / T/K','T','/quantity/unit',[(13,14)]),
    ('Tc / K Tm / K','K','/quantity/unit',[(5,6),(12,13)]),
    ('14.4 and 4.4','4.4','/quantity/raw',[(9,12)]),
    ('-4.4 and 4.4','4.4','/quantity/raw',[(9,12)]),
    ('4.4 and 4.4','4.4','/quantity/raw',[(0,3),(8,11)]),
    ('mK and T/K','K','/quantity/unit',[]),
    ('T / K','K','/quantity/unit',[]),('T / K','T','/quantity/unit',[]),
    ('− 4.4 and 4.4','4.4','/quantity/raw',[(10,13)]),
])
def test_context_uniqueness_counts_whole_tokens_without_nearest_match(text,quote,field,expected):
    assert binding.contextual_positions(text,quote,0,len(text),field)==set(expected)
