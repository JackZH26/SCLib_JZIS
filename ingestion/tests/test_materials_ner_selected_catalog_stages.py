"""Exact source selections, append-only catalog proposals and durable failures.

Test-authored coordinate selections and appended objects are regression inputs,
not fresh model responses, independent annotations or scientific acceptance.
"""
from copy import deepcopy

import jsonschema
import pytest

from materials_private_fixtures import private_json

from ingestion.materials_ner import selected_catalog_stages as selected, identity_stages as identity
from ingestion.materials_ner import item_worker,staged_revision
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.contract_v9 import ExtractionV9
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.sources import Bundle,sha
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.proposals import import_packet,verify_packet,ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_frozen_owner_stages import typed
from test_materials_ner_item_stages import parent_packet,StageProvider


def failure(window=2,policy='source_fields_v4'):
    return next(c for c in private_json('materials_ner_source_selection_failures.json')['cases'] if c['window']==window and c['policy']==policy)


def selected_body(decl):
    data=decl.model_dump();data['schema_version']='materials-selected-source-declarations/1'
    for item in data['additional_source_items']:
        item.pop('value_raw');item['value_selection']=None
    return selected.Declarations.model_validate(data)


def no_completion(decl):
    catalog,_=identity.declare(decl)
    return selected.CatalogCompletion(schema_version=selected.COMPLETION_VERSION,work_id=decl.work_id,
        declared_catalog_sha256=digest(catalog.model_dump()),state_additions=[],samples=[],protocols=[],limitations=[],
        no_additions_reason='No additional source-supported objects proposed in this regression fixture.')


def exact_selection(bundle,span_id,literal):
    source,tokens=selected.source_tokens(bundle);text=source['spans'][span_id]['text']
    start=text.index(literal);end=start+len(literal)
    return dict(span_id=span_id,start_token=next(i for i,t in enumerate(tokens[span_id]) if t['start_char']==start),
        end_token=next(i+1 for i,t in enumerate(tokens[span_id]) if t['end_char']==end))


def actual_selected():
    case=failure();bundle=Bundle.model_validate(case['bundle']);inventory=Inventory.model_validate(case['inventory'])
    raw=selected_body(identity.Declarations.model_validate(case['outputs']['declarations'])).model_dump()
    literals=[('S9','negligible'),('S9',r'the superconductivity is fully suppressed (with $H$ $\parallel $ $c$ $\geq$ $H_{c2}$ = 6 T)'),
        ('S10',r'no $H$-dependence'),('S11',r'there is no significant change of $^{63}K(T)$ across $T_{c}$ (at $H$ $\perp$ $c$)')]
    for item,(span,literal) in zip(raw['additional_source_items'],literals):
        item['value_selection']=exact_selection(bundle,span,literal)
    return bundle,inventory,raw,literals


def test_real_retyped_tex_failure_can_be_copied_exactly_without_rewriting_source_or_dropping_targets():
    bundle,inventory,raw,literals=actual_selected();before=bundle.model_dump()
    decl=selected.Declarations.model_validate(raw);schema=selected.declaration_schema(bundle,inventory)
    jsonschema.validate(raw,schema)
    projected,proof=selected.project_declarations(decl,bundle)
    identity.check_declarations(projected,inventory,bundle,8,strict_field_owner=False)
    assert [i.value_raw for i in projected.additional_source_items]==[s for _,s in literals]
    assert len(proof['entries'])==4 and bundle.model_dump()==before
    assert not proof['derived_literal_is_model_generated'] and not proof['scientific_meaning_verified']
    for item,entry in zip(projected.additional_source_items,proof['entries']):
        witness=entry['witness'];block=next(b for b in bundle.blocks if b.id==witness['block_id'])
        assert block.text[witness['block_start_char']:witness['block_end_char']]==item.value_raw
        assert witness['value_raw_sha256']==sha(item.value_raw.encode())
    assert 'value_raw' not in schema['$defs']['SelectedAddition']['properties']
    assert 'SOURCE_TOKEN_INDEX:' in selected.render_declarations(bundle,inventory)


