"""Failure/restart tests for the local reader queue; no model or scientific claims."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ingestion.materials_ner import reviewed_reader as reader
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.sources import parse_local, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one


def scope_fixture(folder, *, text='The sample showed a resistive onset at 5 K. The criterion is onset.\n'):
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / 'original.txt'
    original.write_text(text)
    bundle = parse_local(original, work_id='arxiv:2401.00001', title='Synthetic test source',
                         source_uri='https://arxiv.org/src/2401.00001v1', processing_permission='allowed')
    bh, bp = save_bundle(folder, bundle)
    official = folder / 'official.src'; official.write_bytes(original.read_bytes())
    request = folder / 'request.json'
    request.write_text(canonical(dict(status=200, requested_url='https://arxiv.org/src/2401.00001v1',
                                     final_url='https://arxiv.org/src/2401.00001v1', artifact=reader.reference(official))))
    metadata = folder / 'metadata.html'
    metadata.write_text('<meta name="citation_arxiv_id" content="2401.00001">[v1]')
    meta_receipt = folder / 'metadata.receipt.json'
    meta_receipt.write_text(canonical(dict(status=200, requested_url='https://arxiv.org/abs/2401.00001',
                                         artifact=reader.reference(metadata))))
    audit = folder / 'structure.json'; audit.write_text('{}')
    preflight = folder / 'preflight.json'
    preflight.write_text(canonical(dict(schema='materials-source-preflight/1', work_id=bundle.work_id,
        permits_bounded_passage_reading=True, official_identity_verified=True, scientific_acceptance=False,
        latest_version_observed='v1', bundle=reader.reference(bp), bundle_sha256=bh,
        original=reader.reference(original), structure=reader.reference(audit),
        official_metadata_receipt=reader.reference(meta_receipt), hold_codes=['visual_and_supplement_coverage_unreviewed'],
        exact_version_binding=dict(publication_version='v1', source_sha256=reader.reference(original)['sha256'],
                                   official_bytes=reader.reference(official), request_receipt=reader.reference(request)))))
    scope = folder / 'scope.json'
    scope.write_text(canonical(dict(schema='materials-reviewed-reader-scope/1', preflight=reader.reference(preflight),
        passages=[dict(block_id=bundle.blocks[0].id, start_char=0, end_char=len(bundle.blocks[0].text), role='target')], image_capture=None)))
    return scope


class Fake:
    def __init__(self, text='{"reading":"Synthetic test reading; no scientific acceptance."}', failure=None, hook=None):
        self.text, self.failure, self.hook, self.calls = text, failure, hook, 0

    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        assert config['model'] == 'gpt-6-luna' and config['reasoning'] == 'medium'
        assert schema == reader.protocol()[1]
        (directory / 'events.jsonl').write_text('{"type":"turn.completed","usage":{"input_tokens":10}}\n')
        (directory / 'response.json').write_text(self.text)
        if self.hook:
            self.hook()
        if self.failure:
            raise self.failure
        return ProviderResult(self.text, {'input_tokens': 10}, 'codex', 'gpt-6-luna', 'synthetic', 0.1)


@pytest.fixture
def queued(tmp_path):
    scope = scope_fixture(tmp_path / 'inputs')
    store = Store(tmp_path / 'queue')
    return store, scope, reader.enqueue(store, scope)


def test_fixed_protocol_and_exact_source_rendering(queued):
    store, scope, identifier = queued
    p = reader.prepare_scope(scope)
    assert p['prompt'].startswith(reader.protocol()[0])
    block = p['prompt_source_spans'][0]
    assert p['prompt'][block['prompt_start_char']:block['prompt_end_char']] == 'The sample showed a resistive onset at 5 K. The criterion is onset.\n'
    assert 'Synthetic test source' not in p['prompt']
    assert reader.enqueue(store, scope) == identifier and store.summary()['jobs'] == 1


def test_legacy_worker_cannot_claim_or_dispatch_reader(queued):
    store, _, identifier = queued
    fake = Fake()
    assert store.claim(job_id=identifier) is None
    assert run_one(store, job_id=identifier, provider_override=fake) is None
    assert fake.calls == 0 and store.summary()['attempts'] == 0


def test_single_attempt_and_preparation_gates(queued, tmp_path):
    store, scope, identifier = queued
    job = reader.row(store, identifier)
    with pytest.raises(ValueError, match='one_automatic_attempt'):
        store.enqueue(work_id=job['work_id'], bundle_hash=job['bundle_hash'], config=job['config'], max_attempts=2)
    target = Store(tmp_path / 'prepared')
    (target.root / 'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'):
        reader.enqueue(target, scope)
    assert target.summary()['jobs'] == 0


@pytest.mark.parametrize('change', ['unknown_version', 'old_version', 'foreign_bytes', 'foreign_url', 'withdrawn'])
def test_source_holds_fail_before_enqueue(tmp_path, change):
    scope = scope_fixture(tmp_path / 'inputs')
    s = json.loads(scope.read_bytes()); path = Path(s['preflight']['path']); p = json.loads(path.read_bytes())
    if change == 'unknown_version':
        p['permits_bounded_passage_reading'] = False
    elif change == 'old_version':
        p['latest_version_observed'] = 'v2'
    elif change == 'foreign_bytes':
        p['exact_version_binding']['source_sha256'] = '0' * 64
    elif change == 'withdrawn':
        p['hold_codes'].append('withdrawn_source')
    else:
        rp = Path(p['exact_version_binding']['request_receipt']['path']); r = json.loads(rp.read_bytes())
        r['requested_url'] = 'https://other.example/2401.00001v1'; rp.write_text(canonical(r))
        p['exact_version_binding']['request_receipt'] = reader.reference(rp)
    path.write_text(canonical(p)); s['preflight'] = reader.reference(path); scope.write_text(canonical(s))
    store = Store(tmp_path / 'queue')
    with pytest.raises(ValueError):
        reader.enqueue(store, scope)
    assert store.summary()['jobs'] == 0


@pytest.mark.parametrize('change', ['bounds', 'role', 'context_only', 'duplicate', 'hint'])
def test_scope_rejects_invalid_slices_and_extra_hints(tmp_path, change):
    scope = scope_fixture(tmp_path / 'inputs'); s = json.loads(scope.read_bytes())
    if change == 'bounds':
        s['passages'][0]['end_char'] = 999999
    elif change == 'role':
        s['passages'][0]['role'] = 'expected_answer'
    elif change == 'context_only':
        s['passages'][0]['role'] = 'context'
    elif change == 'duplicate':
        s['passages'].append(s['passages'][0])
    else:
        s['expected_tc'] = 5
    scope.write_text(canonical(s))
    with pytest.raises(ValueError):
        reader.prepare_scope(scope)


def test_success_replays_without_call_and_is_not_a_paper_or_proposal(queued):
    store, _, identifier = queued; fake = Fake()
    first = reader.run(store, identifier, provider_override=fake)
    second = reader.run(Store(store.root), identifier, provider_override=fake)
    assert first == second and fake.calls == 1
    assert first['outcome'] == 'reading_completed_pending_review'
    assert not first['paper_completed'] and not first['proposal_generated']
    assert reader.status(store)['paper_completions'] == 0
    assert not (store.root / 'proposals.sqlite3').exists()


@pytest.mark.parametrize('artifact', ['scope', 'response', 'captured_implementation'])
def test_completed_replay_detects_later_corruption_without_redrafting(queued, artifact):
    store, scope, identifier = queued; fake = Fake()
    assert reader.run(store, identifier, provider_override=fake)['state'] == 'succeeded'
    if artifact == 'scope':
        scope.write_text(scope.read_text() + '\n')
    elif artifact == 'response':
        next(store.root.glob('reader-attempts/*/*/response.json')).write_text('changed')
    else:
        next(store.root.glob('reader-attempts/*/*/implementation/reviewed_reader.py')).write_text('changed')
    with pytest.raises(ValueError, match='pin_changed'):
        reader.run(Store(store.root), identifier, provider_override=fake)
    assert fake.calls == 1 and store.summary()['attempts'] == 1


def test_input_drift_blocks_before_provider_dispatch(queued):
    store, scope, identifier = queued; fake = Fake()
    scope.write_text(scope.read_text() + '\n')
    result = reader.run(store, identifier, provider_override=fake)
    assert fake.calls == 0 and result['state'] == 'blocked'
    assert result['outcome'] == 'not_dispatched'
    assert not result['provider_dispatch_intent_recorded']


def test_timeout_never_retries_even_if_provider_marks_it_retryable(queued):
    store, _, identifier = queued
    fake = Fake(failure=ProviderFailure('codex_timeout_or_interruption', retryable=True, usage={'input_tokens': 11}))
    a = reader.run(store, identifier, provider_override=fake)
    assert a['outcome'] == 'completion_unknown' and a['state'] == 'blocked'
    assert reader.run(Store(store.root), identifier, provider_override=fake) == a
    assert fake.calls == 1 and store.summary()['attempts'] == 1
    assert a['usage']['input_tokens'] == 11


@pytest.mark.parametrize('code', ['codex_turn_failed', 'codex_timeout_or_interruption'])
def test_uncertain_dispatch_stops_remaining_queue_even_for_generic_provider_error(queued, tmp_path, code):
    store, _, identifier = queued
    next_scope = scope_fixture(tmp_path / 'other-inputs')
    second = reader.enqueue(store, next_scope)
    first_provider = Fake(failure=ProviderFailure(code, retryable=True))
    result = reader.run(store, identifier, provider_override=first_provider)
    assert (store.root / 'READER_DISPATCH_HOLD.json').is_file()
    other = Fake()
    with pytest.raises(ValueError, match='reader_dispatch_hold'):
        reader.run(store, second, provider_override=other)
    assert reader.row(store, second)['attempts'] == 0 and other.calls == 0
    assert reader.run(store, identifier, provider_override=first_provider) == result
    assert first_provider.calls == 1


@pytest.mark.parametrize('text', ['{}', '{"reading":null}', '{"reading":""}', '{"reading":[],"extra":1}', 'not json', '{"reading":"a","reading":"b"}'])
def test_invalid_readings_are_retained_without_repair(queued, text):
    store, _, identifier = queued; fake = Fake(text)
    result = reader.run(store, identifier, provider_override=fake)
    assert result['state'] == 'quarantined' and fake.calls == 1
    marker = next(store.root.glob('reader-attempts/*/*/provider-result.json'))
    assert json.loads(marker.read_bytes())['result']['text'] == text


def test_lock_prevents_concurrent_provider_calls(queued):
    store, _, identifier = queued; other = Fake()
    def race():
        with pytest.raises(BlockingIOError):
            reader.run(Store(store.root), identifier, provider_override=other)
    first = Fake(hook=race)
    assert reader.run(store, identifier, provider_override=first)['state'] == 'succeeded'
    assert first.calls == 1 and other.calls == 0


@pytest.mark.parametrize('phase', ['before_return', 'after_return', 'after_return_expired', 'after_return_tampered'])
def test_real_process_exit_and_fresh_process_recovery(queued, phase, tmp_path):
    store, _, identifier = queued
    crash = tmp_path / 'crash.py'
    crash.write_text('''import os,sys\nfrom pathlib import Path\nfrom ingestion.materials_ner import reviewed_reader as r\nfrom ingestion.materials_ner.store import Store\nfrom test_materials_ner_reviewed_reader import Fake\ns=Store(Path(sys.argv[1])); phase=sys.argv[3]\nif phase.startswith('after_return'):\n s.finish=lambda *a,**k:os._exit(73)\n p=Fake()\nelse:\n p=Fake(hook=lambda:os._exit(73))\nr.run(s,sys.argv[2],provider_override=p)\n''')
    result = subprocess.run([sys.executable, str(crash), str(store.root), identifier, phase], capture_output=True, timeout=30)
    assert result.returncode == 73, result.stderr.decode()
    if phase == 'after_return_expired':
        with store.connect() as db:
            db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (identifier,))
        assert store.claim(job_id=identifier) is None
        assert reader.row(store, identifier)['state'] == 'failed'
    if phase == 'after_return_tampered':
        next(store.root.glob('reader-attempts/*/*/response.json')).write_text('changed')
    restore = tmp_path / 'restore.py'
    restore.write_text('''import json,sys\nfrom pathlib import Path\nfrom ingestion.materials_ner import reviewed_reader as r\nfrom ingestion.materials_ner.store import Store\nclass Forbidden:\n def extract(self,*a,**k):raise AssertionError('recovery dispatched')\nprint(json.dumps(r.run(Store(Path(sys.argv[1])),sys.argv[2],provider_override=Forbidden())))\n''')
    recovered = subprocess.run([sys.executable, str(restore), str(store.root), identifier], capture_output=True, text=True, timeout=30)
    assert recovered.returncode == 0, recovered.stderr
    value = json.loads(recovered.stdout)
    expected = 'blocked' if phase == 'before_return' else 'quarantined' if phase.endswith('tampered') else 'succeeded'
    assert value['state'] == expected and value['recovered_without_provider_call']
    assert store.summary()['attempts'] == 1
    assert reader.run(store, identifier, provider_override=Fake()) == value
