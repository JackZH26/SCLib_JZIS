"""Exact source-fragment selection; fixtures and same-source checks are not Gold."""
from copy import deepcopy

import jsonschema
import pytest

from ingestion.materials_ner import quantity_raw_witness as witness, staged_revision as revision
from ingestion.materials_ner.contract import Quantity, digest
from ingestion.materials_ner.sources import make_blocks
from test_materials_ner_numeric_presentation import raw_request
from test_materials_ner_staged_revision import execute


def q(**kwargs):
    return Quantity(status='reported', raw='old fallible draft', unit='nm', **kwargs)


@pytest.mark.parametrize('text,shape,expected', [
    (r'A junction with $d = 4.5$~nm was measured.', dict(relation='exact',value=4.5), r'4.5$~nm'),
    (r'$x=0.31 \pm 0.03$~nm.', dict(relation='exact',value=.31,uncertainty=dict(kind='reported_unspecified',minus=.03,plus=.03,raw=r'\pm 0.03')), r'0.31 \pm 0.03$~nm'),
    (r'The fit range is 1--3.5~nm.', dict(relation='interval',lower=1,upper=3.5), '1--3.5~nm'),
    ('Thicknesses between 0.5 and 4.5 nm.', dict(relation='interval',lower=.5,upper=4.5), 'between 0.5 and 4.5 nm'),
    (r'The bound is $x\lesssim 0.5$~nm.', dict(relation='le',upper=.5,approximate=True), r'\lesssim 0.5$~nm'),
    ('The bound is ≲0.5 nm.', dict(relation='le',upper=.5,approximate=True), '≲0.5 nm'),
    ('The bound is x<0.5 nm.', dict(relation='lt',upper=.5), '<0.5 nm'),
    ('A value of 1.2e-3 nm.', dict(relation='exact',value=.0012), '1.2e-3 nm'),
    ('The length is 0.50(3) nm.', dict(relation='exact',value=.5,uncertainty=dict(kind='reported_unspecified',minus=.03,plus=.03,raw='(3)')), '0.50(3) nm'),
])
def test_complete_source_numbers_retain_exact_bytes_and_offsets(text,shape,expected):
    quantity=q(**shape);before=quantity.model_dump();choices=list(witness.source_literals(text,quantity))
    assert len(choices)==1 and choices[0]['raw']==expected
    choice=choices[0]
    assert text[choice['start_char']:choice['end_char']]==expected
    assert choice['numeric_shape_matched'] and choice['explicit_unit_matched']
    assert quantity.model_dump()==before


@pytest.mark.parametrize('text', [
    '0.5 nm^2', r'0.5 nm$^{2}$', '0.5 nm / s', '0.5 nm s^-1',
    '0.5 nm ± 0.03', r'0.5 \pm 0.03 nm', '0.50(3) nm',
    '0.4 to 0.5 nm', '0.4--0.5 nm', 'between 0.4 and 0.5 nm',
    '0.4 nm to 0.5 nm', '0.5 nm and 0.6 nm',
    '0.4--0.6 nm', '1.5 nm', '0.5e-3 nm',
    '0.5 μm', '0.5', r'\approx 0.5 nm', r'x\approx0.5 nm', 'x<0.5 nm', '0.5 nm per second',
])
def test_partial_tokens_lists_units_uncertainty_or_approximations_do_not_fit_an_exact_point(text):
    assert not list(witness.source_literals(text,q(relation='exact',value=.5)))


def test_approximate_and_uncertain_frozen_values_cannot_select_an_exact_source():
    assert not list(witness.source_literals('0.5 nm',q(relation='exact',value=.5,approximate=True)))
    assert not list(witness.source_literals('0.5 nm',q(relation='exact',value=.5,
        uncertainty=dict(kind='reported_unspecified',minus=.03,plus=.03,raw='(3)'))))
    assert not list(witness.source_literals('0.5 nm',Quantity(status='not_reported')))
    assert not list(witness.source_literals('0.4~0.5 nm',q(relation='exact',value=.5,approximate=True)))


