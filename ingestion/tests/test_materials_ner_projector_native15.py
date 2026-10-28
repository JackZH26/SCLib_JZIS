"""Synthetic providers and source documents; no real model or scientific receipts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ingestion.materials_ner import source_projector as projector, projector_schema
from ingestion.materials_ner import reviewed_reader as reader, projector_proposals, projection_binding
from ingestion.materials_ner import paper_coverage, review_amendments as amendments
from ingestion.materials_ner.contract import Quantity, canonical, parse_extraction
from ingestion.materials_ner.contract_v5 import DefinitionParameter
from ingestion.materials_ner.providers import ProviderResult
from ingestion.materials_ner.proposals import ProposalDatabase, verify_packet
from ingestion.materials_ner.sources import Bundle
from ingestion.materials_ner.source_audit import audit_source
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import CONTEXT_CONSISTENCY_VERSION
from test_materials_ner_reviewed_reader import scope_fixture
from test_materials_ner_reviewed_proposals import graph, at, reframe, AUTHOR, NOW

TEXT = ('The sample showed a resistive onset at 5 K. The criterion is onset.\n\n'
        'The twist angle is -1.27 deg.\n\n'
        'The reported displacement field is +0.61 V/nm.\n\n'
        'The reported transition is the crossover of low and high temperature linear fits.\n')


class SyntheticNative15Provider:
    def __init__(self, graph):
        self.graph, self.calls = graph, 0

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['model'] == 'gpt-6-luna' and config['reasoning'] == 'medium'
        assert config['graph_schema'] == schema['properties']['schema_version']['const'] == 'materials-ner/15'
        assert config['interface_version'] == projector_schema.NATIVE15_VERSION
        assert config['consistency_version'] == CONTEXT_CONSISTENCY_VERSION
        output = canonical(self.graph)
        (directory/'response.json').write_text(output)
        return ProviderResult(output, {'input_tokens': 10, 'output_tokens': 20},
                              'codex', 'gpt-6-luna', 'synthetic', .1)


@pytest.fixture
def native15_case(tmp_path):
    path = scope_fixture(tmp_path/'synthetic-inputs', text=TEXT)
    scope = json.loads(path.read_bytes()); pre_path = Path(scope['preflight']['path'])
    pre = json.loads(pre_path.read_bytes()); bundle = Bundle.model_validate_json(Path(pre['bundle']['path']).read_bytes())
    Path(pre['structure']['path']).write_text(canonical(audit_source(Path(pre['original']['path']),work_id=bundle.work_id,bundle=bundle)))
    pre['structure'] = reader.reference(pre['structure']['path']); pre_path.write_text(canonical(pre))
    scope['preflight'] = reader.reference(pre_path); path.write_text(canonical(scope))
    manifest = paper_coverage.seed(scope['preflight'], author=AUTHOR, created_at=NOW)
    roles = deepcopy(manifest['roles'])
    roles[0].update(role='main',note='Synthetic source for integration tests only.',anchors=[at(bundle.blocks[0],TEXT)])
    manifest = reframe(manifest,bundle,roles=roles)
    mp = tmp_path/'coverage.json'; reader.put(mp,manifest)
    request = tmp_path/'native15-input.json'
    reader.put(request,dict(schema=projector.NATIVE15_INPUT_SCHEMA,graph_schema='materials-ner/15',
        scope=reader.reference(path),coverage=reader.reference(mp),evidence_transport='source_catalog',
        consistency_version=CONTEXT_CONSISTENCY_VERSION))
    prepared = projector.prepare(request); g = graph(bundle); g['schema_version'] = 'materials-ner/15'
    st = g['states'][0]; block = bundle.blocks[0]
    for identifier,kind,role,raw,value,unit,basis in [
        ('angle','twist_angle','sample_geometry','-1.27 deg',-1.27,'deg',TEXT.split('\n\n')[1]),
        ('D','reported_displacement_field','measurement','+0.61 V/nm',.61,'V/nm',TEXT.split('\n\n')[2]),
    ]:
        i = len(st['conditions']); st['conditions'].append(dict(id=identifier,kind=kind,role=role,
            quantity=Quantity(status='reported',raw=raw,relation='exact',value=value,unit=unit).model_dump(),
            basis_raw=basis,orientation_raw=None,window_position=None))
        st['evidence'] += [dict(field=f'/conditions/{i}'+suffix,**at(block,basis))
            for suffix in ('','/kind','/role','/basis_raw','/quantity','/quantity/raw','/quantity/unit')]
    result = g['results'][0]; criterion = TEXT.split('\n\n')[3].strip()
    result['definition'] = dict(criterion='linear_fit_intersection',criterion_raw=criterion,parameters=[])
    result['evidence'] = [e for e in result['evidence'] if not e['field'].startswith('/definition')]
    result['evidence'] += [dict(field='/definition/'+field,**at(block,criterion)) for field in ('criterion','criterion_raw')]
    result['evidence'] += [dict(field='/quantity/'+field,**at(block,'5 K')) for field in ('raw','unit')]
    g['limitations'] = ['Synthetic integration source and provider; no scientific admission.']
    for group in projection_binding.GROUPS:
        for entity in g[group]:
            for e in entity['evidence']:
                ids = [key for key,span in prepared['source_catalog']['spans'].items()
                    if span['block_id']==e['block_id'] and span['start_char']<e['end_char'] and span['end_char']>e['start_char']]
                assert ids
                field=e['field'];e.clear();e.update(field=field,witness_ids=ids)
    return request, prepared, g


def test_native15_schema_and_source_only_prompt(native15_case):
    _, p, g = native15_case
    Draft202012Validator.check_schema(p['schema']); assert Draft202012Validator(p['schema']).is_valid(g)
    assert p['source_catalog']['reference_answers_used'] is False
    assert 'Native /15 capability policy:' in p['prompt']
    assert '"reported_displacement_field":["V/nm"]' in p['prompt']
    assert 'context_quote' not in p['prompt']
    assert any(Path(pin['path']).name=='native15.txt' for pin in projector.configuration(p)['implementation'])
    assert parse_extraction(projection_binding.native_graph(g)).schema_version == 'materials-ner/15'


@pytest.mark.parametrize('mutation',['old_request','old_graph','no_consistency','bad_consistency','no_catalog','context_quote','wrong_interface','null_interface','execution_profile','extra'])
def test_native15_requires_explicit_unambiguous_request(native15_case,mutation):
    path, _, _ = native15_case; request=json.loads(path.read_bytes())
    if mutation=='old_request': request['schema']=projector.NATIVE14_INPUT_SCHEMA
    elif mutation=='old_graph': request['graph_schema']='materials-ner/14'
    elif mutation=='no_consistency': request.pop('consistency_version')
    elif mutation=='bad_consistency': request['consistency_version']=None
    elif mutation=='no_catalog': request.pop('evidence_transport')
    elif mutation=='context_quote': request['require_context_quote']=True
    elif mutation=='wrong_interface': request['interface_version']=projector_schema.CONSOLIDATED_NATIVE14_VERSION
    elif mutation=='null_interface': request['interface_version']=None
    elif mutation=='execution_profile': request['execution_profile']={'model':'gpt-6.1-sol'}
    else: request['invent_science']=True
    with pytest.raises(ValueError): projector.request_contract(request)


@pytest.mark.parametrize('mutation',['angle_basis','field_basis','criterion_basis','fraction','valid'])
def test_native15_structural_invariants_reach_provider(native15_case,mutation):
    _, p, g = native15_case; g=deepcopy(g)
    if mutation=='angle_basis':g['states'][0]['conditions'][0]['basis_raw']=None
    elif mutation=='field_basis':g['states'][0]['conditions'][1]['basis_raw']=' '
    elif mutation=='criterion_basis':g['results'][0]['definition']['criterion_raw']=None
    elif mutation=='fraction':g['results'][0]['definition']['parameters']=[DefinitionParameter(
        kind='resistance_fraction',name_raw='50% resistance criterion',
        quantity=Quantity(status='reported',raw='50%',relation='exact',value=50,unit='%')).model_dump()]
    assert Draft202012Validator(p['schema']).is_valid(g)==(mutation=='valid')


def synthetic_packet(native15_case,tmp_path):
    path,_,g=native15_case;store=Store(tmp_path/'synthetic-projector');job=projector.enqueue(store,path)
    fake=SyntheticNative15Provider(g); result=projector.run(store,job,provider_override=fake)
    assert result['state']=='succeeded',result
    assert projector.run(Store(store.root),job,provider_override=fake)==result and fake.calls==1
    return projector_proposals.build(store.root,job),fake


def synthetic_amendment(parent):
    anchor=at(Bundle.model_validate(parent['bundle']).blocks[0],TEXT.split('\n\n')[1])
    a=amendments.build(parent,bundle=parent['bundle'],author=AUTHOR,created_at=NOW,
        changes=[dict(path='/states/0/label',before=None,after='Synthetic reviewed state',reason='Synthetic review transport only.',anchors=[anchor])],
        reviews=[dict(result_id='r',fields={f:dict(disposition='not_reviewed',note='Not an independent scientific review.',anchors=[]) for f in amendments.FIELDS},holds=['independent_review_pending'])])
    amendments.verify(a,parent)
    return a


def test_native15_attempt_packet_storage_amendment_and_portable_replay(native15_case,tmp_path,monkeypatch):
    packet,fake=synthetic_packet(native15_case,tmp_path)
    validation=packet['receipt']['validation']
    assert validation['validator_version']=='materials-ner-validation/1.29.0'
    assert validation['registry_version']=='materials-quantities/4.0.0'
    assert validation['normalized']['/states/0/conditions/0/quantity']['normalized']['value']==-1.27
    assert validation['normalized']['/states/0/conditions/1/quantity']['normalized'] is None
    assert projection_binding.scientific_payload(packet['receipt']['extraction'])==projection_binding.scientific_payload(native15_case[2])
    db=ProposalDatabase(tmp_path/'synthetic-candidates')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as c:
        restored=json.loads(c.execute('SELECT payload FROM runs').fetchone()[0])
        assert c.execute('SELECT count(*) FROM results').fetchone()[0]==1
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    amendment=synthetic_amendment(restored);mapping=amendments.review_mapping(amendment)
    assert mapping['schema']=='materials-reviewed-result-mapping/1'
    assert mapping['records'][0]['result_semantics']['version']=='materials-result-semantics/2'
    assert not any(restored[k] for k in ['scientific_acceptance','ml_training_eligible'])
    assert mapping['records'][0]['target_table'] is None
    with pytest.raises(ValueError,match='canonical_tc_mapping_contract_not_qualified'):amendments.tc_mapping(amendment)
    def forbidden(*args,**kwargs):raise AssertionError('Portable replay accessed source or provider')
    monkeypatch.setattr(reader,'checked',forbidden);monkeypatch.setattr(fake,'extract',forbidden)
    verify_packet(restored);amendments.verify(amendment,restored)


def test_wrong_contract_and_scientific_value_are_not_repaired(native15_case,tmp_path):
    path,p,g=native15_case;g=deepcopy(g);g['states'][0]['conditions'][1]['quantity']['value']=-.61
    store=Store(tmp_path/'bad-sign');job=projector.enqueue(store,path)
    result=projector.run(store,job,provider_override=SyntheticNative15Provider(g))
    assert result['state']=='quarantined'
    packet=projector_proposals.build(store.root,job);verify_packet(packet)
    assert packet['receipt']['extraction']['states'][0]['conditions'][1]['quantity']['value']==-.61
    assert 'numeric_value_disagrees_with_raw' in {i['code'] for i in packet['receipt']['validation']['issues']}
    assert not packet['scientific_acceptance']
