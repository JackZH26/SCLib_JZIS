"""No-provider lifecycle, source isolation and replay tests for automatic drafts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ingestion.materials_ner import source_projector as projector, reviewed_reader as reader
from ingestion.materials_ner import paper_coverage as pc, source_tuple_eval
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_reviewed_proposals import prepared, graph


class Fake:
    def __init__(self, graph, error=None):
        self.text = canonical(graph)
        self.calls = 0
        self.error = error

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['model'] == 'gpt-6-luna' and config['reasoning'] == 'medium'
        assert schema['properties']['schema_version']['const'] == 'materials-ner/13'
        (directory / 'response.json').write_text(self.text)
        (directory / 'events.jsonl').write_text('{"type":"turn.completed"}\n')
        if self.error:
            raise self.error
        return ProviderResult(self.text, {'input_tokens':10, 'output_tokens':20}, 'codex', 'gpt-6-luna', 'synthetic', .1)


@pytest.fixture
def queued(prepared, tmp_path):
    _, _, scope, bundle, manifest = prepared
    mp = tmp_path / 'coverage.json'; mp.write_text(canonical(manifest))
    path = tmp_path / 'input.json'
    path.write_text(canonical(dict(schema=projector.INPUT_SCHEMA, scope=reader.reference(scope), coverage=reader.reference(mp))))
    store = Store(tmp_path / 'projector')
    return store, path, projector.enqueue(store, path), bundle, manifest


def test_reference_assertions_never_enter_prompt(queued):
    _, path, _, bundle, m = queued
    before = projector.prepare(path)
    a = dict(id='private-reference', kind='text_result', visual=None,
        anchor=dict(block_id=bundle.blocks[0].id, start_char=0, end_char=3, quote='The'),
        note='PRIVATE_EXPECTED_ANSWER_NEVER_SEND')
    m = pc.build(bundle=bundle, **{**{k:m[k] for k in ('source','roles','visuals','dependencies','supplement','author','created_at')}, 'assertions':[a]})
    req = json.loads(path.read_text()); mp = Path(req['coverage']['path']); mp.write_text(canonical(m))
    req['coverage'] = reader.reference(mp); path.write_text(canonical(req))
    after = projector.prepare(path)
    assert after['prompt'] == before['prompt'] and 'PRIVATE_EXPECTED_ANSWER' not in after['prompt']
    req['reference_answers'] = [5]; path.write_text(canonical(req))
    with pytest.raises(ValueError, match='projector_input_shape'):
        projector.prepare(path)


def test_legacy_dispatch_and_multiple_attempts_are_refused(queued):
    store, path, job, bundle, _ = queued
    fake = Fake(graph(bundle))
    assert store.claim(job_id=job) is None
    assert run_one(store, job_id=job, provider_override=fake) is None
    assert not fake.calls and not store.summary()['attempts']
    with pytest.raises(ValueError, match='one_automatic_attempt'):
        store.enqueue(work_id=bundle.work_id, bundle_hash=projector.row(store,job)['bundle_hash'],
            config=projector.configuration(projector.prepare(path)), max_attempts=2)


def test_one_call_replays_native_graph_without_granting_admission(queued):
    store, _, job, bundle, _ = queued; fake = Fake(graph(bundle))
    first = projector.run(store, job, provider_override=fake)
    assert first['state'] == 'succeeded', first
    assert first == projector.run(Store(store.root), job, provider_override=fake)
    assert fake.calls == 1 and store.summary()['attempts'] == 1
    assert not any(first[k] for k in ['paper_completed','proposal_generated','scientific_acceptance','ml_training_eligible','semantic_validation_qualified'])
    assert json.loads(reader.checked(first['graph']).read_text()) == graph(bundle)
    assert not (store.root / 'proposals.sqlite3').exists()


@pytest.mark.parametrize('change', ['input','response','graph','implementation','model_graph','native_input_graph','binding','interface_validation','model_validation'])
def test_replay_corruption_never_redrafts(queued, change):
    store, path, job, bundle, _ = queued; fake = Fake(graph(bundle))
    result = projector.run(store, job, provider_override=fake)
    if change == 'input': target = path
    elif change in ['graph','model_graph','native_input_graph','binding','interface_validation','model_validation']: target = Path(result[change]['path'])
    elif change == 'implementation': target = next(store.root.glob('projector-attempts/*/*/implementation/materials_ner/source_projector.py'))
    else: target = next(store.root.glob('projector-attempts/*/*/response.json'))
    target.write_text(target.read_text() + '\n')
    with pytest.raises(ValueError): projector.run(store, job, provider_override=fake)
    assert fake.calls == 1


def test_changed_input_blocks_before_provider(queued):
    store, path, job, bundle, _ = queued; fake = Fake(graph(bundle))
    path.write_text(path.read_text() + '\n')
    result = projector.run(store, job, provider_override=fake)
    assert result['outcome'] == 'not_dispatched' and not fake.calls


def test_unknown_completion_holds_remaining_dispatch(queued):
    store, path, job, bundle, _ = queued
    copy = path.parent / 'different-path.json'; copy.write_bytes(path.read_bytes())
    second = projector.enqueue(store, copy)
    fake = Fake(graph(bundle), ProviderFailure('codex_turn_failed', retryable=True))
    result = projector.run(store, job, provider_override=fake)
    assert result['outcome'] == 'completion_unknown'
    assert projector.run(store, job, provider_override=fake) == result
    with pytest.raises(ValueError, match='reader_dispatch_hold'):
        projector.run(store, second, provider_override=fake)
    assert fake.calls == 1 and projector.row(store, second)['attempts'] == 0


def test_pinned_provider_return_recovers_without_second_call(queued, monkeypatch):
    store, _, job, bundle, _ = queued; fake = Fake(graph(bundle)); original = projector.terminal
    def crash(*args, **kwargs): raise SystemExit('simulated interruption after provider return')
    monkeypatch.setattr(projector, 'terminal', crash)
    with pytest.raises(SystemExit): projector.run(store, job, provider_override=fake)
    assert projector.row(store, job)['state'] == 'running'
    monkeypatch.setattr(projector, 'terminal', original)
    result = projector.recover(store, job)
    assert result['state'] == 'succeeded' and result['recovered_without_provider_call']
    assert projector.run(store, job, provider_override=fake) == result and fake.calls == 1


def test_missing_provider_return_is_held_not_resubmitted(queued):
    store, _, job, bundle, _ = queued; fake = Fake(graph(bundle), SystemExit('simulated provider interruption'))
    with pytest.raises(SystemExit): projector.run(store, job, provider_override=fake)
    result = projector.run(store, job, provider_override=fake)
    assert result['outcome'] == 'completion_unknown' and fake.calls == 1


def test_invalid_raw_graph_is_preserved_without_repair(queued):
    store, _, job, bundle, _ = queued; fake = Fake(graph(bundle)); fake.text = '{"schema_version":"materials-ner/13"}'
    result = projector.run(store, job, provider_override=fake)
    assert result['state'] == 'quarantined' and result['error_code'] == 'projector_schema_invalid'
    assert next(store.root.glob('projector-attempts/*/*/response.json')).read_text() == fake.text
    assert projector.run(store, job, provider_override=fake) == result and fake.calls == 1


def test_binding_compilation_retains_model_graph_and_changes_only_evidence(queued):
    from ingestion.materials_ner.projection_binding import scientific_payload
    store, _, job, bundle, _ = queued
    original = graph(bundle)
    # Quote-only evidence is a valid provider output; positions are source-bound
    # mechanically and do not ask the model to count original characters.
    for group in ('samples','states','protocols','results','sample_relations','condition_supports'):
        for entity in original[group]:
            for e in entity['evidence']:
                e.pop('start_char',None); e.pop('end_char',None)
    fake = Fake(original); result = projector.run(store,job,provider_override=fake)
    assert result['state']=='succeeded' and result['evidence_metadata_edits']>0
    model=json.loads(reader.checked(result['model_graph']).read_text())
    compiled=json.loads(reader.checked(result['graph']).read_text())
    assert model==original and model!=compiled
    assert scientific_payload(model)==scientific_payload(compiled)
    binding=json.loads(reader.checked(result['binding']).read_text())
    assert not binding['holds'] and result['graph_authorship']=='gpt-6-luna'
    assert not result['semantic_validation_qualified'] and not result['proposal_generated']


def test_provider_interface_violation_stays_held_even_when_mechanically_resolvable(queued):
    store,_,job,bundle,_=queued; original=graph(bundle)
    for e in original['results'][0]['evidence']:e['field']='/results/r'+e['field']
    result=projector.run(store,job,provider_override=Fake(original))
    assert result['state']=='quarantined' and not result['deterministic_validation_valid']
    assert json.loads(reader.checked(result['validation']).read_text())['valid']
    assert not json.loads(reader.checked(result['interface_validation']).read_text())['valid']


def test_scientific_value_and_unresolved_quote_are_never_repaired(queued):
    store,_,job,bundle,_=queued; original=graph(bundle)
    original['results'][0]['quantity']['value']=777.0
    original['results'][0]['evidence'][0]['quote']='fabricated quote'
    result=projector.run(store,job,provider_override=Fake(original))
    assert result['state']=='quarantined' and result['unresolved_binding_holds']>0
    compiled=json.loads(reader.checked(result['graph']).read_text())
    assert compiled['results'][0]['quantity']['value']==777.0
    assert json.loads(reader.checked(result['model_graph']).read_text())==original


def test_contextual_provider_selector_compiles_to_native_without_scientific_edits(queued):
    store,_,job,bundle,_=queued;original=graph(bundle)
    for e in original['results'][0]['evidence']:
        e.pop('start_char');e.pop('end_char')
        e['context_quote']=e['quote']
    result=projector.run(store,job,provider_override=Fake(original))
    assert result['state']=='succeeded',result
    assert json.loads(reader.checked(result['model_graph']).read_text())==original
    assert 'context_quote' not in json.loads(reader.checked(result['graph']).read_text())['results'][0]['evidence'][0]
    assert result['provider_only_locator_fields']==['context_quote']
    assert result['scientific_payload_unchanged'] and not result['proposal_generated']


def test_required_context_flag_changes_only_schema_not_prompt_or_source(queued):
    _,path,_,_,_=queued;before=projector.prepare(path)
    request=json.loads(path.read_text());request['require_context_quote']=True;path.write_text(canonical(request))
    after=projector.prepare(path)
    assert after['prompt']==before['prompt'] and after['scope']==before['scope']
    assert after['schema']!=before['schema']
    assert projector.configuration(after)['require_context_quote'] is True
    request['require_context_quote']='yes';path.write_text(canonical(request))
    with pytest.raises(ValueError,match='projector_input_shape'):projector.prepare(path)


@pytest.mark.parametrize('provide_context',[False,True])
def test_required_context_is_enforced_and_preserves_native_science(queued,tmp_path,provide_context):
    _,path,_,bundle,_=queued;request=json.loads(path.read_text());request['require_context_quote']=True
    requested=tmp_path/'required-context.json';requested.write_text(canonical(request))
    store=Store(tmp_path/'required-context-queue');job=projector.enqueue(store,requested)
    original=graph(bundle)
    if provide_context:
        for group in ('samples','states','protocols','results','sample_relations','condition_supports'):
            for entity in original[group]:
                for e in entity['evidence']:
                    e.pop('start_char');e.pop('end_char');e['context_quote']=e['quote']
    result=projector.run(store,job,provider_override=Fake(original))
    assert (result['state']=='succeeded')==provide_context
    assert result['scientific_payload_unchanged']


def test_preparation_namespace_stays_empty(queued, tmp_path):
    _, path, _, _, _ = queued; store = Store(tmp_path / 'prepared')
    (store.root / 'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'): projector.enqueue(store, path)
    assert store.summary()['jobs'] == 0


def test_development_comparator_follows_source_not_order_or_ids(queued):
    _, _, _, bundle, m = queued; g = graph(bundle); b = bundle.blocks[0]; start = b.text.index('5 K')
    ref = dict(schema='materials-development-source-tuples/1', work_id=bundle.work_id,
        original=m['source']['original'], independent_gold=False,
        tuples=[dict(assertion_id='reference', original_quantity_anchor=dict(block_id=b.id,start_char=start,end_char=start+3,quote='5 K'),
        expected=dict(formula=None,kind='tc',value=5.0,unit='K',pressure_gpa=None,pressure_role=None,
            source_role='primary',origin='observed',criterion='onset',resistance_fraction_percent=None,derived_from=[]))])
    assert source_tuple_eval.assess(ref,g,bundle)['matched'] == 1
    # Broad shared context must not override an explicit, narrower raw witness.
    g['results'][0]['evidence'].append(dict(field='/quantity/raw',block_id=b.id,quote='5 K'))
    assert source_tuple_eval.assess(ref,g,bundle)['matched'] == 1
    g['results'][0]['id'] = 'different-id'
    assert source_tuple_eval.assess(ref,g,bundle)['matched'] == 1
    changed = deepcopy(g); changed['results'][0]['definition']['criterion'] = 'zero_resistance'
    assert source_tuple_eval.assess(ref,changed,bundle)['matched'] == 0
    changed = deepcopy(g); extra = deepcopy(changed['results'][0]); extra['id']='second'; changed['results'].append(extra)
    assert source_tuple_eval.assess(ref,changed,bundle)['rows'][0]['reason'] == 'missing_or_ambiguous_source_occurrence'
    ref['original'] = dict(ref['original'], sha256='0'*64)
    with pytest.raises(ValueError, match='source_identity'): source_tuple_eval.assess(ref,g,bundle)


@pytest.mark.parametrize('unit,value,approximate,expected', [('GPa',11.6,False,11.6),('kbar',116,False,11.6),('GPa',11.6,True,None)])
def test_reference_pressure_uses_existing_units_without_losing_approximation(unit,value,approximate,expected):
    state = dict(conditions=[dict(kind='pressure',role='measurement',quantity=dict(status='reported',
        raw=f'{value} {unit}',value=value,unit=unit,relation='exact',approximate=approximate))])
    assert source_tuple_eval.pressure(state) == (expected,'measurement')