@pytest.mark.parametrize('mutation',['foreign_span','unchosen_span','equal','reverse','beyond_end','negative','boolean'])
def test_selection_cannot_silently_read_other_source_or_invalid_bounds(mutation):
    bundle,_,raw,_=actual_selected();item=raw['additional_source_items'][0];choice=item['value_selection']
    if mutation=='foreign_span':choice['span_id']='S999999'
    elif mutation=='unchosen_span':choice.update(exact_selection(bundle,'S10',r'no $H$-dependence'))
    elif mutation=='equal':choice['end_token']=choice['start_token']
    elif mutation=='reverse':choice['end_token']=1
    elif mutation=='beyond_end':choice['end_token']=100000
    elif mutation=='negative':choice['start_token']=-1
    else:choice['start_token']=True
    with pytest.raises(ValueError):selected.project_declarations(selected.Declarations.model_validate(raw),bundle)


def test_null_selection_retains_assertion_and_is_not_negative_or_not_reported():
    bundle,inventory,raw,_=actual_selected()
    raw['additional_source_items'][1]['value_selection']=None
    decl,proof=selected.project_declarations(selected.Declarations.model_validate(raw),bundle)
    identity.check_declarations(decl,inventory,bundle,8,strict_field_owner=False)
    assert len(decl.additional_source_items)==4 and decl.additional_source_items[1].value_raw is None
    assert proof['entries'][1]['selection_status']=='not_selected' and proof['entries'][1]['witness'] is None
    assert decl.additional_source_items[1].source_span_ids==['S9','S11']


def test_appended_state_cannot_change_existing_tc_field_pairs_or_operational_ids():
    case=failure(4);bundle=Bundle.model_validate(case['bundle']);inventory=Inventory.model_validate(case['inventory'])
    decl=identity.Declarations.model_validate(case['outputs']['declarations']);before=decl.model_dump()
    completion=no_completion(decl).model_dump();state=deepcopy(before['samples'][0]['states'][0])
    state['conditions']=[]
    # Deliberately a regression proposal, not an adjudicated Hc2 state.
    completion.update(state_additions=[dict(sample_id='sample:1',states=[state])],no_additions_reason=None)
    initial,_=identity.declare(decl);typed_completion=selected.CatalogCompletion.model_validate(completion)
    jsonschema.validate(completion,selected.completion_schema(bundle,initial))
    final,catalog,proof=selected.complete(decl,typed_completion,inventory,bundle,8,strict_field_owner=False)
    assert decl.model_dump()==before and final.samples[0].states[:-1]==decl.samples[0].states
    for old in initial.states:
        assert next(s for s in catalog.states if s.id==old.id)==old
    assert proof['prior_scientific_fields_unchanged'] and proof['new_scientific_fields_are_model_proposals']
    assert proof['added_entities']==1 and not proof['scientific_acceptance']
    assert final.protocols==decl.protocols and final.additional_source_items==decl.additional_source_items


@pytest.mark.parametrize('mutation',['hash','sample','duplicate','budget','overwritten_field','empty_without_reason','addition_with_reason'])
def test_completion_is_parent_bound_append_only_and_bounded(mutation):
    bundle,inventory,decl,_,_,_,_,_=typed();data=no_completion(decl).model_dump()
    state=decl.samples[0].states[0].model_dump()
    if mutation=='hash':data['declared_catalog_sha256']='0'*64
    elif mutation=='empty_without_reason':data['no_additions_reason']=None
    else:
        data.update(state_additions=[dict(sample_id='sample:1',states=[state])],no_additions_reason=None)
        if mutation=='sample':data['state_additions'][0]['sample_id']='foreign'
        elif mutation=='duplicate':data['state_additions']*=2
        elif mutation=='budget':data['state_additions'][0]['states']=[state]*65
        elif mutation=='overwritten_field':data['state_additions'][0]['formula_raw']='FeSe'
        elif mutation=='addition_with_reason':data['no_additions_reason']='Inconsistent decision.'
    with pytest.raises(ValueError):selected.complete(decl,selected.CatalogCompletion.model_validate(data),inventory,bundle,8,strict_field_owner=False)


@pytest.mark.parametrize('method',[None,'resistivity',r'\muSR','.', '123','---'])
def test_method_lexical_guard_preserves_null_and_named_technique_macros(method):
    case=failure(4,'source_fields_v3');data=deepcopy(case['extraction']);data['protocols'][1]['method']=method
    report=validate_extraction(ExtractionV9.model_validate(data),Bundle.model_validate(case['bundle']))
    expected=method in {'.','123','---'}
    assert (dict(code='method_no_identity_token',path='/protocols/1/method') in report['issues'])==expected
    bundle,inventory,decl,_,_,_,_,_=typed();raw=selected_body(decl).model_dump();p=raw['protocols'][0];p['method']=method
    if method is None:
        p['method_class']='unspecified'
        for evidence in p['evidence']:evidence['fields']=[f for f in evidence['fields'] if f!='/method']
        p['evidence']=[e for e in p['evidence'] if e['fields']]
    if expected:
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw,selected.declaration_schema(bundle,inventory))
    else:jsonschema.validate(raw,selected.declaration_schema(bundle,inventory))


