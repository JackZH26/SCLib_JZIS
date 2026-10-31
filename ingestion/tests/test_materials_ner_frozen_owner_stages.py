"""Real failed declarations, fixed IDs, incomplete owners and retained worker attempts."""
from copy import deepcopy

import jsonschema
import pytest

from materials_private_fixtures import private_json

from ingestion.materials_ner import frozen_owner_stages as frozen, identity_stages as identity
from ingestion.materials_ner import item_worker,item_stages as items,staged_revision
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.contract_v9 import ExtractionV9
from ingestion.materials_ner.formula_identity import has_identity_token
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.sources import Bundle
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.proposals import import_packet,verify_packet,ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_identity_stages import fixture
from test_materials_ner_item_stages import parent_packet,StageProvider


def failure(window):
    return next(c for c in private_json('materials_ner_catalog_integrity_failures.json')['cases'] if c['window']==window and c['policy']=='source_fields_v3')


def selection_for(raw,catalog,inventory):
    out={}
    all_items,added=items.inventory_items(inventory,catalog)
    for item in all_items:
        if item.id in raw['item_owners']:
            decision=deepcopy(raw['item_owners'][item.id])
            if decision['resolution']=='bound':
                si,ti,pi=(decision.pop(n) for n in ('sample_index','state_index','protocol_index'))
                decision.update(sample_id=f'sample:{si+1}',state_id=f'state:{si+1}:{ti+1}',protocol_id=f'protocol:{pi+1}')
        else:
            decision=dict(resolution='unresolved',explanation='Additional source assertion has no established owner.',
                source_span_ids=item.source_span_ids,attribution=dict(source_role='unknown',cited_source_raw=None,source_span_ids=item.source_span_ids))
        out[item.id]=decision
    return dict(schema_version=frozen.BINDING_VERSION,work_id=catalog.work_id,catalog_sha256=digest(catalog.model_dump()),decisions=out)


def typed():
    bundle,inventory,raw,relations,decisions,links=fixture()
    decl=identity.body(identity.OwnedDeclarations.model_validate(raw));relations=identity.Relations.model_validate(relations)
    catalog,_=identity.project(decl,relations,bundle)
    selection=frozen.OwnerBindings.model_validate(selection_for(raw,catalog,inventory))
    return bundle,inventory,decl,relations,catalog,selection,decisions,links


@pytest.mark.parametrize('raw',['.','---','123','{}',r'$\ldots$',r'\mathrm{.}',r'\text{...}'])
def test_punctuation_numbers_and_formatting_commands_are_not_identity(raw):
    assert not has_identity_token(raw)


@pytest.mark.parametrize('raw',[None,'FeSe','PCCO','D',r'Pr$_{1.85}$Ce$_{0.15}$CuO$_{4-y}$',
    r'\mathrm{BaFe_{2}(As_{1-x}P_x)_{2}}',r'$^{18}$O','YBa2Cu3O7-δ','α-FeSe'])
def test_negative_lexical_check_does_not_claim_or_normalize_chemistry(raw):
    assert has_identity_token(raw)


def test_actual_period_formula_is_rejected_without_rewriting_the_historical_graph():
    case=failure(4);original=deepcopy(case['extraction']);ex=ExtractionV9.model_validate(original)
    assert ex.samples[0].formula_raw=='.'
    report=validate_extraction(ex,Bundle.model_validate(case['bundle']))
    assert dict(code='formula_no_identity_token',path='/samples/0/formula_raw') in report['issues']
    assert ex.model_dump()==original
    owned=identity.OwnedDeclarations.model_validate(case['outputs']['declarations']);decl=identity.body(owned)
    # Historical type remains parseable; new generation rejects the bad token.
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(decl.model_dump(),frozen.declaration_schema(Bundle.model_validate(case['bundle'])))


def test_punctuation_in_additional_formula_assertions_is_also_reported():
    case=failure(4);raw=deepcopy(case['extraction'])
    raw['samples'][0]['additional_formula_assertions']=[dict(formula_raw='---',basis='unresolved',context_raw=None)]
    report=validate_extraction(ExtractionV9.model_validate(raw),Bundle.model_validate(case['bundle']))
    assert dict(code='formula_no_identity_token',path='/samples/0/additional_formula_assertions/0/formula_raw') in report['issues']


