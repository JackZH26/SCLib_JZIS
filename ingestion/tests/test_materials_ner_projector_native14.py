"""Explicit native /14 producer integration; synthetic lifecycle, not model accuracy."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from ingestion.materials_ner import source_projector as projector, projector_schema
from ingestion.materials_ner import reviewed_reader as reader, projector_proposals, projection_binding
from ingestion.materials_ner.contract import canonical, parse_extraction
from ingestion.materials_ner.providers import ProviderResult
from ingestion.materials_ner.proposals import ProposalDatabase, verify_packet
from ingestion.materials_ner.store import Store
from test_materials_ner_catalog_projector import catalog_case
from test_materials_ner_reviewed_proposals import prepared
from test_materials_ner_extrapolation import source_graph


class Native14Provider:
    def __init__(self, graph):
        self.graph = graph
        self.calls = 0

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['model'] == 'gpt-6-luna' and config['reasoning'] == 'medium'
        assert config['graph_schema'] == schema['properties']['schema_version']['const'] == 'materials-ner/14'
        assert config['interface_version'] == projector_schema.NATIVE14_VERSION
        text = canonical(self.graph)
        (directory/'response.json').write_text(text)
        return ProviderResult(text, {'input_tokens':10,'output_tokens':20}, 'codex', 'gpt-6-luna', 'synthetic', .1)


def upgrade(catalog_case, tmp_path):
    path, _, graph = catalog_case
    request = json.loads(path.read_bytes())
    request.update(schema=projector.NATIVE14_INPUT_SCHEMA, graph_schema='materials-ner/14')
    target = tmp_path/'native14-request.json'; reader.put(target, request)
    graph = deepcopy(graph); graph['schema_version'] = 'materials-ner/14'
    return target, graph


def test_explicit_capability_changes_no_original_input_or_old_request(catalog_case, tmp_path):
    old_path, old, _ = catalog_case
    target, _ = upgrade(catalog_case, tmp_path); new = projector.prepare(target)
    assert projector.prepare(old_path)['schema'] == old['schema']
    assert projector.prepare(old_path)['prompt'] == old['prompt']
    assert new['bundle'] == old['bundle'] and new['scope'] == old['scope']
    assert new['source_catalog'] == old['source_catalog'] and new['coverage'] == old['coverage']
    assert new['schema'] != old['schema'] and new['prompt'] != old['prompt']
    assert 'Native /14 capability policy:' in new['prompt']
    assert 'Native /14 capability policy:' not in old['prompt']
    assert projector.configuration(new)['interface_version'] == projector_schema.NATIVE14_VERSION
    assert projector.configuration(old)['interface_version'] == projector_schema.VERSION


@pytest.mark.parametrize('mutation', ['old_with_selector','missing_selector','unknown_contract','missing_catalog','quote_transport','unknown_field'])
def test_no_implicit_or_ambiguous_contract_upgrade(catalog_case, tmp_path, mutation):
    path, _ = upgrade(catalog_case, tmp_path); request = json.loads(path.read_bytes())
    if mutation == 'old_with_selector':request['schema'] = projector.INPUT_SCHEMA
    elif mutation == 'missing_selector':request.pop('graph_schema')
    elif mutation == 'unknown_contract':request['graph_schema'] = 'materials-ner/15'
    elif mutation == 'missing_catalog':request.pop('evidence_transport')
    elif mutation == 'quote_transport':request['require_context_quote'] = True
    else:request['infer_scientific_facts'] = True
    with pytest.raises(ValueError, match='projector_input_shape'):projector.request_contract(request)


def test_native14_complete_attempt_portable_packet_and_idempotent_store(catalog_case, tmp_path, monkeypatch):
    path, graph = upgrade(catalog_case, tmp_path)
    store=Store(tmp_path/'native14-queue'); job=projector.enqueue(store,path); fake=Native14Provider(graph)
    result=projector.run(store,job,provider_override=fake)
    assert result['state']=='succeeded',result
    assert projector.run(Store(store.root),job,provider_override=fake)==result and fake.calls==1
    packet=projector_proposals.build(store.root,job)
    assert packet['receipt']['extraction']['schema_version']=='materials-ner/14'
    assert packet['receipt']['validation']['validator_version']=='materials-ner-validation/1.26.0'
    assert packet['receipt']['validation']['registry_version']=='materials-quantities/3.0.0'
    assert packet['rows']['results'][0]['review_status']=='pending_review'
    assert projection_binding.scientific_payload(packet['receipt']['extraction'])==projection_binding.scientific_payload(graph)
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as connection:
        restored=json.loads(connection.execute('SELECT payload FROM runs').fetchone()[0])
        assert connection.execute('SELECT count(*) FROM results').fetchone()[0]==1
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    def forbidden(*args,**kwargs):raise AssertionError('Portable replay touched source files or provider.')
    monkeypatch.setattr(reader,'checked',forbidden);monkeypatch.setattr(fake,'extract',forbidden)
    verify_packet(restored)


def test_wrong_returned_contract_is_held_without_repair(catalog_case, tmp_path):
    path, graph=upgrade(catalog_case,tmp_path);graph['schema_version']='materials-ner/13'
    store=Store(tmp_path/'wrong-contract');job=projector.enqueue(store,path);fake=Native14Provider(graph)
    result=projector.run(store,job,provider_override=fake)
    assert result['state']=='quarantined' and result['outcome']=='graph_not_validated'
    assert json.loads(reader.checked(result['model_graph']).read_bytes())==graph
    assert projector.run(store,job,provider_override=fake)==result and fake.calls==1
    with pytest.raises(ValueError):projector_proposals.build(store.root,job)


def test_invalid_native14_graph_is_retained_without_entities(catalog_case,tmp_path):
    path,graph=upgrade(catalog_case,tmp_path);graph['results'][0]['protocol_id']='missing'
    store=Store(tmp_path/'bad-native14');job=projector.enqueue(store,path)
    result=projector.run(store,job,provider_override=Native14Provider(graph))
    assert result['error_code']=='projector_schema_invalid'
    packet=projector_proposals.build(store.root,job)
    assert not any(packet['rows'].values()) and 'extraction' not in packet['receipt']
    assert json.loads(packet['raw_output'])==graph
    verify_packet(packet)


@pytest.mark.parametrize('field,value', [('basis',None),('basis',' '),('name',None),('name',' '),('valid',None)])
def test_source_backed_native14_requirements_reach_provider_schema(prepared,field,value):
    _,graph=source_graph(prepared)
    graph=parse_extraction(graph).model_dump()
    for group in projection_binding.GROUPS:
        for entity in graph[group]:
            entity['evidence']=[dict(field=e['field'],witness_ids=['E0001']) for e in entity['evidence']]
    if field=='basis':graph['states'][0]['conditions'][0]['basis_raw']=value
    elif field=='name':graph['results'][0]['quantity_name_raw']=value
    schema=projector_schema.output_schema(graph_schema='materials-ner/14',source_catalog={'spans':{'E0001':{}}})
    Draft202012Validator.check_schema(schema)
    assert Draft202012Validator(schema).is_valid(graph)==(field=='valid')
    if field=='valid':
        parse_extraction(projection_binding.native_graph(graph))
        assert not Draft202012Validator(projector_schema.output_schema(source_catalog={'spans':{'E0001':{}}})).is_valid(graph)
