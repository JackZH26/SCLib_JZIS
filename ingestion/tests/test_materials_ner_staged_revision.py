"""Immutable staged parents, bounded scientific edits and original context."""
from copy import deepcopy
import json
import sqlite3

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import staged_revision as revision, item_worker
from ingestion.materials_ner.contract import digest,canonical
from ingestion.materials_ner.native_revision import configuration,run_one
from ingestion.materials_ner.proposals import ProposalDatabase,import_packet,verify_packet
from ingestion.materials_ner.providers import ProviderResult
from ingestion.materials_ner.sources import Block,save_bundle,sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one as initial_run
from test_materials_ner_catalog_stages import split_fixture
from test_materials_ner_item_stages import parent_packet,StageProvider
from test_materials_ner_inventory_v2 import SequenceProvider


def fixture(tmp_path,extra_condition=False,unmapped=False,stale_evidence=False):
    source_parent,_,_,_,_=parent_packet(tmp_path/'inventory')
    bundle,_,declarations,relations,decisions,links=split_fixture()
    if stale_evidence:
        declarations['samples'][0]['states'][0]['evidence'][0]['fields'].append('/conditions/99')
    # An intentionally erroneous model category, not a modified source assertion.
    first=next(iter(decisions.values()))['observation'];first['result']['origin']='computed'
    if unmapped:first['result'].update(quantity_kind='unmapped',quantity_name_raw='SYNTHETIC fitted scale')
    if extra_condition:
        condition=deepcopy(declarations['samples'][0]['states'][0]['conditions'][0])
        condition.update(kind='magnetic_flux_density',quantity=dict(status='ambiguous',raw='10 nA',unit='nA',
            relation=None,value=None,lower=None,upper=None,approximate=False,uncertainty=None))
        declarations['samples'][0]['states'][0]['conditions'].append(condition)
    keys=list(decisions)
    responses=[declarations,relations,*[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
        decisions={k:decisions[k] for k in keys[i:i+4]}) for i in range(0,len(keys),4)],links]
    store=Store(tmp_path/'staged');job=item_worker.enqueue(store,source_parent,workflow='source_item_stages_v2')
    initial_run(store,job_id=job,provider_override=StageProvider(responses))
    packet=import_packet(store,job);verify_packet(packet)
    graph,_=revision.resolve_parent(packet)
    target=dict(id='origin',path='/observations/0/result/origin',expected_value_sha256=digest('computed'),
        operation='replace',concern='Check origin against the synthetic original source.',source_span_ids=['S1'])
    request=dict(schema_version=revision.REQUEST_VERSION,parent_run_id=packet['run_id'],author_kind='assistant',
        fields=[target],source_context=None,prior_revision_run_ids=[])
    response=dict(schema_version=revision.VERSION,work_id=bundle.work_id,parent_run_id=packet['run_id'],
        base_graph_sha256=digest(graph.model_dump()),request_sha256=digest(request),read_context_block_ids=[],
        selections={'origin':dict(action='replace',value='observed',span_ids=['S1'],literal_witnesses=None,quantity_name_witness=None,reason='The source reports an observation.')})
    return store,bundle,packet,request,response


def execute(store,bundle,parent,request,response,*,invalid_provider_output=False):
    config=configuration(parent,mode='staged_fields',review_request=request)
    bundle_hash,_=save_bundle(store.root,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=config,max_attempts=1)
    response=deepcopy(response)
    for selection in response['selections'].values():
        selection.setdefault('literal_witnesses',None)
        selection.setdefault('quantity_name_witness',None)
    provider=SequenceProvider([response])
    if invalid_provider_output:
        # Test the application guard independently of generation-schema
        # enforcement. This provider is synthetic and intentionally malformed.
        class InvalidProvider:
            calls=0
            def extract(self,prompt,schema,config,directory):
                self.calls+=1
                return ProviderResult(canonical(response),{'input_tokens':10,'output_tokens':2},
                    'synthetic-invalid','gpt-6-luna','1',.01)
        provider=InvalidProvider()
    outcome=run_one(store,job,parent,bundle,mode='staged_fields',provider_override=provider)
    assert provider.calls==1
    packet=import_packet(store,job);verify_packet(packet)
    return outcome,packet


