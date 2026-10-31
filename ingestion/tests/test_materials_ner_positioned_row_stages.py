"""Durable real-source regressions; authored responses are not model data or Gold."""
from copy import deepcopy
from functools import lru_cache

import jsonschema
import pytest

from ingestion.materials_ner import positioned_row_stages as row, source_atoms as atoms, item_stages as items
from ingestion.materials_ner import item_worker
from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.proposals import import_packet,verify_packet,ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_scientific_row_stages import fixture as old_fixture, responses as old_responses
from test_materials_ner_item_stages import StageProvider


@lru_cache(maxsize=1)
def prepared():
    b,i,parent,c,scope,_,_,raw=old_fixture();a=row.Adapter(c,scope)
    for sample,cell in zip(raw['samples'],a.palette(b)['cells'],strict=True):
        if cell['footnotes']:sample['isotopes'][0]['fraction']=dict(candidate_id=None,missing_status='ambiguous')
    choices=atoms.CatalogChoices.model_validate(raw)
    declared=a.check_declarations(choices,i,b,128)
    outputs=old_responses()[-1]
    relations=a.Relations.model_validate(outputs[1]);cat,proof=a.project(choices,relations,b)
    outputs[0]=raw;outputs[2]['catalog_sha256']=digest(cat.model_dump())
    owners=a.OwnerBindings.model_validate(outputs[2]);owned,plan,_=a.bind(owners,choices,relations,i,b)
    mapping=atoms.verify_context(c,b,i)[1];sources=a.table_sources(b)
    for group in outputs[3:-1]:
        for key,decision in group['decisions'].items():
            result=decision['observation']['result'];binding=sources[mapping[key]]['binding']
            result['quantity']=deepcopy(binding['quantity']);result['quantity_name_raw']=binding['quantity_name_raw']
            result['component_raw']=result['interpretation_raw']=None
            # Quantity positions are supplied by the source compiler; preserve
            # independent authored fields and do not manufacture broad witnesses.
            result['evidence']=[dict(e,fields=[f for f in e['fields'] if not
                (f=='/quantity_name_raw' or f.startswith('/quantity/') or f=='/quantity' or f in {'/component_raw','/interpretation_raw'})])
                for e in result['evidence']]
            result['evidence']=[e for e in result['evidence'] if e['fields']]
    outputs[-1]['contexts']={x.id:dict(resolution='unresolved',bindings=[],
        explanation='Authored regression leaves scientific context applicability for independent review.') for x in i.context_assertions}
    return b,i,parent,c,scope,a,choices,relations,cat,owners,plan,outputs


def test_native_positions_survive_catalog_owner_and_compact_expansion():
    b,i,_,_,_,a,choices,relations,cat,owners,plan,out=prepared()
    decisions={k:v for group in out[3:-1] for k,v in items.ItemGroup.model_validate(group).decisions.items()}
    owned=a.bind(owners,choices,relations,i,b)[0]
    graph,coverage,proof=a.assemble(b,i,cat,decisions,items.ContextLinks.model_validate(out[-1]),
        owner_plan=plan,owner_declarations=owned,catalog_relations=relations,source_declarations=choices,owner_bindings=owners,
        missing_item_ids=[x.id for x in i.items if x.id not in decisions])
    native=graph.expand(b)
    assert native.schema_version=='materials-ner/11' and len(native.results)==5
    assert [r.quantity.value for r in native.results]==[91.19,90.99,91.35,91.16,44.63]
    assert all(s.conditions[0].kind=='reported_magnetic_field' and s.conditions[1].role=='study_extent' for s in native.states)
    for r in native.results:
        assert any(e.field=='/quantity/unit' and hasattr(e,'start_char') and e.quote=='K' for e in r.evidence)
    damaged=graph.model_copy(deep=True)
    damaged.samples[0].evidence[0].exact_quotes[0].start_char+=1
    with pytest.raises(ValueError,match='evidence_position_quote_mismatch'):damaged.expand(b)
    damaged=graph.model_copy(deep=True);damaged.table_value_sources[0].binding['source']['unit']=deepcopy(damaged.table_value_sources[1].binding['source']['unit'])
    with pytest.raises(ValueError,match='table_value_binding_changed'):damaged.expand(b)


