"""Source regressions and authored transport rehearsals; not independent Gold."""
from copy import deepcopy
from functools import lru_cache
import json

import jsonschema
import pytest

from ingestion.materials_ner import assertion_scope_stages as row, source_atoms as atoms
from ingestion.materials_ner import item_stages as items, item_worker, staged_revision as revision
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_scoped_row_stages import prepared as previous_prepared
from test_materials_ner_item_stages import StageProvider
from test_materials_ner_staged_revision import execute


@lru_cache(maxsize=1)
def prepared():
    b,i,parent,c,scope,_,_,_,_,_,_,old,_ = previous_prepared()
    a = row.Adapter(c,scope); out = deepcopy(old)
    choices = atoms.CatalogChoices.model_validate(out[0]); a.check_declarations(choices,i,b,128)
    relations = a.Relations.model_validate(out[1]); cat,_ = a.project(choices,relations,b)
    out[2]['catalog_sha256'] = digest(cat.model_dump())
    owners = a.OwnerBindings.model_validate(out[2]); _,plan,_ = a.bind(owners,choices,relations,i,b)
    return b,i,parent,c,scope,a,choices,cat,plan,out


def test_conditions_require_the_physical_kind_in_the_selected_source_clause():
    b,i,_,_,_,a,declarations,*_ = prepared()
    support = a.condition_kind_sources(b)
    assert support['strain'] == []
    assert 'T54' in support['temperature'] and 'T54' in support['reported_magnetic_field']
    schema = a.declaration_schema(b,i); jsonschema.Draft202012Validator.check_schema(schema)
    assert all(v['properties']['kind']['enum'] != ['strain'] for v in schema['$defs']['ConditionChoice']['anyOf'])
    compiled,proof = a.compile(declarations,b)
    states = [state for sample in compiled.samples for state in sample.states]
    assert states and proof['condition_kind_scope']['selections']
    assert not proof['condition_kind_scope']['scientific_applicability_verified']
    # Existing field and scan-temperature settings stay represented; this is
    # not a shortcut that removes all conditions from extraction.
    kinds = {c.kind for s in states for c in s.conditions}
    assert {'temperature','reported_magnetic_field'} <= kinds


@pytest.mark.parametrize('variant',['silent_kind','wrong_numeric_clause','dimensionless_row_is_not_strain'])
def test_source_silence_and_disconnected_numbers_cannot_be_condition_witnesses(variant):
    b,i,_,_,_,a,declarations,*_ = prepared(); value=declarations.model_dump()
    conditions=value['samples'][0]['states'][0]['conditions']
    if variant=='wrong_numeric_clause':
        condition=next(c for c in conditions if c['kind']=='temperature')
        condition['applicability']={'candidate_id':'T1:R1:C2/row_label','end_candidate_id':None}
    else:
        quantity={'candidate_id':None,'missing_status':'not_applicable'}
        if variant=='dimensionless_row_is_not_strain':
            quantity=deepcopy(value['samples'][0]['variables'][0]['amount'])
        conditions.append(dict(kind='strain',role='measurement',quantity=quantity,basis=None,
            orientation=None,window_position=None,applicability=dict(candidate_id='T54',end_candidate_id=None)))
    with pytest.raises(ValueError,match='staged_scientific_row_field_contract_invalid'):
        a.check_declarations(atoms.CatalogChoices.model_validate(value),i,b,128)


@pytest.mark.parametrize('field',['interpretation','qualifier'])
def test_ordinary_tc_header_is_not_an_extra_scientific_assertion(field):
    b,i,_,_,_,a,_,cat,plan,out=prepared(); group=deepcopy(out[3])
    result=group['decisions']['I1']['observation']['result'];header=result['quantity_name_raw']
    if field=='interpretation':result['interpretation_raw']=header
    else:result['qualifiers']=[dict(kind='temperature_role',role='system_transition',raw=header)]
    with pytest.raises(ValueError,match='staged_positioned_item_contract_invalid|staged_redundant_header_qualifier'):
        a.check_group(items.ItemGroup.model_validate(group),cat,i,b,plan)


