"""Original direction fragments and mandatory applicability witnesses."""
from copy import deepcopy
import jsonschema
import pytest
from ingestion.materials_ner import staged_revision as revision,direction_witness
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.sources import Block,sha
from test_materials_ner_staged_revision import fixture,execute


def prepared(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    original=bundle.model_copy(deep=True)
    text='SYNTHETIC direction: $H$ $\\perp$ $c$ at 9 T. Contrast: $H$ $\\parallel$ $c$ at 12 T. Angle theta = 30 deg.'
    block=Block(id=bundle.blocks[0].id+':direction',document_id=bundle.blocks[0].document_id,
        ordinal=99,locator='synthetic:direction',text=text,sha256=sha(text.encode()))
    original.blocks.append(block)
    context=dict(original_bundle=original.model_dump(),selections=[dict(source_block_id=block.id,
        start_char=0,end_char=len(text),purpose='Synthetic direction witness',selection_basis='Synthetic original fragment.')])
    request['source_context']=context
    extended,proof=revision.source_bundle(parent,revision.SourceContext.model_validate(context))
    catalog=revision.source_catalog(extended);span=next(s for s,v in catalog['spans'].items() if v['block_id']==proof['added_blocks'][0]['block_id'])
    graph,_=revision.resolve_parent(parent);path='/states/0/conditions/0/orientation_raw'
    request['fields']=[dict(id='direction',path=path,expected_value_sha256=digest(revision.pointer(graph.model_dump(),path)),
        operation='replace',concern='Select the original direction, preserving the existing quantity.',source_span_ids=[span])]
    response.update(request_sha256=digest(request),read_context_block_ids=[proof['added_blocks'][0]['alias']],
        selections={'direction':dict(action='replace',value={'source_choice':'D1'},span_ids=[span],
        reason='Select the exact first source direction; this fixture does not grant scientific approval.',
        literal_witnesses=None,quantity_name_witness=None)})
    return store,extended,parent,request,response


def test_direction_copies_exact_original_coordinates_and_rejects_translated_text(tmp_path):
    store,bundle,parent,request,response=prepared(tmp_path)
    ctx=direction_witness.context(request['fields'][0]['path'],bundle,request['fields'][0]['source_span_ids'])
    assert [v['raw'] for v in ctx['choices'].values()]==['$H$ $\\perp$ $c$','$H$ $\\parallel$ $c$']
    for choice in ctx['choices'].values():
        block=next(b for b in bundle.blocks if b.id==choice['block_id'])
        assert block.text[choice['start_char']:choice['end_char']]==choice['raw']
    _,packet=execute(store,bundle,parent,request,response)
    before,_=revision.resolve_parent(parent);after,_=revision.resolve_parent(packet)
    assert after.states[0].conditions[0].orientation_raw=='$H$ $\\perp$ $c$'
    assert after.states[0].conditions[0].quantity==before.states[0].conditions[0].quantity
    assert after.observations==before.observations and not packet['scientific_acceptance']
    malformed=deepcopy(response);malformed['selections']['direction']['value']='$H$ = 9 T perpendicular to $c$'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(malformed,revision.output_schema(bundle,None,parent,review_request=request))
    with pytest.raises(ValueError,match='direction_source_choice_invalid'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(malformed),review_request=request,field_source_policy=direction_witness.POLICY)


def test_magnitude_or_unsupported_angle_is_not_a_direction_choice(tmp_path):
    _,bundle,_,request,_=prepared(tmp_path)
    # Source parser candidates are finite and preserve unknown notation.
    block=bundle.blocks[-1];text='SYNTHETIC H = 9 T; theta = 30 deg; no axis reported.'
    bundle=bundle.model_copy(deep=True);bundle.blocks[-1]=block.model_copy(update={'text':text,'sha256':sha(text.encode())})
    catalog=revision.source_catalog(bundle);span=next(s for s,v in catalog['spans'].items() if v['block_id']==block.id)
    assert direction_witness.context(request['fields'][0]['path'],bundle,[span])['choices']=={}


def test_missing_required_witness_cannot_be_replaced_by_an_unrelated_source_span(tmp_path):
    _,bundle,parent,request,response=prepared(tmp_path)
    # Both spans exist; the explicit replacement omits required original context.
    request['fields'][0]['source_span_ids'].insert(0,'S1')
    response['request_sha256']=digest(request)
    with pytest.raises(ValueError,match='required_source_span_missing'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request,field_source_policy=direction_witness.POLICY)


def test_component_literal_is_not_an_orientation_choice_object(tmp_path):
    store,bundle,parent,request,response=prepared(tmp_path)
    before,_=revision.resolve_parent(parent)
    path='/observations/0/result/component_raw'
    request['fields'][0].update(path=path,expected_value_sha256=digest(before.observations[0].result.component_raw))
    response['request_sha256']=digest(request)
    literal=r'$H$ $\parallel$ $c$'
    response['selections']['direction']['value']=literal
    assert direction_witness.context(path,bundle,request['fields'][0]['source_span_ids']) is None
    jsonschema.validate(response,revision.output_schema(bundle,None,parent,review_request=request))
    _,packet=execute(store,bundle,parent,request,response)
    after,_=revision.resolve_parent(packet)
    assert after.observations[0].result.component_raw==literal
    assert after.observations[0].result.quantity==before.observations[0].result.quantity
    assert after.states==before.states and not packet['scientific_acceptance']