def test_exact_scientific_field_revision_is_replayable_quarantined_and_restorable(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    old=digest(parent);before,_=revision.resolve_parent(parent)
    schema=revision.output_schema(bundle,None,parent,review_request=request)
    jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(response,schema)
    outcome,packet=execute(store,bundle,parent,request,response)
    assert outcome['state']=='quarantined' and digest(parent)==old
    after,_=revision.resolve_parent(packet)
    expected=before.model_dump();expected['observations'][0]['result']['origin']='observed'
    expected['observations'][0]['result']['evidence']=after.model_dump()['observations'][0]['result']['evidence']
    assert after.model_dump()==expected
    assert packet['receipt']['revision_audit']['unlisted_scientific_fields_unchanged']
    assert {'code':'staged_field_revision_requires_scientific_review','path':'/'} in packet['receipt']['validation']['issues']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as conn,sqlite3.connect(tmp_path/'restored.sqlite3') as restored:
        conn.backup(restored)
        assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not restored.execute('PRAGMA foreign_key_check').fetchall()
        for row in restored.execute('select payload from runs'):verify_packet(json.loads(row[0]))
    # An unchanged later read must preserve the original and new proposal ancestry.
    nxt=deepcopy(request);nxt.update(parent_run_id=packet['run_id'],prior_revision_run_ids=[packet['run_id']])
    nxt['fields'][0]['expected_value_sha256']=digest('observed')
    second=dict(response,parent_run_id=packet['run_id'],base_graph_sha256=digest(after.model_dump()),request_sha256=digest(nxt),
        selections={'origin':dict(action='unchanged_supported',value=None,span_ids=['S1'],reason='Already source-supported in this synthetic fixture.')})
    _,again=execute(store,bundle,packet,nxt,second)
    assert revision.resolve_parent(again)[0]==after
    omitted=dict(nxt,prior_revision_run_ids=[])
    with pytest.raises(ValueError,match='request_binding'):revision.validate_request(omitted,packet,bundle)


def test_explicit_auxiliary_removal_preserves_every_other_condition_and_source(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path,extra_condition=True)
    graph,_=revision.resolve_parent(parent);conditions=graph.states[0].conditions
    index=len(conditions)-1;path=f'/states/0/conditions/{index}'
    request['fields']=[dict(id='duplicate',path=path,expected_value_sha256=digest(conditions[index].model_dump()),
        operation='remove',concern='Erroneous auxiliary condition; the source observation remains.',source_span_ids=['S1'])]
    response.update(request_sha256=digest(request),selections={'duplicate':dict(action='remove',value=None,
        span_ids=['S1'],reason='The original source does not support a magnetic field in current units.')})
    _,packet=execute(store,bundle,parent,request,response)
    after,_=revision.resolve_parent(packet)
    assert after.states[0].conditions==conditions[:-1] and after.observations==graph.observations
    assert parent['bundle']==packet['bundle']


def test_appended_original_context_preserves_old_aliases_and_records_new_read_scope(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    original=bundle.model_copy(deep=True)
    text='SYNTHETIC SECOND SECTION. The reported values were directly observed in this test fixture.'
    block=Block(id=bundle.blocks[0].id+':methods',document_id=bundle.blocks[0].document_id,
        ordinal=99,locator='synthetic:methods',text=text,sha256=sha(text.encode()))
    original.blocks.append(block)
    context=dict(original_bundle=original.model_dump(),selections=[dict(source_block_id=block.id,start_char=0,
        end_char=len(text),purpose='origin method',selection_basis='Synthetic source context test.')])
    request['source_context']=context
    extended,proof=revision.source_bundle(parent,revision.SourceContext.model_validate(context))
    old_catalog=revision.source_catalog(bundle);new_catalog=revision.source_catalog(extended)
    added_span=next(s for s in new_catalog['spans'] if s not in old_catalog['spans'])
    request['fields'][0]['source_span_ids']=[added_span]
    response['selections']['origin']['span_ids']=[added_span]
    response.update(request_sha256=digest(request),read_context_block_ids=[proof['added_blocks'][0]['alias']])
    _,packet=execute(store,extended,parent,request,response)
    after,_=revision.resolve_parent(packet)
    assert packet['bundle_hash']!=parent['bundle_hash']
    assert after.processed_block_ids[-1]==proof['added_blocks'][0]['alias']
    assert packet['receipt']['revision_audit']['context']['existing_source_aliases_unchanged']
    assert all(new_catalog['spans'][k]==v for k,v in old_catalog['spans'].items())
    coverage=packet['receipt']['inventory_coverage'];scope=coverage['source_scope']
    assert 'first_read_inventory_block_coverage_mismatch' not in {i['code'] for i in coverage['issues']}
    assert scope['first_read']['inventory_sha256']==digest(parent['receipt']['inventory'])
    assert scope['first_read']['block_ids']==list(old_catalog['blocks'])
    assert scope['revision_context']['declared_read_block_ids']==response['read_context_block_ids']
    assert not scope['revision_context']['counted_as_recall_gain']
    assert not scope['independent_recall_denominator_available']
    # A subsequent evidence review inherits the context read without claiming
    # either a new read or new result discovery in that block.
    later=deepcopy(request)
    later.update(parent_run_id=packet['run_id'],source_context=None,prior_revision_run_ids=[packet['run_id']])
    later['fields'][0]['expected_value_sha256']=digest('observed')
    again=dict(response,parent_run_id=packet['run_id'],base_graph_sha256=digest(after.model_dump()),
        request_sha256=digest(later),read_context_block_ids=[],
        selections={'origin':dict(action='bind_evidence',value=None,span_ids=[added_span],literal_witnesses={},reason='Retain the original source support.')})
    later['fields'][0]['operation']='bind_evidence';again['request_sha256']=digest(later)
    _,next_packet=execute(store,extended,packet,later,again)
    new_scope=next_packet['receipt']['inventory_coverage']['source_scope']
    assert new_scope['first_read']==scope['first_read']
    assert new_scope['revision_context']['declared_read_block_ids']==response['read_context_block_ids']
    assert new_scope['revision_context']['current_read_context_block_ids']==[]
    tampered=deepcopy(next_packet['receipt'])
    tampered['inventory_coverage']['source_scope']['first_read']['result_items']+=1
    with pytest.raises(ValueError,match='coverage_receipt_mismatch'):
        revision.verify_receipt(tampered,extended,next_packet['raw_output'])
    changed=deepcopy(context);changed['original_bundle']['documents'][0]['source_sha256']='1'*64
    with pytest.raises(ValueError,match='document_mismatch'):
        revision.source_bundle(parent,revision.SourceContext.model_validate(changed))


@pytest.mark.parametrize('mutation',['scope','id','whole_entity','precondition','duplicate','overlap','operation','spans','unlisted','read_scope','wrong_type','hash'])
def test_out_of_scope_or_wrong_typed_mutations_are_rejected_atomically(tmp_path,mutation):
    _,bundle,parent,request,response=fixture(tmp_path);f=request['fields'][0]
    if mutation=='scope':f['path']='/limitations'
    if mutation=='id':f['path']='/observations/0/id'
    if mutation=='whole_entity':f['path']='/observations/0'
    if mutation=='precondition':f['expected_value_sha256']='0'*64
    if mutation=='duplicate':request['fields'].append(deepcopy(f))
    if mutation=='overlap':request['fields'].append(dict(f,id='wider',path='/observations/0/result'))
    if mutation=='operation':response['selections']['origin'].update(action='remove',value=None)
    if mutation=='spans':response['selections']['origin']['span_ids']=['S99999']
    if mutation=='unlisted':response['selections']['other']=response['selections']['origin']
    if mutation=='read_scope':response['read_context_block_ids']=['B99999']
    if mutation=='wrong_type':response['selections']['origin']['value']=42
    response['request_sha256']=digest(request)
    if mutation=='hash':response['base_graph_sha256']='0'*64
    checksum=digest(parent)
    with pytest.raises((ValueError,KeyError,ValidationError)):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)
    assert digest(parent)==checksum


def test_unsupported_condition_removal_does_not_retarget_positional_evidence(tmp_path):
    _,bundle,parent,request,response=fixture(tmp_path,extra_condition=True)
    graph,_=revision.resolve_parent(parent)
    request['fields']=[dict(request['fields'][0],path='/states/0/conditions/0',operation='remove',
        expected_value_sha256=digest(graph.states[0].conditions[0].model_dump()))]
    response.update(request_sha256=digest(request))
    response['selections']['origin'].update(action='remove',value=None)
    with pytest.raises(ValueError,match='no_index_retargeting'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)


def test_generation_keeps_carried_context_cardinality_and_excludes_removed_targets(tmp_path):
    _,bundle,parent,request,response=fixture(tmp_path,extra_condition=True)
    graph,_=revision.resolve_parent(parent)
    index=next(i for i,c in enumerate(graph.context_dispositions) if c.resolution=='carried')
    last=len(graph.states[0].conditions)-1
    fields=[]
    for identifier,path,operation in [('bindings',f'/context_dispositions/{index}/bindings','replace'),
                                     ('bad_condition',f'/states/0/conditions/{last}','remove')]:
        fields.append(dict(request['fields'][0],id=identifier,path=path,operation=operation,
            expected_value_sha256=digest(revision.pointer(graph.model_dump(),path))))
    request['fields']=fields
    schema=revision.output_schema(bundle,None,parent,review_request=request)
    value=schema['properties']['selections']['properties']['bindings']['anyOf'][0]['properties']['value']
    assert value['minItems']==1
    candidate=[{'entity':'state','entity_id':graph.states[0].id,'field':f'/conditions/{last}'}]
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate([],value)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(candidate,value)
    jsonschema.validate([{'entity':'state','entity_id':graph.states[0].id,'field':'/conditions/0'}],value)


def test_generation_disallows_detection_position_on_fit_or_study_extent(tmp_path):
    _,bundle,parent,request,_=fixture(tmp_path)
    graph,_=revision.resolve_parent(parent)
    i,j=next((i,j) for i,s in enumerate(graph.states) for j,c in enumerate(s.conditions) if c.role!='detection_window')
    path=f'/states/{i}/conditions/{j}/window_position'
    request['fields']=[dict(request['fields'][0],path=path,expected_value_sha256=digest(revision.pointer(graph.model_dump(),path)))]
    schema=revision.output_schema(bundle,None,parent,review_request=request)
    value=schema['properties']['selections']['properties']['origin']['anyOf'][0]['properties']['value']
    assert value=={'type':'null'}


def test_null_field_decision_keeps_source_audit_without_binding_evidence_to_absence(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    graph,_=revision.resolve_parent(parent);path='/samples/0/substrate_raw'
    request['fields']=[dict(request['fields'][0],path=path,expected_value_sha256=digest(graph.samples[0].substrate_raw))]
    response.update(request_sha256=digest(request))
    response['selections']['origin']['value']=None
    typed=revision.NativeEdits.model_validate(response)
    current=revision.apply_edits(parent,bundle,typed,review_request=request)
    legacy=revision.apply_edits(parent,bundle,typed,review_request=request,field_evidence_policy='legacy_all_replacements')
    assert not any('/substrate_raw' in ref.fields for ref in current.revised_graph.samples[0].evidence)
    assert any('/substrate_raw' in ref.fields for ref in legacy.revised_graph.samples[0].evidence)
    assert current.audit['changes'][0]['source_quotes']==legacy.audit['changes'][0]['source_quotes']
    assert current.audit['field_evidence_policy']=='non_null_fields_v2'
    assert 'field_evidence_policy' not in legacy.audit
    _,packet=execute(store,bundle,parent,request,response)
    assert packet['receipt']['config']['field_evidence_policy']=='non_null_fields_v2'
    assert revision.resolve_parent(packet)[0]==current.revised_graph


def test_evidence_only_owner_binding_preserves_values_and_cannot_mutate_data(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    before,inventory=revision.resolve_parent(parent)
    path='/states/0/conditions/0'
    request['fields']=[dict(request['fields'][0],operation='bind_evidence',path=path,
        expected_value_sha256=digest(revision.pointer(before.model_dump(),path)))]
    response.update(request_sha256=digest(request))
    response['selections']['origin'].update(action='bind_evidence',value=None)
    response['selections']['origin']['literal_witnesses']={p:'W1' for p in revision.literal_claims(revision.pointer(before.model_dump(),path),path)}
    schema=revision.output_schema(bundle,inventory,parent,review_request=request)
    jsonschema.validate(response,schema)
    _,packet=execute(store,bundle,parent,request,response)
    after,_=revision.resolve_parent(packet)
    expected=before.model_dump();expected['states'][0]['evidence']=after.model_dump()['states'][0]['evidence']
    assert expected==after.model_dump()
    assert any(ref.fields==['/conditions/0'] and ref.span_ids==['S1'] for ref in after.states[0].evidence)
    change=packet['receipt']['revision_audit']['changes'][0]
    assert change['before']==change['after'] and not change['changed']
    assert change['selection']['action']=='bind_evidence' and change['source_quotes']
    changed=deepcopy(response);changed['selections']['origin']['value']={'kind':'pressure'}
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(changed,schema)
    with pytest.raises(ValueError,match='nonreplacement_has_value'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(changed),review_request=request)
    changed=deepcopy(response);changed['selections']['origin']['action']='replace'
    with pytest.raises(ValueError,match='operation_not_requested'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(changed),review_request=request)


@pytest.mark.parametrize('path',['/samples/0','/observations/0/result','/observations/0/id',
    '/states/0/conditions','/states/0/evidence','/samples/0/substrate_raw','/context_dispositions/0/bindings'])
def test_evidence_only_rejects_missing_and_non_scientific_owners(tmp_path,path):
    _,bundle,parent,request,_=fixture(tmp_path)
    request['fields']=[dict(request['fields'][0],operation='bind_evidence',path=path)]
    with pytest.raises(ValueError,match='evidence_target_invalid'):
        revision.validate_request(request,parent,bundle)


def test_rebased_inventory_validation_keeps_genuine_original_read_holds(tmp_path):
    _,bundle,parent,_,_=fixture(tmp_path)
    graph,inventory=revision.resolve_parent(parent)
    # Unit-check the coverage function with a deliberately incomplete inventory;
    # this is not a valid import packet and cannot pass parent reconstruction.
    incomplete=inventory.model_copy(deep=True)
    unread=incomplete.processed_block_ids.pop();incomplete.unread_block_ids.append(unread)
    copied=deepcopy(parent);copied['receipt']['inventory']=incomplete.model_dump()
    report=revision.validate_coverage(graph,incomplete,bundle,parent=copied)
    assert 'first_read_inventory_unread_blocks' in {i['code'] for i in report['issues']}
    assert not report['valid']
    assert report['source_scope']['first_read']['unread_block_ids']==[unread]


def test_evidence_binding_cannot_certify_nonliteral_owner_wording(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    graph,_=revision.resolve_parent(parent)
    path='/observations/0/definition/criterion_raw'
    request['fields']=[dict(request['fields'][0],path=path,
        expected_value_sha256=digest(revision.pointer(graph.model_dump(),path)))]
    response.update(request_sha256=digest(request))
    response['selections']['origin']['value']='SYNTHETIC NONLITERAL CRITERION ADDED BY A FALLIBLE MODEL'
    _,fallible=execute(store,bundle,parent,request,response)
    graph,_=revision.resolve_parent(fallible)
    request.update(parent_run_id=fallible['run_id'],prior_revision_run_ids=[fallible['run_id']])
    request['fields'][0].update(operation='bind_evidence',expected_value_sha256=digest(response['selections']['origin']['value']))
    response.update(parent_run_id=fallible['run_id'],base_graph_sha256=digest(graph.model_dump()),request_sha256=digest(request))
    response['selections']['origin'].update(action='bind_evidence',value=None)
    schema=revision.output_schema(bundle,None,fallible,review_request=request)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(response,schema)
    with pytest.raises(ValueError,match='binding_literal_not_supported'):
        revision.apply_edits(fallible,bundle,revision.NativeEdits.model_validate(response),review_request=request,
                             literal_witness_policy=None,binding_failure_policy=None)
    # Legacy receipts remain replayable under their pinned absence of this
    # guard. That compatibility does not make their evidence scientifically valid.
    historical=revision.apply_edits(fallible,bundle,revision.NativeEdits.model_validate(response),
        review_request=request,evidence_binding_policy=None,literal_witness_policy=None,binding_failure_policy=None)
    assert historical.revised_graph.observations[0].definition.criterion_raw==graph.observations[0].definition.criterion_raw
    response['selections']['origin'].update(action='unresolved',reason='The existing raw string is absent from the original source.')
    jsonschema.validate(response,schema)
    _,unresolved=execute(store,bundle,fallible,request,response)
    assert revision.resolve_parent(unresolved)[0]==graph


def test_literal_owner_checks_include_prose_but_leave_quantity_notation_to_numeric_validator():
    claims=revision.literal_claims({'basis_raw':'literal basis','quantity':{'status':'reported','relation':'interval',
        'raw':'1--3.5~nm','uncertainty':{'raw':'numeric notation'}},'sensitivities':[{'raw':'10 nA current step'}]},'/owner')
    assert claims=={'/owner/basis_raw':'literal basis','/owner/sensitivities/0/raw':'10 nA current step'}


def independent_binding_case(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    graph,_=revision.resolve_parent(parent);literal=' '.join(bundle.blocks[0].text.split()[:4])
    original=bundle.model_copy(deep=True);text='SYNTHETIC unrelated context with no matching literal.'
    block=Block(id=bundle.blocks[0].id+':other',document_id=bundle.blocks[0].document_id,
        ordinal=99,locator='synthetic:other',text=text,sha256=sha(text.encode()));original.blocks.append(block)
    context=dict(original_bundle=original.model_dump(),selections=[dict(source_block_id=block.id,start_char=0,
        end_char=len(text),purpose='Unrelated context',selection_basis='Synthetic wrong-source binding test.')])
    request['source_context']=context
    extended,proof=revision.source_bundle(parent,revision.SourceContext.model_validate(context))
    wrong_span=next(k for k in revision.source_catalog(extended)['spans'] if k not in revision.source_catalog(bundle)['spans'])
    path='/observations/0/definition/criterion_raw'
    request['fields']=[dict(request['fields'][0],path=path,expected_value_sha256=digest(revision.pointer(graph.model_dump(),path)))]
    response.update(request_sha256=digest(request),read_context_block_ids=[proof['added_blocks'][0]['alias']])
    response['selections']['origin'].update(value=literal)
    _,parent=execute(store,extended,parent,request,response);graph,_=revision.resolve_parent(parent)
    fields=[]
    for identifier,p in [('bad_literal',path),('good_quantity','/observations/0/result/quantity')]:
        fields.append(dict(request['fields'][0],id=identifier,path=p,operation='bind_evidence',
            expected_value_sha256=digest(revision.pointer(graph.model_dump(),p))))
    request.update(parent_run_id=parent['run_id'],fields=fields,source_context=None,prior_revision_run_ids=[parent['run_id']])
    response.update(parent_run_id=parent['run_id'],base_graph_sha256=digest(graph.model_dump()),
        request_sha256=digest(request),read_context_block_ids=[],selections={
        'bad_literal':dict(action='bind_evidence',value=None,span_ids=[wrong_span],literal_witnesses={path:'W999'},
            reason='A deliberately wrong-source selection in a synthetic fixture.'),
        'good_quantity':dict(action='bind_evidence',value=None,span_ids=['S1'],literal_witnesses={},
            reason='The original quantity keeps its source binding.')})
    for selection in response['selections'].values():selection['quantity_name_witness']=None
    return store,extended,parent,request,response,wrong_span


def test_wrong_literal_witness_is_rejected_without_losing_other_independent_evidence(tmp_path):
    store,bundle,parent,request,response,_=independent_binding_case(tmp_path)
    before,_=revision.resolve_parent(parent);checksum=digest(parent)
    schema=revision.output_schema(bundle,None,parent,review_request=request)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(response,schema)
    outcome,packet=execute(store,bundle,parent,request,response,invalid_provider_output=True)
    after,_=revision.resolve_parent(packet);audit=packet['receipt']['revision_audit']
    assert outcome['state']=='quarantined' and digest(parent)==checksum
    assert len(after.observations)==len(before.observations)
    assert after.observations[0].definition==before.observations[0].definition
    assert audit['changes'][0]['binding_outcome']=='rejected'
    assert audit['changes'][1]['binding_outcome']=='applied'
    assert audit['rejected_field_bindings'][0]['target_id']=='bad_literal'
    assert 'staged_field_literal_witness_invalid' in audit['rejected_field_bindings'][0]['codes']
    assert {'code':'staged_field_evidence_binding_rejected','path':request['fields'][0]['path']} in packet['receipt']['validation']['issues']
    expected=before.model_dump();expected['observations'][0]['result']['evidence']=after.model_dump()['observations'][0]['result']['evidence']
    assert expected==after.model_dump()
    db=ProposalDatabase(tmp_path/'partial-private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as conn,sqlite3.connect(tmp_path/'partial-restored.sqlite3') as restored:
        conn.backup(restored);assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not restored.execute('PRAGMA foreign_key_check').fetchall()
        for payload, in restored.execute('SELECT payload FROM runs'):verify_packet(json.loads(payload))
    tampered=deepcopy(packet['receipt']);tampered['revision_audit']['rejected_field_bindings']=[]
    with pytest.raises(ValueError,match='receipt_reconstruction_mismatch'):
        revision.verify_receipt(tampered,bundle,packet['raw_output'])


def test_valid_literal_witness_and_distinct_context_are_both_retained(tmp_path):
    store,bundle,parent,request,response,context=independent_binding_case(tmp_path)
    path=request['fields'][0]['path'];response['selections']['bad_literal']['literal_witnesses']={path:'W1'}
    schema=revision.output_schema(bundle,None,parent,review_request=request);jsonschema.validate(response,schema)
    _,packet=execute(store,bundle,parent,request,response)
    change=packet['receipt']['revision_audit']['changes'][0]
    assert change['binding_outcome']=='applied' and change['effective_span_ids']==[context,'S1']
    assert change['selection']['span_ids']==[context]
    assert change['selection']['literal_witnesses']=={path:'W1'}
    assert not packet['receipt']['revision_audit']['rejected_field_bindings']


def test_mixed_value_and_evidence_revision_is_still_atomic(tmp_path):
    _,bundle,parent,request,response,_=independent_binding_case(tmp_path)
    graph,_=revision.resolve_parent(parent);path='/observations/0/result/origin'
    request['fields'][1].update(path=path,operation='replace',expected_value_sha256=digest(graph.observations[0].result.origin))
    response['selections']['good_quantity'].update(action='replace',value='observed',literal_witnesses=None)
    request['fields'].reverse()
    response['request_sha256']=digest(request);checksum=digest(parent)
    with pytest.raises(ValueError,match='literal_witness_invalid'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)
    assert digest(parent)==checksum


def test_literal_witness_can_span_a_partition_but_never_a_document_block_boundary(tmp_path):
    from types import SimpleNamespace
    _,bundle,_,_,_=fixture(tmp_path)
    literal='FIRSTLITERAL SECONDLITERAL'
    text='x'*887+literal+' end'
    source=bundle.model_copy(deep=True);source.blocks[0].text=text;source.blocks[0].sha256=sha(text.encode())
    graph=SimpleNamespace(model_dump=lambda:{'label_raw':literal})
    support=revision.literal_support(graph,'/label_raw',source)['/label_raw']
    assert support['supporting_span_sets']==[['S1','S2']]
    first=source.blocks[0];first.text='FIRSTLITERAL ';first.sha256=sha(first.text.encode())
    second=first.model_copy(update=dict(id=first.id+':split',ordinal=99,locator='synthetic:split',text='SECONDLITERAL',sha256=sha(b'SECONDLITERAL')))
    source.blocks=[first,second]
    assert revision.literal_support(graph,'/label_raw',source)['/label_raw']['supporting_span_sets']==[]
    empty=SimpleNamespace(model_dump=lambda:{'label_raw':'  '})
    assert revision.literal_support(empty,'/label_raw',source)['/label_raw']['supporting_span_sets']==[]


def test_unmapped_quantity_name_cannot_be_cleared_by_a_nullable_raw_field_edit(tmp_path):
    _,bundle,parent,request,response=fixture(tmp_path,unmapped=True)
    graph,_=revision.resolve_parent(parent);path='/observations/0/result/quantity_name_raw'
    request['fields']=[dict(request['fields'][0],path=path,expected_value_sha256=digest(graph.observations[0].result.quantity_name_raw))]
    response.update(request_sha256=digest(request));schema=revision.output_schema(bundle,None,parent,review_request=request)
    for value in (None,'','   '):
        response['selections']['origin']['value']=value
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate(response,schema)
        with pytest.raises((ValidationError,ValueError)):
            revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)
    response['selections']['origin'].update(action='unresolved',value=None)
    jsonschema.validate(response,schema)
    assert revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request).revised_graph==graph