def test_added_assertion_can_remain_unresolved_without_losing_the_original_owner():
    case=failure(2);bundle=Bundle.model_validate(case['bundle']);inventory=Inventory.model_validate(case['inventory'])
    raw=case['outputs']['declarations'];old=identity.OwnedDeclarations.model_validate(raw)
    with pytest.raises(ValueError,match='additional_item_owners_not_closed'):identity.project_owners(old,inventory,bundle)
    decl=identity.body(old);declared=identity.check_declarations(decl,inventory,bundle,8,strict_field_owner=False)
    relations=identity.Relations(schema_version='materials-source-catalog-relations/1',work_id=bundle.work_id,
        protocol_uses={p.id:dict(resolution='unresolved',uses=[],explanation='Applicability requires review.') for p in declared.protocols},sample_relations=[])
    catalog,_=identity.project(decl,relations,bundle);data=selection_for(raw,catalog,inventory)
    jsonschema.validate(data,frozen.binding_schema(bundle,inventory,catalog))
    selection=frozen.OwnerBindings.model_validate(data);owned,plan,proof=frozen.bind(selection,decl,relations,inventory,bundle)
    assert plan['items']['I1']['resolution']=='bound'
    assert plan['items']['additional:1']['resolution']=='unresolved'
    assert proof['scientific_payload_unchanged'] and not proof['derived_indices_are_model_output']
    assert identity.body(owned)==decl and len(owned.additional_item_owners)==1
    all_items,_=items.inventory_items(inventory,catalog)
    schema=frozen.item_schema(bundle,catalog,['I1','additional:1'],all_items,plan=plan)
    assert schema['properties']['decisions']['properties']['additional:1']=={'$ref':'#/$defs/HeldItem'}


@pytest.mark.parametrize('mutation',['state','sample','protocol','catalog','missing_key','extra_key'])
def test_foreign_or_unclosed_owner_selection_is_rejected_by_schema_and_replay(mutation):
    bundle,inventory,decl,rel,catalog,selection,_,_=typed();data=selection.model_dump();first=next(iter(data['decisions'].values()))
    if mutation in {'state','sample','protocol'}:first[mutation+'_id']='foreign'
    elif mutation=='catalog':data['catalog_sha256']='0'*64
    elif mutation=='missing_key':data['decisions'].pop(next(iter(data['decisions'])))
    else:data['decisions']['unrequested']=deepcopy(first)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(data,frozen.binding_schema(bundle,inventory,catalog))
    with pytest.raises(ValueError):frozen.bind(frozen.OwnerBindings.model_validate(data),decl,rel,inventory,bundle)


def test_projection_preserves_selected_science_and_rejects_changed_frozen_inputs():
    bundle,inventory,decl,rel,catalog,selection,decisions,links=typed()
    owned,plan,bridge=frozen.bind(selection,decl,rel,inventory,bundle)
    group=items.ItemGroup(schema_version='materials-source-item-group/1',work_id=bundle.work_id,decisions=decisions)
    graph,coverage,proof=frozen.assemble(bundle,inventory,catalog,group.decisions,items.ContextLinks.model_validate(links),
        owner_plan=plan,owner_declarations=owned,catalog_relations=rel,source_declarations=decl,owner_bindings=selection)
    assert coverage['valid'] and validate_extraction(graph.expand(bundle),bundle)['valid']
    assert proof['schema']=='materials-source-item-assembly/4' and proof['frozen_owner_projection']==bridge
    changed=selection.model_copy(deep=True);next(iter(changed.decisions.values())).protocol_id='phantom'
    with pytest.raises(ValueError):frozen.assemble(bundle,inventory,catalog,group.decisions,items.ContextLinks.model_validate(links),
        owner_plan=plan,owner_declarations=owned,catalog_relations=rel,source_declarations=decl,owner_bindings=changed)


