"""Realistic graph ownership, dimension guards and split-stage recovery tests."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import catalog_stages as catalogs, item_stages as items, item_worker
from ingestion.materials_ner.proposals import import_packet,verify_packet,ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.worker import run_one
from test_materials_ner_item_stages import fixture as original_fixture, parent_packet, StageProvider


def split_fixture():
    bundle, inventory, old, catalog, decisions, links = original_fixture()
    declarations = {k:v for k,v in catalog.items() if k not in {'schema_version','samples','states','protocols','sample_relations'}}
    declarations.update(schema_version='materials-source-declarations/1',samples=[],protocols=[])
    maps = {'sample':{},'state':{},'protocol':{},'sample_relation':{}};conditions={}
    for n,sample in enumerate(catalog['samples'],1):
        maps['sample'][sample['id']]=f'sample:{n}'
        body={k:v for k,v in sample.items() if k!='id'};body['states']=[]
        states=[s for s in catalog['states'] if s['sample_id']==sample['id']]
        for m,state in enumerate(states,1):
            maps['state'][state['id']]=f'state:{n}:{m}'
            state_body={k:v for k,v in state.items() if k not in {'id','sample_id','conditions'}}
            state_body['conditions']=[]
            for k,condition in enumerate(state['conditions'],1):
                conditions[(state['id'],condition['id'])]=f'condition:{n}:{m}:{k}'
                state_body['conditions'].append({k:v for k,v in condition.items() if k!='id'})
            body['states'].append(state_body)
        declarations['samples'].append(body)
    relations={'schema_version':'materials-source-catalog-relations/1','work_id':bundle.work_id,'protocol_uses':{},'sample_relations':[]}
    for n,protocol in enumerate(catalog['protocols'],1):
        pid=f'protocol:{n}';maps['protocol'][protocol['id']]=pid
        body={k:v for k,v in protocol.items() if k not in {'id','context_uses','evidence'}}
        body['evidence']=[]
        for ref in protocol['evidence']:
            fields=[f for f in ref['fields'] if not f.startswith('/context_uses')]
            if fields:body['evidence'].append(dict(ref,fields=fields))
        declarations['protocols'].append(body)
        uses=[]
        for index,use in enumerate(protocol['context_uses']):
            refs=[r for r in protocol['evidence'] if '/context_uses/'+str(index) in r['fields'] or '/context_uses' in r['fields']]
            assert refs
            uses.append({'state_id':maps['state'][use['state_id']],
                'condition_id':conditions[(use['state_id'],use['condition_id'])],
                'source_span_ids':list(dict.fromkeys(s for r in refs for s in r['span_ids']))})
        relations['protocol_uses'][pid]={'resolution':'linked' if uses else 'none','uses':uses,
            'explanation':None if uses else 'No source-supported condition use is required for this procedure.'}
    for n,relation in enumerate(catalog['sample_relations'],1):
        maps['sample_relation'][relation['id']]=f'relation:{n}'
        relations['sample_relations'].append({'from_sample_id':maps['sample'][relation['from_sample_id']],
            'to_sample_id':maps['sample'][relation['to_sample_id']],'relation':relation['relation'],
            'relation_raw':relation['relation_raw'],'source_span_ids':relation['evidence'][0]['span_ids']})
    for decision in decisions.values():
        observation=decision['observation'];old_state=observation['state_id']
        for qualifier in observation['result']['qualifiers']:
            if qualifier['kind']=='non_detection':
                qualifier['window_condition_ids']=[conditions[(old_state,c)] for c in qualifier['window_condition_ids']]
        for kind in ('sample','state','protocol'):observation[kind+'_id']=maps[kind][observation[kind+'_id']]
    for context in links['contexts'].values():
        for binding in context['bindings']:
            if binding['entity'] in maps:binding['entity_id']=maps[binding['entity']][binding['entity_id']]
    for support in links['condition_supports']:
        support['condition_id']=conditions[(support['state_id'],support['condition_id'])]
        support['state_id']=maps['state'][support['state_id']]
    return bundle,inventory,declarations,relations,decisions,links


def typed():
    bundle,inventory,declarations,relations,decisions,links=split_fixture()
    return bundle,inventory,catalogs.Declarations.model_validate(declarations),catalogs.Relations.model_validate(relations),decisions,links


def test_nested_scientific_declarations_and_explicit_links_survive_projection():
    bundle,inventory,declarations,relations,decisions,links=typed()
    declared=catalogs.check_declarations(declarations,inventory,bundle,64)
    for schema,payload in [(catalogs.declaration_schema(bundle),declarations.model_dump()),
                           (catalogs.relation_schema(bundle,declared),relations.model_dump())]:
        jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(payload,schema)
    catalog,proof=catalogs.project(declarations,relations,bundle)
    assert proof['scientific_declarations_unchanged'] and not proof['scientific_acceptance']
    assert catalog.samples[0].model_dump(exclude={'id'})==declarations.samples[0].model_dump(exclude={'states'})
    assert catalog.states[0].model_dump(exclude={'id','sample_id','conditions'})==declarations.samples[0].states[0].model_dump(exclude={'conditions'})
    for generated,declared_condition in zip(catalog.states[0].conditions,declarations.samples[0].states[0].conditions):
        assert generated.model_dump(exclude={'id'})==declared_condition.model_dump()
    assert catalog.protocols[1].evidence[-1].fields==['/context_uses/0']
    group=items.ItemGroup(schema_version='materials-source-item-group/1',work_id=bundle.work_id,decisions=decisions)
    graph,coverage,_=items.assemble(bundle,inventory,catalog,group.decisions,items.ContextLinks.model_validate(links))
    assert coverage['valid'] and validate_extraction(graph.expand(bundle),bundle)['valid']


@pytest.mark.parametrize('where,kind,unit',[('condition','delay','nA'),('condition','carrier_density','nA'),('parameter','magnetic_flux_density','nm')])
def test_reported_context_units_cannot_be_coerced_into_unrelated_dimensions(where,kind,unit):
    bundle,_,declarations,_,_,_=split_fixture()
    quantity=deepcopy(declarations['samples'][0]['states'][0]['conditions'][0]['quantity']);quantity['unit']=unit
    if where=='condition':
        condition=declarations['samples'][0]['states'][0]['conditions'][0]
        condition.update(kind=kind,quantity=quantity)
    else:declarations['protocols'][0]['parameters']=[dict(kind=kind,name_raw='reported parameter',quantity=quantity)]
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(declarations,catalogs.declaration_schema(bundle))


@pytest.mark.parametrize('mutation',['missing_condition','wrong_state','phantom_sample','duplicate_use','missing_protocol'])
def test_relations_cannot_bind_planned_missing_or_differently_owned_objects(mutation):
    bundle,inventory,declarations,relations,_,_=split_fixture()
    extra=deepcopy(declarations['samples'][0]['states'][0]);extra['conditions']=[]
    extra['evidence']=[r for r in extra['evidence'] if all(not f.startswith('/conditions') for f in r['fields'])]
    declarations['samples'][0]['states'].append(extra)
    declared,_=catalogs.declare(catalogs.Declarations.model_validate(declarations))
    use=relations['protocol_uses']['protocol:2']['uses'][0]
    if mutation=='missing_condition':use['condition_id']='planned-but-not-declared'
    if mutation=='wrong_state':use['state_id']='state:1:2'
    if mutation=='phantom_sample':relations['sample_relations'][0]['to_sample_id']='planned-sample'
    if mutation=='duplicate_use':relations['protocol_uses']['protocol:2']['uses'].append(deepcopy(use))
    if mutation=='missing_protocol':relations['protocol_uses'].pop('protocol:1')
    if mutation!='duplicate_use':
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate(relations,catalogs.relation_schema(bundle,declared))
    with pytest.raises(ValueError):catalogs.check_relations(catalogs.Relations.model_validate(relations),declared,bundle)


def test_component_cycles_are_rejected_without_dropping_an_edge():
    bundle,_,declarations,relations,_,_=typed()
    first=relations.sample_relations[0]
    reverse=first.model_copy(update={'from_sample_id':first.to_sample_id,'to_sample_id':first.from_sample_id})
    relations.sample_relations.append(reverse)
    with pytest.raises(ValidationError,match='cyclic_component_containment'):catalogs.project(declarations,relations,bundle)
    assert len(relations.sample_relations)==2


def test_declaration_evidence_must_refer_to_its_actual_body():
    bundle,inventory,declarations,_,_,_=typed()
    declarations.protocols[0].evidence[0].fields=['/context_uses/0']
    with pytest.raises(ValueError,match='staged_declaration_evidence_owner_invalid'):
        catalogs.check_declarations(declarations,inventory,bundle,64)


@pytest.mark.parametrize('failure',[None,2,4])
def test_worker_preserves_split_stage_failures_and_replays_private_archive(tmp_path,failure):
    parent,_,_,_,_=parent_packet(tmp_path)
    bundle,_,declarations,relations,decisions,links=split_fixture()
    keys=list(decisions)
    responses=[declarations,relations,*[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
        decisions={k:decisions[k] for k in keys[i:i+2]}) for i in range(0,len(keys),2)],links]
    provider=StageProvider(responses,fail_at=failure);store=Store(tmp_path/'split')
    job=item_worker.enqueue(store,parent,workflow='source_item_stages_v2',group_size=2)
    result=run_one(store,job_id=job,provider_override=provider)
    assert result['state']==('failed' if failure else 'succeeded'),result
    packet=import_packet(store,job);verify_packet(packet)
    assert len(packet['rows']['results'])==({None:5,2:0,4:2}[failure])
    assert packet['receipt']['declared_catalog']
    if failure==4:assert packet['receipt']['staged_assembly']['missing_item_ids']==['I3','I4','I5']
    if failure==2:assert packet['receipt']['catalog_projection'] is None
    database=ProposalDatabase(tmp_path/'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert json.loads(db.execute('SELECT payload FROM runs').fetchone()[0])==packet
    if not failure:
        tampered=deepcopy(packet['receipt']);tampered['catalog_projection']['id_assignments'][0]['entity_id']='foreign'
        with pytest.raises(ValueError,match='staged_receipt_assembly_mismatch'):
            item_worker.verify_receipt(tampered,bundle,packet['raw_output'])
    assert not packet['ml_training_eligible'] and not packet['scientific_acceptance']


def test_unresolved_relation_decision_is_explicit_and_never_scientific_acceptance():
    bundle,_,declarations,relations,_,_=typed()
    relations.protocol_uses['protocol:1']=catalogs.NoUses(resolution='unresolved',uses=[],explanation='No source-supported condition mapping.')
    catalog,proof=catalogs.project(declarations,relations,bundle)
    assert proof['unresolved_protocol_ids']==['protocol:1']
    assert catalog.limitations[-1].startswith('System: unresolved catalog')


@pytest.mark.parametrize('mode',['strict','diagnostic'])
def test_nonexistent_field_evidence_is_retained_and_cannot_pass_validation(tmp_path,mode):
    parent,_,_,_,_=parent_packet(tmp_path)
    bundle,_,declarations,relations,decisions,links=split_fixture()
    assert declarations['samples'][0]['substrate_raw'] is None
    declarations['samples'][0]['evidence'].append({'fields':['/substrate_raw'],'span_ids':['S1']})
    keys=list(decisions)
    responses=[declarations,relations,*[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
        decisions={k:decisions[k] for k in keys[i:i+2]}) for i in range(0,len(keys),2)],links]
    store=Store(tmp_path/'split');provider=StageProvider(responses)
    job=item_worker.enqueue(store,parent,workflow='source_item_stages_v2',group_size=2,catalog_evidence_mode=mode)
    result=run_one(store,job_id=job,provider_override=provider)
    assert result['state']=='quarantined'
    packet=import_packet(store,job);verify_packet(packet)
    if mode=='strict':
        assert provider.calls==1 and len(packet['rows']['results'])==0
    else:
        assert provider.calls==6 and len(packet['rows']['results'])==5
        receipt=packet['receipt']
        assert any(i['code']=='evidence_field_not_present' for i in receipt['catalog_diagnostic']['issues'])
        assert any(i['code']=='evidence_field_not_present' for i in receipt['validation']['issues'])
        assert receipt['declared_catalog']['samples'][0]['evidence'][-1]['fields']==['/substrate_raw']
        assert all(r['review_status']=='quarantined' for r in packet['rows']['results'])
    assert not packet['scientific_acceptance']