def test_attached_note_scope_does_not_supply_an_origin_answer():
    b,i,_,_,_,a,_,cat,plan,out=prepared()
    text=a.render_items(b,i,cat,['I55'],plan)
    view=json.loads(next(line[len('CELL SOURCE SCOPE: '):] for line in text.splitlines() if line.startswith('CELL SOURCE SCOPE: ')))
    assert [n['label'] for n in view['I55']['attached_notes']]==['b']
    assert 'exchang' in view['I55']['attached_notes'][0]['definition_source']['quote']
    assert 'span co-location is not' in text
    # Scientific provenance remains a model choice, including uncertainty.
    schema=a.item_schema(b,cat,['I55'],i.items,plan=plan)
    origins=[]
    for value in schema['$defs'].values():
        for branch in value.get('anyOf',[]):
            if 'origin' in branch.get('properties',{}):origins.extend(branch['properties']['origin']['enum'])
    assert set(origins)=={'observed','computed','model_derived','unknown'}


def test_worker_and_native11_field_mutation_preserve_source_and_table_proofs(tmp_path):
    b,i,parent,c,scope,a,_,_,_,out=prepared();out=deepcopy(out)
    # An authored wrong proposal exercises revision transport, not model accuracy.
    out[4]['decisions']['I55']['observation']['result']['origin']='model_derived'
    declarations=atoms.CatalogChoices.model_validate(out[0]);relations=a.Relations.model_validate(out[1])
    cat,_=a.project(declarations,relations,b)
    decisions={key:value for g in out[3:-1] for key,value in items.ItemGroup.model_validate(g).decisions.items()}
    graph=a.context_graph(cat,decisions,b);out[-1]['graph_sha256']=digest(graph)
    store=Store(tmp_path/'authored');provider=StageProvider(out)
    job=item_worker.enqueue(store,parent,workflow=a.WORKFLOW,field_generation_policy=a.POLICY,
        source_atom_context=c,catalog_scope=scope,max_source_items=128,max_input_tokens=120000,timeout_seconds=600)
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome['state']=='quarantined' and provider.calls==6,outcome
    packet=import_packet(store,job);verify_packet(packet)
    assert not packet['receipt']['staged_errors'],packet['receipt']['staged_errors']
    before,_=revision.resolve_parent(packet);old_hash=digest(packet)
    path='/observations/4/result/origin'
    request=dict(schema_version=revision.REQUEST_VERSION,parent_run_id=packet['run_id'],author_kind='assistant',
        source_context=None,prior_revision_run_ids=[],fields=[dict(id='origin',path=path,
        expected_value_sha256=digest('model_derived'),operation='replace',
        concern='Authored transport regression for one experimental-origin correction.',source_span_ids=['S9','S10'])])
    response=dict(schema_version=revision.VERSION,work_id=b.work_id,parent_run_id=packet['run_id'],
        base_graph_sha256=digest(before.model_dump()),request_sha256=digest(request),read_context_block_ids=[],
        selections={'origin':dict(action='replace',value='observed',span_ids=['S9','S10'],
            reason='Authored transport fixture, not an independent scientific review.',literal_witnesses=None,quantity_name_witness=None)})
    configuration=revision.configuration(packet,review_request=request,max_input_tokens=120000)
    assert configuration['validator_version']=='materials-ner-validation/1.22.0'
    # execute uses the existing bounded revision worker and synthetic provider.
    result,revised=execute(store,b,packet,request,response)
    assert result['state']=='quarantined',result
    after,_=revision.resolve_parent(revised)
    assert digest(packet)==old_hash and after.table_value_sources==before.table_value_sources
    expected=before.model_dump();expected['observations'][4]['result']['origin']='observed'
    expected['observations'][4]['result']['evidence']=after.model_dump()['observations'][4]['result']['evidence']
    assert after.model_dump()==expected
    assert revised['receipt']['config']['validator_version']==revised['receipt']['validation']['validator_version']
    assert revised['receipt']['extraction']['schema_version']=='materials-ner/11'
    changed=after.model_copy(deep=True);changed.observations[0].result.quantity.value=999
    with pytest.raises(ValueError,match='staged_positioned_table_value_changed'):changed.expand(b)
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and db.ingest(revised)['inserted']
    assert not db.ingest(revised)['inserted']
    assert not revised['scientific_acceptance'] and not revised['ml_training_eligible']