@pytest.mark.parametrize('change',['wrong_applicability','instrument_parameter','back_enrichment','duplicate_formula'])
def test_old_scientific_failure_modes_are_rejected_without_repairing_payload(change):
    b,i,_,_,_,a,choices,*_=prepared();raw=choices.model_dump()
    if change=='wrong_applicability':raw['samples'][0]['states'][0]['conditions'][0]['applicability']['candidate_id']='T74'
    elif change=='instrument_parameter':raw['protocols'][0]['parameters']=[dict(kind='magnetic_flux_density',
        name=raw['protocols'][0]['method'],quantity=dict(candidate_id='N46',missing_status=None),support=dict(candidate_id='T54',end_candidate_id=None))]
    elif change=='back_enrichment':raw['samples'][3]['isotopes'][0]['fraction']=dict(candidate_id='N42',missing_status=None)
    else:raw['samples'][0]['alternative_formulas']=[dict(formula=raw['samples'][0]['formula'],basis=raw['samples'][0]['basis'],context=dict(candidate_id='T81',end_candidate_id=None))]
    with pytest.raises(ValueError,match='staged_scientific_row_field_contract_invalid'):
        a.check_declarations(atoms.CatalogChoices.model_validate(raw),i,b,128)


@pytest.mark.parametrize('change',['unit','value','header','stitched_raw','physical_kind'])
def test_result_choices_cannot_retype_or_reclassify_incompatible_source_values(change):
    b,i,_,_,_,a,_,_,cat,_,plan,out=prepared();raw=deepcopy(out[3]);result=raw['decisions']['I1']['observation']['result']
    if change=='unit':result['quantity']['unit']='GPa'
    elif change=='value':result['quantity']['value']=91.20
    elif change=='header':result['quantity_name_raw']=result['quantity_name_raw'][:-1]
    elif change=='stitched_raw':result['component_raw']='16O back-exchanged'
    else:result['quantity_kind']='critical_pressure'
    with pytest.raises(ValueError,match='staged_positioned_item_contract_invalid'):
        a.check_group(items.ItemGroup.model_validate(raw),cat,i,b,plan)


def test_disconnected_context_cannot_be_hidden_by_a_structurally_valid_pointer():
    b,i,_,_,_,a,_,_,cat,_,_,out=prepared()
    graph=items.graph_objects(cat,{k:v for group in out[3:-1] for k,v in items.ItemGroup.model_validate(group).decisions.items()})
    schema=a.links_schema(b,i,graph)
    target=next(x for x in i.context_assertions if 'S10' not in x.span_ids)
    raw=deepcopy(out[-1]);raw['contexts'][target.id]=dict(resolution='carried',explanation=None,
        bindings=[dict(entity='state',entity_id='state:1:1',field='/conditions/0')])
    with pytest.raises(ValueError,match='staged_positioned_context_contract_invalid'):
        a.check_links(items.ContextLinks.model_validate(raw),i,graph,b)
    jsonschema.Draft202012Validator.check_schema(schema)


def test_full_durable_worker_revision_and_private_idempotency(tmp_path):
    b,i,parent,c,scope,a,_,_,_,_,_,out=prepared();store=Store(tmp_path/'positioned');provider=StageProvider(deepcopy(out))
    job=item_worker.enqueue(store,parent,workflow=a.WORKFLOW,field_generation_policy=a.POLICY,
        source_atom_context=c,catalog_scope=scope,max_source_items=128,max_input_tokens=120000,timeout_seconds=600)
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome['state']=='quarantined' and provider.calls==6,outcome
    packet=import_packet(store,job);verify_packet(packet);receipt=packet['receipt']
    assert not receipt['staged_errors'],receipt['staged_errors']
    assert receipt['config']['native_output_schema']=='materials-ner/11'
    assert receipt['validation']['validator_version']==receipt['config']['validator_version']=='materials-ner-validation/1.22.0'
    assert len(receipt['extraction']['results'])==5
    audit=receipt['source_quantity_audit']
    assert audit['policy']=='initial_source_quantity_support_v2'
    assert audit['status_counts']['table_value_header_unit_supported']==5
    assert not any(r['path'].startswith('/table_value_sources/') for r in audit['records'])
    from ingestion.materials_ner.staged_revision import resolve_parent
    graph,inventory=resolve_parent(packet)
    assert graph.expand(b).model_dump()==receipt['extraction']
    db=ProposalDatabase(tmp_path/'private');assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
