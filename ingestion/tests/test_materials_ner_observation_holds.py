"""False-positive retirement preserves discovery, source and unaffected results."""
from copy import deepcopy
import pytest
from ingestion.materials_ner import staged_revision as revision,observation_holds,occurrence_audit
from ingestion.materials_ner.contract import digest
from test_materials_ner_staged_revision import fixture,execute
from test_materials_ner_direction_witness import prepared as with_context


def requested(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    graph,_=revision.resolve_parent(parent);old=graph.observations[1].model_dump()
    request['fields']=[dict(id='misclassified',path='/observations/1',expected_value_sha256=digest(old),
        operation='hold_observation',concern='Synthetic classification review: preserve the source item and original value.',source_span_ids=['S1'])]
    response.update(request_sha256=digest(request),selections={'misclassified':dict(action='hold_observation',
        value={'reason':'not_a_result','explanation':'Synthetic test of a model-proposed hold; this does not approve a scientific exclusion.'},
        span_ids=['S1'],reason='Retain the original occurrence for independent review.',literal_witnesses=None,quantity_name_witness=None)})
    return store,bundle,parent,request,response


def test_middle_observation_hold_preserves_ids_source_counts_and_replays(tmp_path):
    store,bundle,parent,request,response=requested(tmp_path)
    before,_=revision.resolve_parent(parent);original_hash=digest(parent)
    outcome,packet=execute(store,bundle,parent,request,response)
    after,_=revision.resolve_parent(packet)
    assert outcome['state']=='quarantined' and digest(parent)==original_hash
    assert [o.model_dump() for o in after.observations]==[o.model_dump() for i,o in enumerate(before.observations) if i!=1]
    assert after.samples==before.samples and after.states==before.states and after.protocols==before.protocols
    assert after.completion.outcome=='incomplete'
    held=after.unextracted_items[-1]
    assert held.item_id=='I2' and held.reason=='not_a_result'
    change=packet['receipt']['revision_audit']['changes'][0]
    assert change['before']==before.observations[1].model_dump()
    assert not change['observation_hold']['scientific_exclusion_approved']
    audit=occurrence_audit.audit_packet(packet)
    assert audit['original_item_count']==len(before.observations)
    assert audit['original_items_held']==1 and audit['original_items_missing']==0
    assert not audit['scientific_acceptance'] and not audit['ml_training_eligible']
    assert packet['bundle']==parent['bundle'] and not packet['scientific_acceptance']
    with pytest.raises(ValueError,match='precondition_mismatch'):
        bad=deepcopy(request);bad['fields'][0]['expected_value_sha256']=digest(before.observations[0].model_dump())
        revision.validate_request(bad,parent,bundle)


@pytest.mark.parametrize('edge',['dependency','support','context'])
def test_holding_result_cannot_silently_remove_dependent_facts(edge):
    data={'observations':[{'id':'r1','result':{'dependencies':[]}},
                          {'id':'r2','result':{'dependencies':[]}}],
        'context_dispositions':[],'condition_supports':[],'unextracted_items':[],
        'completion':{'outcome':'results','empty_reason':None}}
    if edge=='dependency':data['observations'][1]['result']['dependencies']=[{'result_id':'r1'}]
    if edge=='support':data['condition_supports']=[{'result_id':'r1'}]
    if edge=='context':data['context_dispositions']=[{'bindings':[{'entity':'definition','entity_id':'r1','field':'/criterion'}]}]
    before=deepcopy(data)
    with pytest.raises(ValueError,match='has_live_'):
        observation_holds.apply(data,[dict(observation_id='r1',unextracted_items=[dict(item_id='I1',reason='unresolved',explanation='Synthetic hold.')])])
    assert data==before


def test_a_different_source_occurrence_cannot_authorize_the_hold(tmp_path):
    _,bundle,parent,request,_=with_context(tmp_path)
    graph,inventory=revision.resolve_parent(parent)
    other=request['fields'][0]['source_span_ids']
    assert other!=['S1']
    with pytest.raises(ValueError,match='source_disconnected'):
        observation_holds.target(graph,inventory,bundle,'/observations/1',other)


def test_condition_support_requires_an_explicit_scoped_removal(tmp_path):
    _,bundle,parent,request,response=requested(tmp_path)
    graph,_=revision.resolve_parent(parent)
    # I3 has a stable geometry support edge in the existing synthetic fixture.
    request['fields'][0].update(path='/observations/2',expected_value_sha256=digest(graph.observations[2].model_dump()))
    response['request_sha256']=digest(request)
    with pytest.raises(ValueError,match='has_live_support'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)


def test_shared_inventory_claim_cannot_be_held_while_another_result_uses_it(tmp_path):
    _,bundle,parent,_,_=requested(tmp_path);graph,inventory=revision.resolve_parent(parent)
    ambiguous=graph.model_copy(deep=True)
    ambiguous.observations[0].inventory_item_ids=['I2']
    with pytest.raises(ValueError,match='item_still_emitted'):
        observation_holds.target(ambiguous,inventory,bundle,'/observations/1',['S1'])
