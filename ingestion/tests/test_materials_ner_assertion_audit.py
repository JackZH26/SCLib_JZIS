"""Synthetic lifecycle/failure tests; fake decisions are never accuracy evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ingestion.materials_ner import assertion_audit as audit, reviewed_reader as reader
from ingestion.materials_ner import source_projector as projector, projection_binding as binding
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_reviewed_proposals import prepared, graph


class Fake:
    def __init__(self, response, error=None):
        self.text = canonical(response); self.error = error; self.calls = 0

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['model'] == 'gpt-6-luna' and config['reasoning'] == 'medium'
        assert schema['required'] and 'schema_version' not in schema['properties']
        (directory / 'response.json').write_text(self.text)
        if self.error: raise self.error
        return ProviderResult(self.text, {'input_tokens':10,'output_tokens':20}, 'codex', 'gpt-6-luna', 'synthetic', .1)


@pytest.fixture
def queued(prepared, tmp_path):
    _, _, scope, b, manifest = prepared
    mp = tmp_path / 'coverage.json'; reader.put(mp, manifest)
    request = tmp_path / 'projector.json'
    reader.put(request, dict(schema=projector.INPUT_SCHEMA, scope=reader.reference(scope), coverage=reader.reference(mp)))
    p = projector.prepare(request); g = graph(b)
    raw = tmp_path / 'model.json'; reader.put(raw, g)
    compiled = tmp_path / 'compiled.json'; reader.put(compiled, binding.compile_bindings(g,b,p['scope'],manifest))
    inp = tmp_path / 'audit.json'; reader.put(inp, audit.build_input(reader.reference(raw),reader.reference(compiled),reader.reference(request)))
    store = Store(tmp_path / 'audit-queue'); job = audit.enqueue(store,inp)
    prepared = audit.prepare(inp)
    response = {t['id']:dict(status='insufficient_source',reason='Synthetic test abstention.',witnesses=[]) for t in prepared['targets']}
    return store, inp, job, prepared, response


def test_complete_abstention_is_a_recorded_audit_not_admission(queued):
    store,_,job,p,response=queued;fake=Fake(response)
    result=audit.run(store,job,provider_override=fake)
    assert result['state']=='succeeded' and result['complete_decision_inventory']
    assert result['model_status_counts']=={'insufficient_source':len(p['targets'])}
    assert not any(result[k] for k in ['semantic_validation_qualified','scientific_acceptance','paper_completed','proposal_generated','ml_training_eligible','scientific_payload_changed'])
    assert audit.run(Store(store.root),job,provider_override=fake)==result and fake.calls==1
    assert not (store.root/'proposals.sqlite3').exists()


def test_same_frozen_draft_cannot_be_reaudited_by_renaming_request(queued):
    store,path,job,p,response=queued
    renamed=path.with_name('renamed.json');renamed.write_bytes(path.read_bytes())
    assert audit.enqueue(store,renamed)==job
    config=audit.configuration(audit.prepare(renamed));config['reasoning']='high'
    assert store.enqueue(work_id=p['work_id'],bundle_hash=p['bundle_sha256'],config=config,max_attempts=1)==job
    assert store.summary()['jobs']==1


def test_generic_workers_and_retry_policy_cannot_dispatch_audit(queued):
    store,_,job,p,response=queued;fake=Fake(response)
    assert store.claim(job_id=job) is None and run_one(store,job_id=job,provider_override=fake) is None
    with pytest.raises(ValueError,match='one_automatic_attempt'):
        store.enqueue(work_id=p['work_id'],bundle_hash=p['bundle_sha256'],config=audit.configuration(p),max_attempts=2)
    config=audit.configuration(p);config.pop('single_pass_identity')
    with pytest.raises(ValueError,match='frozen_identity'):
        store.enqueue(work_id=p['work_id'],bundle_hash=p['bundle_sha256'],config=config,max_attempts=1)
    assert not fake.calls


@pytest.mark.parametrize('change',['missing','extra','empty_support','empty_contradiction','replacement','duplicate_key'])
def test_incomplete_or_repairing_response_is_quarantined_without_retry(queued,change):
    store,_,job,p,response=queued;key=next(iter(response))
    if change=='missing':response.pop(key)
    if change=='extra':response['A9999']=deepcopy(response[key])
    if change in {'empty_support','empty_contradiction'}:response[key]['status']='supported' if change=='empty_support' else 'contradicted'
    if change=='replacement':response[key]['replacement_value']=4.4
    fake=Fake(response)
    if change=='duplicate_key':fake.text='{"'+key+'":{},"'+key+'":{}}'
    result=audit.run(store,job,provider_override=fake)
    assert result['state']=='quarantined' and not result['scientific_acceptance']
    assert audit.run(store,job,provider_override=fake)==result and fake.calls==1
    assert next(store.root.glob('audit-attempts/*/*/response.json')).read_text()==fake.text


@pytest.mark.parametrize('field_change',['value','omission','stale_semantics','graph','source'])
def test_candidate_or_source_tampering_is_rejected_before_provider(queued,field_change):
    store,path,job,p,response=queued;inp=json.loads(path.read_text())
    if field_change=='value':inp['targets'][0]['candidate_value']='invented'
    if field_change=='omission':inp['targets'].pop()
    if field_change=='stale_semantics':inp['relationship_semantics']['context_uses']='The procedure determines the named condition.'
    if field_change=='graph':
        cp=Path(inp['compiled_graph']['path']);g=json.loads(cp.read_text());g['graph']['results'][0]['quantity']['value']=999
        cp.write_text(canonical(g));inp['compiled_graph']=reader.reference(cp);inp['graph_sha256']=digest(g['graph'])
    if field_change=='source':
        bundle=json.loads(reader.checked(p['scope']['preflight']).read_text())['bundle']
        f=Path(bundle['path']);f.write_text(f.read_text()+'\n')
    path.write_text(canonical(inp))
    with pytest.raises(ValueError):audit.prepare(path)
    fake=Fake(response);result=audit.run(store,job,provider_override=fake)
    assert result['outcome']=='not_dispatched' and not fake.calls


@pytest.mark.parametrize('change',['input','response','model_audit','audit_validation','implementation','output-schema'])
def test_completed_artifact_corruption_never_calls_model_again(queued,change):
    store,path,job,_,response=queued;fake=Fake(response);result=audit.run(store,job,provider_override=fake)
    if change=='input':target=path
    elif change in {'model_audit','audit_validation'}:target=Path(result[change]['path'])
    elif change=='implementation':target=next(store.root.glob('audit-attempts/*/*/implementation/materials_ner/assertion_audit.py'))
    else:target=next(store.root.glob('audit-attempts/*/*/'+change+'.json'))
    target.write_text(target.read_text()+'\n')
    with pytest.raises(ValueError):audit.run(store,job,provider_override=fake)
    assert fake.calls==1


def test_crash_after_return_recovers_without_model_call(queued,monkeypatch):
    store,_,job,_,response=queued;fake=Fake(response);original=audit.terminal
    def crash(*args,**kwargs):raise SystemExit('synthetic post-return crash')
    monkeypatch.setattr(audit,'terminal',crash)
    with pytest.raises(SystemExit):audit.run(store,job,provider_override=fake)
    monkeypatch.setattr(audit,'terminal',original)
    result=audit.recover(store,job)
    assert result['state']=='succeeded' and result['recovered_without_provider_call']
    assert audit.run(store,job,provider_override=fake)==result and fake.calls==1


@pytest.mark.parametrize('error',[ProviderFailure('codex_turn_failed',retryable=True),SystemExit('synthetic crash')])
def test_uncertain_completion_holds_namespace_without_second_call(queued,error):
    store,_,job,_,response=queued;fake=Fake(response,error)
    if isinstance(error,SystemExit):
        with pytest.raises(SystemExit):audit.run(store,job,provider_override=fake)
    result=audit.run(store,job,provider_override=fake)
    assert result['outcome']=='completion_unknown'
    assert audit.run(store,job,provider_override=fake)==result and fake.calls==1
    assert (store.root/'READER_DISPATCH_HOLD.json').exists()


def witness(p,quote):
    return dict(block_id=p['bundle'].blocks[0].id,quote=quote,context_quote=p['bundle'].blocks[0].text)


def test_fabricated_support_quote_is_quarantined(queued):
    store,_,job,p,response=queued;key=next(iter(response))
    response[key]=dict(status='supported',reason='Synthetic false support.',witnesses=[witness(p,'the fabricated result is 500 K')])
    result=audit.run(store,job,provider_override=Fake(response))
    assert result['state']=='quarantined' and result['unresolved_witnesses']==1


def test_locatable_support_is_still_an_unqualified_model_opinion(queued):
    store,_,job,p,response=queued
    target=next(t for t in p['targets'] if t['entity_group']=='results' and t['field']=='/quantity')
    response[target['id']]=dict(status='supported',reason='Synthetic unqualified opinion.',witnesses=[witness(p,'5 K')])
    result=audit.run(store,job,provider_override=Fake(response))
    assert result['state']=='succeeded' and result['model_status_counts']['supported']==1
    report=json.loads(reader.checked(result['audit_validation']).read_text())
    checked=next(r for r in report['rows'] if r['assertion_id']==target['id'])
    assert checked['resolved_witnesses'][0]['quote']=='5 K' and not checked['semantic_verified']
    assert not result['scientific_acceptance'] and not result['proposal_generated']


def test_quantity_context_cannot_be_used_as_target_and_clipped_tokens_fail(queued):
    _,_,_,p,_=queued;target=next(t for t in p['targets'] if t['entity_group']=='results' and t['field']=='/quantity')
    assert audit.resolve_witness(witness(p,'5 K'),target,p)['quote']=='5 K'
    changed={**p,'scope':deepcopy(p['scope'])}
    for span in changed['scope']['passages']:span['role']='context'
    with pytest.raises(ValueError,match='unresolved_in_scope'):audit.resolve_witness(witness(p,'5 K'),target,changed)
    with pytest.raises(ValueError,match='unresolved_in_scope'):audit.resolve_witness(witness(p,'ample'),target,p)


def test_prompt_excludes_previous_witnesses_issues_and_reference_answers(queued):
    _,_,_,p,_=queued
    assert 'current_witnesses' not in p['prompt'] and 'current_issues' not in p['prompt']
    assert 'UNTRUSTED CANDIDATE CONTEXT' in p['prompt']
    assert audit.RELATIONSHIP_SEMANTICS['context_uses'] in p['prompt']
    assert 'This link alone does not assert' in p['prompt']


def test_prepared_full_corpus_namespace_remains_unclaimable(queued,tmp_path):
    _,path,_,_,_=queued;store=Store(tmp_path/'full-corpus')
    (store.root/'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError,match='staging_preparation_only'):audit.enqueue(store,path)
    assert store.summary()['jobs']==0


def test_concurrent_enqueue_is_one_queue_local_audit(queued):
    from concurrent.futures import ThreadPoolExecutor
    store,_,job,p,_=queued
    def enqueue_copy(n):
        config=audit.configuration(p);config['request']={**config['request'],'path':f'/synthetic/renamed-{n}.json'}
        return store.enqueue(work_id=p['work_id'],bundle_hash=p['bundle_sha256'],config=config,max_attempts=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(enqueue_copy,range(8)))=={job}
    assert store.summary()['jobs']==1


def test_expired_audit_lease_never_enters_generic_retry_queue(queued):
    store,_,job,_,response=queued
    claimed=store.claim(job_id=job,workflow=audit.WORKFLOW)
    directory=store.root/audit.ATTEMPTS_DIRECTORY/job/claimed['lease_token'];directory.mkdir(parents=True)
    (directory/'DISPATCH_INTENT.json').write_text('{}')
    with store.connect() as db:db.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(job,))
    assert store.claim() is None
    assert audit.row(store,job)['state']=='failed'
    fake=Fake(response);result=audit.run(store,job,provider_override=fake)
    assert result['outcome']=='completion_unknown' and not fake.calls
    assert store.summary()['attempts']==1