def selection_case(tmp_path):
    store,bundle,parent,request,response,quantity=raw_request(tmp_path)
    graph,_=revision.resolve_parent(parent)
    context=witness.context(graph,request['fields'][0]['path'],bundle)
    assert context['choices']
    key=next(iter(context['choices']))
    response['selections']['origin']['value']={'source_choice':key}
    return store,bundle,parent,request,response,context,key


def test_only_choice_is_returned_and_original_bytes_are_derived_and_replayed(tmp_path):
    store,bundle,parent,request,response,context,key=selection_case(tmp_path)
    schema=revision.output_schema(bundle,None,parent,review_request=request)
    jsonschema.validate(response,schema)
    _,packet=execute(store,bundle,parent,request,response)
    change=packet['receipt']['revision_audit']['changes'][0]
    assert change['selection']['value']=={'source_choice':key}
    assert change['after']==context['choices'][key]['raw']
    assert change['selected_quantity_raw_source']==context['choices'][key]
    assert change['quantity_raw_context']==context
    assert change['quantity_raw_guard']['numeric_semantics_unchanged']
    assert not change['quantity_raw_context']['scientific_acceptance']


@pytest.mark.parametrize('bad', ['39 K', {'source_choice':'Q999'}, {'source_choice':'Q1','raw':'39 K'},
                                {'source_choice':None}])
def test_retyped_forged_and_extra_source_values_are_rejected(tmp_path,bad):
    _,bundle,parent,request,response,_,_=selection_case(tmp_path)
    response['selections']['origin']['value']=bad
    checksum=digest(parent)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(response,revision.output_schema(bundle,None,parent,review_request=request))
    with pytest.raises(ValueError,match='quantity_raw_source_choice_invalid'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)
    assert digest(parent)==checksum


def test_other_source_blocks_are_not_choices_and_stale_graphs_cannot_apply(tmp_path):
    _,bundle,parent,request,response,context,_=selection_case(tmp_path)
    graph,_=revision.resolve_parent(parent)
    added=make_blocks(bundle.documents[0].id,[('synthetic:other-owner','Another synthetic sample has length 39 K.')])[0]
    added.id='synthetic:unowned:block';bundle.blocks.append(added)
    new=witness.context(graph,request['fields'][0]['path'],bundle)
    assert all(c['block_id']!=added.id for c in new['choices'].values())
    assert new['choices']==context['choices']
    bundle.blocks.pop()
    response['base_graph_sha256']='0'*64
    with pytest.raises(ValueError,match='response_binding_mismatch'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)


def test_wrong_source_hash_and_frozen_shape_do_not_create_choices(tmp_path):
    _,bundle,parent,request,_,_,_=selection_case(tmp_path)
    graph,_=revision.resolve_parent(parent)
    changed=deepcopy(graph);changed.observations[0].result.quantity.value=9876
    assert not witness.context(changed,request['fields'][0]['path'],bundle)['choices']
    bundle.blocks[0].text+=' modified'
    with pytest.raises(ValueError):
        witness.context(graph,request['fields'][0]['path'],bundle)


def test_no_supported_layout_allows_only_an_unresolved_decision(tmp_path):
    _,bundle,parent,request,response,_,_=selection_case(tmp_path)
    # Target a not-reported quantity using a narrow test graph override. This
    # tests generation policy independently of source retrieval/replay.
    from unittest.mock import patch
    graph,inventory=revision.resolve_parent(parent)
    graph.observations[0].result.quantity=Quantity(status='not_reported')
    request['fields'][0]['expected_value_sha256']=digest(None)
    with patch.object(revision,'resolve_parent',return_value=(graph,inventory)):
        schema=revision.output_schema(bundle,None,parent,review_request=request)
    actions=[b['properties']['action']['enum'] for b in schema['properties']['selections']['properties']['origin']['anyOf']]
    assert actions==[['unresolved']]
