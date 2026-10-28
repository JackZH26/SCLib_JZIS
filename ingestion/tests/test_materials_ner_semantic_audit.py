"""Typed-facet and shared-witness checks; synthetic decisions are not Gold."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ingestion.materials_ner import assertion_audit as audit, semantic_audit as semantic, semantic_claims as claims
from ingestion.materials_ner import reviewed_reader as reader
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.store import Store
from test_materials_ner_assertion_audit import queued, Fake
from test_materials_ner_reviewed_proposals import prepared


@pytest.fixture
def typed_prepared(queued,tmp_path):
    _,base,_,_,_=queued
    path=tmp_path/'semantic.json';reader.put(path,semantic.build_input(reader.reference(base)))
    return path,audit.prepare(path)


class TypedFake(Fake):
    def extract(self,prompt,schema,config,directory):
        assert schema['required']==['witnesses','decisions']
        return super().extract(prompt,schema,config,directory)


def abstentions(p):
    return dict(witnesses=[],decisions={t['id']:dict(status='insufficient_source',reason='Synthetic abstention.',witness_ids=[]) for t in p['targets']})


def witness(p,quote='5 K',identifier='W1'):
    b=p['bundle'].blocks[0]
    return dict(id=identifier,block_id=b.id,quote=quote,context_quote=b.text)


def evaluation(p,response,tmp_path):
    directory=tmp_path/'evaluate';directory.mkdir();result={}
    semantic.evaluate(p,canonical(response),directory,result)
    return result,json.loads(reader.checked(result['audit_validation']).read_text())


def test_inventory_covers_criterion_defaults_dependencies_and_all_native_properties(typed_prepared):
    _,p=typed_prepared;graph=deepcopy(p['graph'])
    graph['results'][0]['definition']['criterion']='unspecified'
    inventory=claims.generate(graph);targets=inventory['targets']
    assert any(t['facet']=='criterion' and '/results/0/definition' in t['paths'] for t in targets)
    assert any(t['facet']=='derived_parent' and '/results/0/dependencies' in t['paths'] for t in targets)
    assert any(t['facet']=='qualifier' and '/results/0/qualifiers' in t['paths'] for t in targets)
    covered=set(inventory['covered_entity_leaf_paths']);absent={x['path'] for x in inventory['sparse_optional_absences']}
    assert set(inventory['entity_leaf_paths'])==covered|absent
    assert not inventory['independent_scientific_claim_census']
    assert not any(t['paths']==['/results/0/quantity'] for t in targets)
    assert len([t for t in targets if t['facet']=='raw_literal' and t['paths']==['/results/0/quantity/raw']])==1


def test_unsupported_entity_field_is_not_silently_covered(typed_prepared):
    _,p=typed_prepared;g=deepcopy(p['graph']);g['results'][0]['invented_field']='not a contract field'
    with pytest.raises(ValueError):claims.generate(g)


def test_typed_policy_separates_independent_scientific_axes(typed_prepared):
    _,p=typed_prepared
    assert 'independent of primary/cited' in claims.FACETS['origin']
    assert 'Origin uncertainty alone' in claims.FACETS['source_role']
    assert 'does not assert exactness' in claims.FACETS['raw_literal']
    assert 'approximation' in claims.FACETS['qualification']
    assert 'needs_completion' in claims.FACETS['criterion']
    assert 'does not assert' in claims.FACETS['applicability']
    assert 'criterion' in {t['facet'] for t in p['targets']}


def test_one_shared_witness_can_support_distinct_facets_without_merging_decisions(typed_prepared,tmp_path):
    _,p=typed_prepared;response=abstentions(p);response['witnesses']=[witness(p)]
    targets=[t for t in p['targets'] if t['facet'] in {'value_shape','raw_literal'} and any(path.startswith('/results/0/quantity/') for path in t['paths'])]
    assert len(targets)==2
    for t in targets:response['decisions'][t['id']]=dict(status='supported',reason='Synthetic source-backed opinion.',witness_ids=['W1'])
    result,report=evaluation(p,response,tmp_path)
    assert result['state']=='succeeded' and report['unique_witnesses']==1 and report['witness_references']==2
    assert not report['semantic_validation_qualified'] and not report['scientific_acceptance']


@pytest.mark.parametrize('case',['needs_completion','contradicted','supported'])
def test_non_abstention_requires_witnesses(typed_prepared,tmp_path,case):
    _,p=typed_prepared;response=abstentions(p);first=next(iter(response['decisions']))
    response['decisions'][first]['status']=case
    result,report=evaluation(p,response,tmp_path)
    assert result['state']=='quarantined' and report['schema_issues']


def test_reported_omission_is_distinct_from_source_insufficiency(typed_prepared,tmp_path):
    _,p=typed_prepared;response=abstentions(p);t=next(t for t in p['targets'] if t['facet']=='criterion')
    response['witnesses']=[witness(p,'onset')]
    # Use a unique sentence as locator; 'onset' occurs in several sentences.
    response['witnesses'][0]['context_quote']='The sample showed a resistive onset at 5 K.'
    response['decisions'][t['id']]=dict(status='needs_completion',reason='Synthetic missing-field diagnosis.',witness_ids=['W1'])
    result,report=evaluation(p,response,tmp_path)
    assert result['state']=='succeeded' and report['model_status_counts']['needs_completion']==1
    assert report['automatic_repairs']==0


@pytest.mark.parametrize('case',['duplicate_id','unknown_id','unused','duplicate_reference','fake_quote','missing_decision','replacement'])
def test_shared_catalogue_cannot_hide_invalid_decisions_or_witnesses(typed_prepared,tmp_path,case):
    _,p=typed_prepared;response=abstentions(p);t=next(t for t in p['targets'] if t['facet']=='origin')
    response['witnesses']=[witness(p)];response['decisions'][t['id']]=dict(status='supported',reason='Synthetic.',witness_ids=['W1'])
    if case=='duplicate_id':response['witnesses'].append(witness(p))
    if case=='unknown_id':response['decisions'][t['id']]['witness_ids']=['missing']
    if case=='unused':response['witnesses'].append(witness(p,identifier='unused'))
    if case=='duplicate_reference':response['decisions'][t['id']]['witness_ids']=['W1','W1']
    if case=='fake_quote':response['witnesses'][0]['quote']='made up 777 K'
    if case=='missing_decision':response['decisions'].pop(t['id'])
    if case=='replacement':response['decisions'][t['id']]['replacement_value']='computed'
    result,report=evaluation(p,response,tmp_path)
    assert result['state']=='quarantined' and not report['scientific_acceptance']


def test_context_only_quantity_is_held_but_context_may_supplement_target(typed_prepared,tmp_path):
    _,p=typed_prepared;response=abstentions(p);response['witnesses']=[witness(p)]
    t=next(t for t in p['targets'] if t['facet']=='value_shape' and t['requires_target'])
    response['decisions'][t['id']]=dict(status='supported',reason='Synthetic.',witness_ids=['W1'])
    changed={**p,'scope':deepcopy(p['scope'])}
    for span in changed['scope']['passages']:span['role']='context'
    result,report=evaluation(changed,response,tmp_path)
    assert result['state']=='quarantined'
    assert 'semantic_required_target_witness_missing' in {h['code'] for row in report['rows'] for h in row['holds']}


def test_false_literal_support_with_real_unrelated_quote_is_held(typed_prepared,tmp_path):
    _,p=typed_prepared;response=abstentions(p);response['witnesses']=[witness(p,'The sample')]
    t=next(t for t in p['targets'] if t['facet']=='raw_literal' and t['paths']==['/results/0/quantity/raw'])
    response['decisions'][t['id']]=dict(status='supported',reason='Synthetic false literal support.',witness_ids=['W1'])
    result,report=evaluation(p,response,tmp_path)
    assert result['state']=='quarantined'
    assert any(h['code']=='semantic_supported_literal_not_in_witness' for row in report['rows'] for h in row['holds'])


def test_control_claim_is_typed_and_its_own_context_contains_the_mutation(queued,tmp_path):
    _,base,_,_,_=queued
    controls=[dict(id='C1',facet='criterion',graph_pointer='/results/0/definition/criterion',candidate_value='zero_resistance')]
    inp=semantic.build_input(reader.reference(base),controls=controls);path=tmp_path/'control.json';reader.put(path,inp)
    p=audit.prepare(path);assert p['targets'][0]['subject_context']['definition']['criterion']=='zero_resistance'
    assert p['request']['mode']=='synthetic_controls' and len(p['targets'])==1
    assert 'expected' not in inp and 'current_issues' not in p['prompt'] and 'current_witnesses' not in p['prompt']
    bad=deepcopy(controls);bad[0]['expected']='contradicted'
    with pytest.raises(ValueError,match='control_shape'):semantic.build_input(reader.reference(base),controls=bad)
    bad=deepcopy(controls);bad[0]['candidate_value']='invented_enum'
    with pytest.raises(ValueError):semantic.build_input(reader.reference(base),controls=bad)
    bad=deepcopy(controls);bad[0]['facet']='origin'
    with pytest.raises(ValueError,match='facet_mismatch'):semantic.build_input(reader.reference(base),controls=bad)


def test_preparation_detects_changed_manifest_and_does_not_dispatch(typed_prepared,tmp_path):
    path,p=typed_prepared;inp=json.loads(path.read_text());inp['targets'].pop();path.write_text(canonical(inp))
    with pytest.raises(ValueError,match='manifest_drift'):audit.prepare(path)


def test_v2_runs_on_shared_lifecycle_without_extra_attempt_or_graph_change(typed_prepared,tmp_path):
    path,p=typed_prepared;store=Store(tmp_path/'semantic-queue');job=audit.enqueue(store,path);fake=TypedFake(abstentions(p))
    first=audit.run(store,job,provider_override=fake)
    assert first['state']=='succeeded' and not first['scientific_payload_changed']
    assert not first['proposal_generated'] and not first['semantic_validation_qualified']
    assert audit.run(Store(store.root),job,provider_override=fake)==first and fake.calls==1
    copied=path.with_name('copied.json');copied.write_bytes(path.read_bytes());assert audit.enqueue(store,copied)==job
    assert store.summary()['attempts']==1 and not (store.root/'proposals.sqlite3').exists()


def catalog_prepared(base_path,tmp_path):
    base=json.loads(base_path.read_text())['base_input'];path=tmp_path/'catalog-input.json'
    reader.put(path,semantic.build_input(base,evidence_transport='source_catalog'))
    return path,audit.prepare(path)


def test_source_catalog_is_neutral_original_text_with_closed_response_ids(typed_prepared,tmp_path):
    path,_=typed_prepared;_,p=catalog_prepared(path,tmp_path)
    cat=p['source_catalog'];assert cat['semantic_annotations'] is False and not cat['reference_answers_used']
    assert p['schema']['required']==['decisions']
    ids=p['schema']['$defs']['Decision']['anyOf'][0]['properties']['witness_ids']['items']['enum']
    assert ids==list(cat['spans'])
    for span in cat['spans'].values():
        block=next(b for b in p['bundle'].blocks if b.id==span['block_id'])
        assert block.text[span['start_char']:span['end_char']]==span['text']
    assert 'Return a shared witness catalogue:' not in p['prompt']
    assert 'Select original evidence IDs' in p['prompt']


@pytest.mark.parametrize('change',['text','offset','role'])
def test_source_catalog_tampering_is_rejected(typed_prepared,tmp_path,change):
    from ingestion.materials_ner import scoped_evidence as se
    path,_=typed_prepared;_,p=catalog_prepared(path,tmp_path);cat=deepcopy(p['source_catalog']);first=next(iter(cat['spans']))
    if change=='text':cat['spans'][first]['text']='fabricated original'
    if change=='offset':cat['spans'][first]['start_char']+=1
    if change=='role':cat['spans'][first]['role']='context'
    with pytest.raises(ValueError,match='catalog_drift'):se.selected(cat,[first],p['bundle'],p['scope'],p['coverage'])


def test_source_catalog_preserves_target_context_boundaries_and_refuses_overlap(typed_prepared):
    from ingestion.materials_ner import scoped_evidence as se
    _,p=typed_prepared;scope=deepcopy(p['scope']);block=p['bundle'].blocks[0];cut=block.text.index('The criterion')
    scope['passages']=[dict(block_id=block.id,start_char=0,end_char=cut,role='target'),
        dict(block_id=block.id,start_char=cut,end_char=len(block.text),role='context')]
    cat=se.build(p['bundle'],scope);out=se.selected(cat,list(cat['spans']),p['bundle'],scope,p['coverage'])
    assert len(out)==2 and out[0]['end_char']==cut and out[1]['start_char']==cut
    scope['passages'][1]['start_char']-=1
    with pytest.raises(ValueError,match='catalog_overlap'):se.build(p['bundle'],scope)


@pytest.mark.parametrize('invalid',['E99999','repeat'])
def test_source_catalog_rejects_unknown_or_repeated_references(typed_prepared,tmp_path,invalid):
    path,_=typed_prepared;_,p=catalog_prepared(path,tmp_path);response=abstentions(p);response.pop('witnesses')
    t=next(t for t in p['targets'] if t['facet']=='origin');first=next(iter(p['source_catalog']['spans']))
    response['decisions'][t['id']]=dict(status='supported',reason='Synthetic.',witness_ids=[first,first] if invalid=='repeat' else [invalid])
    result,report=evaluation(p,response,tmp_path)
    assert result['state']=='quarantined' and not report['scientific_acceptance']


def test_source_catalog_witnesses_are_copied_and_replayed_without_new_call(typed_prepared,tmp_path):
    path,_=typed_prepared;path,p=catalog_prepared(path,tmp_path);response=abstentions(p);response.pop('witnesses')
    t=next(t for t in p['targets'] if t['facet']=='raw_literal' and t['paths']==['/results/0/quantity/raw'])
    first=next(iter(p['source_catalog']['spans']))
    response['decisions'][t['id']]=dict(status='supported',reason='Synthetic literal check.',witness_ids=[first])
    store=Store(tmp_path/'catalog-queue');job=audit.enqueue(store,path);fake=Fake(response)
    result=audit.run(store,job,provider_override=fake)
    assert result['state']=='succeeded' and result['unique_witnesses']==1 and not result['scientific_acceptance']
    assert audit.run(store,job,provider_override=fake)==result and fake.calls==1
    catalog=Path(result['source_catalog']['path']);catalog.write_text(catalog.read_text()+'\n')
    with pytest.raises(ValueError):audit.run(store,job,provider_override=fake)
    assert fake.calls==1
