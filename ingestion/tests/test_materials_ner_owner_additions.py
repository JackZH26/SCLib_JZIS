"""Owner repair preserves shared experiments, quantities and historical proposals."""
from copy import deepcopy
import jsonschema
import pytest
from pydantic import ValidationError
from ingestion.materials_ner import staged_revision as revision,owner_additions
from ingestion.materials_ner.contract import digest
from test_materials_ner_staged_revision import fixture,execute


def requested(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    graph,_=revision.resolve_parent(parent);raw=graph.model_dump()
    fields=[];selections={};owners={}
    for group in ('samples','states','protocols'):
        target=dict(id=group,path='/'+group,operation='append_owner',source_span_ids=['S1'],
            expected_value_sha256=digest(raw[group]),concern='Synthetic source-scoped owner repair.')
        fields.append(target)
        spec=owner_additions.spec(graph,parent['run_id'],revision.FieldTarget.model_validate(target))
        value=deepcopy(raw[group][0]);value['id']=spec['assigned_id']
        if group=='states':value.update(sample_id=owners['samples']['id'],conditions=[],evidence=[])
        if group=='protocols':value.update(method=None,method_class='unspecified',observable=None,details_raw=None,parameters=[],context_uses=[],evidence=[])
        owners[group]=value
        selections[group]=dict(action='append_owner',value=value,span_ids=['S1'],reason='Synthetic unknown owner, not scientific acceptance.',literal_witnesses=None,quantity_name_witness=None)
    for group,reference in [('samples','sample_id'),('states','state_id'),('protocols','protocol_id')]:
        path='/observations/0/'+reference
        fields.append(dict(id=reference,path=path,operation='replace',source_span_ids=['S1'],
            expected_value_sha256=digest(revision.pointer(raw,path)),concern='Rebind this synthetic result only.'))
        selections[reference]=dict(action='replace',value=owners[group]['id'],span_ids=['S1'],reason='Synthetic explicit reference repair.',literal_witnesses=None,quantity_name_witness=None)
    request['fields']=fields;response.update(request_sha256=digest(request),selections=selections)
    return store,bundle,parent,request,response


def test_new_owners_and_references_replay_without_changing_shared_nmr_graph(tmp_path):
    store,bundle,parent,request,response=requested(tmp_path);before,_=revision.resolve_parent(parent);old=digest(parent)
    schema=revision.output_schema(bundle,None,parent,review_request=request)
    jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(response,schema)
    outcome,packet=execute(store,bundle,parent,request,response)
    after,_=revision.resolve_parent(packet)
    assert outcome['state']=='quarantined' and digest(parent)==old and packet['bundle']==parent['bundle']
    for group in ['samples','states','protocols']:
        assert getattr(after,group)[:-1]==getattr(before,group)
        assert len(getattr(after,group))==len(getattr(before,group))+1
    assert after.observations[1:]==before.observations[1:]
    assert after.observations[0].result.model_dump(exclude={'evidence'})==before.observations[0].result.model_dump(exclude={'evidence'})
    assert after.observations[0].id==before.observations[0].id
    assert after.observations[0].inventory_item_ids==before.observations[0].inventory_item_ids
    assert after.condition_supports==before.condition_supports and after.unextracted_items==before.unextracted_items
    assert after.protocols[-1].method is None and after.protocols[-1].method_class=='unspecified'
    assert after.states[-1].conditions==[]
    audit=packet['receipt']['revision_audit']['owner_additions']
    assert len(audit['additions'])==3 and not audit['scientific_acceptance']
    assert all(x['referenced_by_observations']==[before.observations[0].id] for x in audit['additions'])
    assert {'code':'staged_owner_revision_requires_scientific_review','path':'/'} in packet['receipt']['validation']['issues']


@pytest.mark.parametrize('fault,pattern',[
    ('old_id','identity_mismatch'),('unused','has_no_result_binding'),
    ('not_requested','operation_not_requested'),('missing_source','changed_value_has_no_source'),
    ('decline_with_value','nonreplacement_has_value'),('dangling_state','state')])
def test_addition_rejects_identity_scope_source_and_reference_failures(tmp_path,fault,pattern):
    _,bundle,parent,request,response=requested(tmp_path);changed=deepcopy(response)
    if fault=='old_id':changed['selections']['protocols']['value']['id']='protocol:1'
    if fault=='unused':
        changed['selections']['protocol_id'].update(action='unresolved',value=None)
    if fault=='not_requested':changed['selections']['sample_id']['action']='append_owner'
    if fault=='missing_source':changed['selections']['protocols']['span_ids']=[]
    if fault=='decline_with_value':changed['selections']['protocols']['action']='unresolved'
    if fault=='dangling_state':changed['selections']['states']['value']['sample_id']='not-a-source-sample'
    with pytest.raises((ValueError,ValidationError),match=pattern):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(changed),review_request=request)


def test_additions_use_exact_collection_preconditions_and_declared_ids(tmp_path):
    _,bundle,parent,request,response=requested(tmp_path)
    wrong=deepcopy(request);wrong['fields'][0]['expected_value_sha256']=digest([])
    with pytest.raises(ValueError,match='precondition_mismatch'):revision.validate_request(wrong,parent,bundle)
    wrong=deepcopy(request);wrong['fields'][0]['path']='/observations'
    wrong['fields']=wrong['fields'][:1]
    with pytest.raises(ValueError,match='addition_scope_invalid'):revision.validate_request(wrong,parent,bundle)
    wrong=deepcopy(response);wrong['selections']['protocol_id']['value']='invented-owner'
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(wrong,revision.output_schema(bundle,None,parent,review_request=request))


def test_a_declined_addition_preserves_the_existing_graph_and_inventory(tmp_path):
    _,bundle,parent,request,response=requested(tmp_path);before,_=revision.resolve_parent(parent)
    for s in response['selections'].values():s.update(action='unresolved',value=None)
    applied=revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)
    assert applied.revised_graph==before and 'owner_additions' not in applied.audit