def worker_outputs():
    bundle,inventory,decl,rel,catalog,selection,decisions,links=typed();keys=list(decisions)
    outputs=[selected_body(decl).model_dump(),no_completion(decl).model_dump(),rel.model_dump(),selection.model_dump(),
        *[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
            decisions={k:decisions[k] for k in keys[i:i+4]}) for i in range(0,len(keys),4)],links]
    return bundle,outputs


@pytest.mark.parametrize('failure_at',[None,1,2,3,4,5,6,7])
def test_worker_retains_every_stage_failure_and_private_revision_replay(tmp_path,failure_at):
    parent,_,_,_,_=parent_packet(tmp_path/'parent');bundle,outputs=worker_outputs();assert len(outputs)==7
    store=Store(tmp_path/'selected');job=item_worker.enqueue(store,parent,workflow=selected.WORKFLOW)
    outcome=run_one(store,job_id=job,provider_override=StageProvider(outputs,fail_at=failure_at))
    assert outcome['state']==('failed' if failure_at else 'succeeded'),outcome
    packet=import_packet(store,job);verify_packet(packet)
    assert len(packet['rows']['results'])=={None:5,1:0,2:0,3:0,4:0,5:0,6:4,7:5}[failure_at]
    db=ProposalDatabase(tmp_path/'private');assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    if not failure_at:
        graph,_=staged_revision.resolve_parent(packet);assert graph.expand(bundle).model_dump()==packet['receipt']['extraction']
        for key in ('source_selection_projection','catalog_completion_projection'):
            damaged=deepcopy(packet['receipt']);damaged[key]['tampered']=True
            with pytest.raises(ValueError,match='assembly_mismatch'):item_worker.verify_receipt(damaged,bundle,packet['raw_output'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


def test_invalid_completion_stops_before_any_owner_or_result_call(tmp_path):
    parent,_,_,_,_=parent_packet(tmp_path/'parent');bundle,outputs=worker_outputs()
    outputs[1]['declared_catalog_sha256']='0'*64
    class InvalidCompletionProvider(StageProvider):
        def extract(self,prompt,schema,config,directory):
            # Simulate an invalid provider reply; leave the actual requested
            # schema and captured input intact for receipt verification.
            if self.calls==1:
                schema=deepcopy(schema);schema['properties']['declared_catalog_sha256'].pop('enum')
            return super().extract(prompt,schema,config,directory)
    store=Store(tmp_path/'invalid');job=item_worker.enqueue(store,parent,workflow=selected.WORKFLOW)
    result=run_one(store,job_id=job,provider_override=InvalidCompletionProvider(outputs))
    packet=import_packet(store,job);verify_packet(packet)
    assert result['state']=='quarantined' and len(packet['receipt']['stages'])==2
    assert not packet['rows']['results']
    assert packet['receipt']['staged_errors'][0]['code']=='staged_catalog_completion_parent_mismatch'


@pytest.mark.parametrize('key,value',[('source_selection_version','unknown'),('catalog_completion_version','unknown'),
    ('max_catalog_completions',2),('max_catalog_added_entities',100),('owner_binding_version','unknown')])
def test_versions_and_budgets_cannot_be_relabelled(tmp_path,key,value):
    from ingestion.materials_ner.item_flow_v2 import interfaces
    parent,_,_,_,_=parent_packet(tmp_path/'parent');config=item_worker.configuration(parent,workflow=selected.WORKFLOW)
    config[key]=value
    with pytest.raises(ValueError,match='selected_catalog_configuration_mismatch'):interfaces(config)


@pytest.mark.parametrize('workflow',['source_item_stages_v1','source_item_stages_v2','source_item_stages_v3','source_item_stages_v4'])
def test_policy_cannot_be_attached_to_old_transcripts(tmp_path,workflow):
    parent,_,_,_,_=parent_packet(tmp_path/'parent')
    with pytest.raises(ValueError):item_worker.configuration(parent,workflow=workflow,field_generation_policy=selected.POLICY)
