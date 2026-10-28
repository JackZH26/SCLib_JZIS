"""Frozen scientific ownership, honest holds and backwards-compatible replay."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import item_ownership as owners, catalog_stages as catalogs, item_stages as items, item_worker
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.proposals import import_packet,verify_packet,ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.sources import Block,sha
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.worker import run_one
from ingestion.materials_ner import staged_revision
from test_materials_ner_catalog_stages import split_fixture
from test_materials_ner_item_stages import parent_packet,StageProvider


def fixture():
    bundle,inventory,declarations,relations,decisions,links=split_fixture()
    declarations.update(schema_version='materials-owned-source-declarations/1',item_owners={},additional_item_owners=[])
    for item in inventory.items:
        observation=decisions[item.id]['observation'];state=observation['state_id'].split(':')
        spans=list(dict.fromkeys(item.source_span_ids+item.context_span_ids))
        declarations['item_owners'][item.id]=dict(resolution='bound',sample_index=int(state[1])-1,
            state_index=int(state[2])-1,protocol_index=int(observation['protocol_id'].split(':')[1])-1,
            source_span_ids=spans,attribution=dict(source_role=observation['result']['source_role'],
                cited_source_raw=observation['result']['cited_source_raw'],source_span_ids=spans))
    return bundle,inventory,declarations,relations,decisions,links


def test_owner_plan_covers_each_assertion_without_changing_scientific_bodies():
    bundle,inventory,declarations,relations,decisions,links=fixture()
    owned=owners.Declarations.model_validate(declarations);plan=owners.project(owned,inventory,bundle)
    body=owners.body(owned);catalog=catalogs.check_declarations(body,inventory,bundle,64)
    assert body.model_dump()==split_fixture()[2]
    assert plan['scientific_declarations_unchanged'] and not plan['scientific_acceptance']
    assert set(plan['items'])=={x.id for x in inventory.items}
    schema=owners.declaration_schema(bundle,inventory)
    jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(declarations,schema)
    group=items.ItemGroup(schema_version='materials-source-item-group/1',work_id=bundle.work_id,decisions=decisions)
    owners.check_group(group,plan)
    schema=owners.item_schema(bundle,catalog,list(decisions),inventory.items,plan=plan)
    jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(group.model_dump(),schema)
    assert all(plan['items'][k]['owners']=={f:decisions[k]['observation'][f] for f in ('sample_id','state_id','protocol_id')} for k in decisions)


@pytest.mark.parametrize('failure',['missing_item','extra_item','sample_index','state_index','protocol_index','source_disconnected','phantom_source','fabricated_citation','missing_additional_owner'])
def test_owner_closure_and_literal_source_binding_fail_closed(failure):
    bundle,inventory,declarations,_,_,_=fixture();first=next(iter(declarations['item_owners']));selection=declarations['item_owners'][first]
    if failure=='missing_item':declarations['item_owners'].pop(first)
    elif failure=='extra_item':declarations['item_owners']['absent']=deepcopy(selection)
    elif failure in {'sample_index','state_index','protocol_index'}:selection[failure]=999
    elif failure=='source_disconnected':
        text='A separate source paragraph without this result.'
        block=Block(id='unrelated',document_id=bundle.documents[0].id,ordinal=len(bundle.blocks),
            locator='synthetic:unrelated',text=text,sha256=sha(text.encode()))
        bundle.blocks.append(block)
        selection['source_span_ids']=[s for s,x in source_catalog(bundle)['spans'].items() if x['block_id']=='unrelated']
    elif failure=='phantom_source':selection['attribution']['source_span_ids']=['S9999']
    elif failure=='fabricated_citation':selection['attribution']['cited_source_raw']='Fabricated paper not in source'
    else:declarations['additional_source_items']=[inventory.items[0].model_dump(exclude={'id'})]
    with pytest.raises(ValueError):owners.project(owners.Declarations.model_validate(declarations),inventory,bundle)


@pytest.mark.parametrize('value',[-1,True,1.5])
def test_owner_array_positions_are_real_nonnegative_integer_indices(value):
    _,_,declarations,_,_,_=fixture();declarations['item_owners']['I1']['sample_index']=value
    with pytest.raises(ValidationError):owners.Declarations.model_validate(declarations)


@pytest.mark.parametrize('field',['sample_id','state_id','protocol_id','source_role','cited_source_raw'])
def test_item_stage_cannot_silently_reassign_a_frozen_owner_or_attribution(field):
    bundle,inventory,declarations,_,decisions,_=fixture();owned=owners.Declarations.model_validate(declarations)
    plan=owners.project(owned,inventory,bundle);catalog,_=catalogs.declare(owners.body(owned))
    if field.endswith('_id'):decisions['I1']['observation'][field]='different-owner'
    else:decisions['I1']['observation']['result'][field]='cited' if field=='source_role' else 'invented citation'
    payload=dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,decisions=decisions)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(payload,owners.item_schema(bundle,catalog,list(decisions),inventory.items,plan=plan))
    with pytest.raises(ValueError):owners.check_group(items.ItemGroup.model_validate(payload),plan)


def test_honest_unresolved_owner_keeps_assertion_and_never_emits_or_approves_it():
    bundle,inventory,declarations,_,decisions,_=fixture();old=declarations['item_owners']['I1']
    declarations['item_owners']['I1']=dict(resolution='unresolved',explanation='Specimen association is not established.',
        source_span_ids=old['source_span_ids'],attribution=old['attribution'])
    owned=owners.Declarations.model_validate(declarations);plan=owners.project(owned,inventory,bundle)
    catalog,_=catalogs.declare(owners.body(owned))
    payload=dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,decisions=decisions)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(payload,owners.item_schema(bundle,catalog,list(decisions),inventory.items,plan=plan))
    with pytest.raises(ValueError,match='unresolved_emission'):owners.check_group(items.ItemGroup.model_validate(payload),plan)
    decisions['I1']=dict(decision='held',reason='insufficient_context',explanation='Specimen association is not established.')
    owners.check_group(items.ItemGroup.model_validate(payload),plan)
    assert plan['items']['I1']['owners'] is None and len(plan['items'])==len(inventory.items)
    assert not plan['ml_training_eligible']


def test_added_assertion_owners_use_the_same_collision_safe_ids():
    bundle,inventory,declarations,_,_,_=fixture()
    declarations['additional_source_items']=[inventory.items[0].model_dump(exclude={'id'})]
    declarations['additional_item_owners']=[deepcopy(declarations['item_owners']['I1'])]
    plan=owners.project(owners.Declarations.model_validate(declarations),inventory,bundle)
    assert plan['additional_item_ids']==['additional:1']
    assert plan['items']['additional:1']==plan['items']['I1']


def execute(tmp_path,*,policy=owners.POLICY,failure=None):
    parent,_,_,_,_=parent_packet(tmp_path/'parent')
    bundle,inventory,declarations,relations,decisions,links=fixture()
    if policy is None:declarations=owners.body(owners.Declarations.model_validate(declarations)).model_dump()
    keys=list(decisions)
    responses=[declarations,relations,*[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
        decisions={k:decisions[k] for k in keys[i:i+4]}) for i in range(0,len(keys),4)],links]
    store=Store(tmp_path/'staged');provider=StageProvider(responses,fail_at=failure)
    job=item_worker.enqueue(store,parent,workflow='source_item_stages_v2',item_owner_policy=policy)
    result=run_one(store,job_id=job,provider_override=provider);packet=import_packet(store,job);verify_packet(packet)
    return result,packet,bundle,store


@pytest.mark.parametrize('failure',[None,2,4])
def test_real_worker_interface_replay_failure_and_idempotent_archive(tmp_path,failure):
    result,packet,bundle,_=execute(tmp_path,failure=failure)
    assert result['state']==('failed' if failure else 'succeeded')
    receipt=packet['receipt'];plan=receipt['item_owner_plan']
    assert receipt['config']['item_owner_policy']==owners.POLICY and plan['all_source_items_accounted']
    assert len(packet['rows']['results'])==({None:5,2:0,4:4}[failure])
    database=ProposalDatabase(tmp_path/'archive')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    damaged=deepcopy(receipt);damaged['item_owner_plan']['items']['I1']['owners']['state_id']='wrong-state'
    with pytest.raises(ValueError,match='assembly_mismatch'):item_worker.verify_receipt(damaged,bundle,packet['raw_output'])
    if not failure:
        graph,_=staged_revision.resolve_parent(packet)
        assert len(graph.observations)==5 and graph.expand(bundle).model_dump()==receipt['extraction']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


def test_historical_no_policy_replay_does_not_acquire_an_owner_plan(tmp_path):
    _,packet,bundle,_=execute(tmp_path,policy=None)
    assert 'item_owner_policy' not in packet['receipt']['config'] and 'item_owner_plan' not in packet['receipt']
    report=item_worker.verify_receipt(packet['receipt'],bundle,packet['raw_output'])
    assert 'item_owner_plan' not in report
    parent=packet['receipt']['source_inventory_parent']
    with pytest.raises(ValueError,match='owner_policy_unknown'):
        item_worker.configuration(parent,workflow='source_item_stages_v1',item_owner_policy=owners.POLICY)