def test_explicitly_unresolved_addition_preserves_other_results_and_incomplete_accounting():
    bundle,inventory,decl,rel,_,selection,decisions,links=typed()
    raw=decl.model_dump();raw['additional_source_items'].append(inventory.items[0].model_dump(exclude={'id'}))
    decl=identity.Declarations.model_validate(raw);catalog,_=identity.project(decl,rel,bundle)
    choice=selection.model_dump();choice['catalog_sha256']=digest(catalog.model_dump())
    choice['decisions']['additional:1']=dict(resolution='unresolved',explanation='Additional occurrence ownership is unresolved.',
        source_span_ids=inventory.items[0].source_span_ids,attribution=dict(source_role='unknown',cited_source_raw=None,source_span_ids=inventory.items[0].source_span_ids))
    selected=frozen.OwnerBindings.model_validate(choice);owned,plan,_=frozen.bind(selected,decl,rel,inventory,bundle)
    decisions=deepcopy(decisions);decisions['additional:1']=dict(decision='held',reason='unresolved',explanation='The owner is unresolved.')
    group=items.ItemGroup(schema_version='materials-source-item-group/1',work_id=bundle.work_id,decisions=decisions)
    graph,coverage,proof=frozen.assemble(bundle,inventory,catalog,group.decisions,items.ContextLinks.model_validate(links),
        owner_plan=plan,owner_declarations=owned,catalog_relations=rel,source_declarations=decl,owner_bindings=selected)
    assert len(graph.observations)==5
    assert not coverage['valid'] and graph.completion.outcome=='incomplete'
    assert proof['frozen_owner_projection']['additional_item_ids']==['additional:1']
    assert all(o.id!='item:additional:1' for o in graph.observations)


@pytest.mark.parametrize('failure_at',[None,1,2,3,4,5,6])
def test_actual_worker_retains_each_failure_and_can_reconstruct_revision_ancestry(tmp_path,failure_at):
    parent,_,_,_,_=parent_packet(tmp_path/'parent')
    bundle,inventory,decl,rel,catalog,selection,decisions,links=typed();keys=list(decisions)
    outputs=[decl.model_dump(),rel.model_dump(),selection.model_dump(),
        *[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
            decisions={k:decisions[k] for k in keys[i:i+4]}) for i in range(0,len(keys),4)],links]
    assert len(outputs)==6
    store=Store(tmp_path/'frozen');job=item_worker.enqueue(store,parent,workflow=frozen.WORKFLOW)
    outcome=run_one(store,job_id=job,provider_override=StageProvider(outputs,fail_at=failure_at))
    assert outcome['state']==('failed' if failure_at else 'succeeded'),outcome
    packet=import_packet(store,job);verify_packet(packet)
    assert packet['receipt']['config']['output_format']==frozen.OUTPUT_FORMAT
    assert len(packet['rows']['results'])=={None:5,1:0,2:0,3:0,4:0,5:4,6:5}[failure_at]
    db=ProposalDatabase(tmp_path/'private');assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    if not failure_at:
        graph,_=staged_revision.resolve_parent(packet);assert graph.expand(bundle).model_dump()==packet['receipt']['extraction']
        damaged=deepcopy(packet['receipt']);damaged['owner_selection_projection']['catalog_sha256']='0'*64
        with pytest.raises(ValueError,match='assembly_mismatch'):item_worker.verify_receipt(damaged,bundle,packet['raw_output'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


def test_new_policy_is_not_silently_attached_to_a_historical_workflow(tmp_path):
    parent,_,_,_,_=parent_packet(tmp_path/'parent')
    with pytest.raises(ValueError,match='field_generation_policy_unknown'):
        item_worker.configuration(parent,workflow=identity.WORKFLOW,field_generation_policy=frozen.POLICY)
    with pytest.raises(ValueError,match='frozen_owner_configuration_mismatch'):
        item_worker.configuration(parent,workflow=frozen.WORKFLOW,field_generation_policy='source_fields_v3')


def test_frozen_owner_prompts_do_not_reintroduce_old_parallel_owner_arrays():
    bundle,inventory,decl,rel,catalog,selection,_,_=typed()
    schema=frozen.declaration_schema(bundle,inventory)
    assert 'item_owners' not in schema['properties'] and 'additional_item_owners' not in schema['properties']
    assert 'SOURCE_ITEM_LEDGER:' in frozen.render_declarations(bundle,inventory)
    assert 'SOURCE_INVENTORY:' not in frozen.render_declarations(bundle,inventory)
    assert digest(catalog.model_dump()) in frozen.render_bindings(bundle,inventory,catalog)
    jsonschema.Draft202012Validator.check_schema(frozen.binding_schema(bundle,inventory,catalog))
    assert 'BoundIdOwner' in frozen.binding_schema()['$defs']
    assert 'UnresolvedOwner' in frozen.binding_schema()['$defs']


def test_owner_contract_version_cannot_be_relabelled(tmp_path):
    parent,_,_,_,_=parent_packet(tmp_path/'parent');config=item_worker.configuration(parent,workflow=frozen.WORKFLOW)
    config['owner_binding_version']='unknown'
    from ingestion.materials_ner.item_flow_v2 import interfaces
    with pytest.raises(ValueError,match='frozen_owner_configuration_mismatch'):interfaces(config)
