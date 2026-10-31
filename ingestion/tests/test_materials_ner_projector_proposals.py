"""Authentic synthetic receipts, hostile replay and actual SQLite crash recovery."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ingestion.materials_ner import projector_proposals as adapter, reviewed_reader as reader
from ingestion.materials_ner import source_projector as projector
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.proposals import ProposalDatabase, TABLES, verify_packet
from ingestion.materials_ner.sources import sha
from test_materials_ner_source_projector import queued, Fake
from test_materials_ner_reviewed_proposals import prepared, graph, at, AUTHOR, NOW


@pytest.fixture
def terminal(queued):
    store, _, job, bundle, _ = queued
    fake = Fake(graph(bundle)); result = projector.run(store, job, provider_override=fake)
    assert fake.calls == 1 and result['state'] == 'succeeded'
    return store, job, bundle, fake


def rehash(packet):
    packet['run_id'] = digest(packet['receipt'])
    packet['packet_hash'] = digest({k:v for k,v in packet.items() if k != 'packet_hash'})
    return packet


def counts(db):
    with db.connect() as connection:
        return {t:connection.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in TABLES}


def findings(path, store, job, bundle, *, entity=True, omission=True):
    a = projector.row(store, job); anchor = at(bundle.blocks[0], '5 K')
    items = []
    if entity:
        items.append(dict(id='state-review', kind='entity', path='/states/0', code='condition_role_requires_review',
                          note='Synthetic source-backed review obligation, not a correction.', anchors=[anchor]))
    if omission:
        items.append(dict(id='source-review', kind='source_completeness', path='/paper', code='source_census_incomplete',
                          note='Synthetic source census obligation, not an extra extracted result.', anchors=[anchor]))
    value = dict(schema=adapter.FINDINGS, work_id=bundle.work_id, bundle_sha256=digest(bundle.model_dump()),
        attempt_sha256=a['result_hash'], author=AUTHOR, created_at=NOW, independent_review=False, findings=items)
    path.write_text(canonical(value)); return path


def test_authentic_pending_packet_idempotent_and_pure_portable(terminal, tmp_path, monkeypatch):
    store, job, bundle, fake = terminal
    p = adapter.build(store.root, job)
    assert adapter.build(store.root, job) == p
    assert p['receipt']['config']['model'] == 'gpt-6-luna'
    assert p['receipt']['graph_authorship'] == 'gpt-6-luna'
    assert p['rows']['results'][0]['review_status'] == 'pending_review'
    assert not p['receipt']['paper_completed'] and not p['scientific_acceptance']
    db = ProposalDatabase(tmp_path/'db')
    assert db.ingest(p)['inserted'] and not db.ingest(p)['inserted']
    with db.connect() as conn:
        saved = json.loads(conn.execute('SELECT payload FROM runs').fetchone()[0])
        assert conn.execute('SELECT model FROM runs').fetchone()[0] == 'gpt-6-luna'
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    def forbidden(*args, **kwargs): raise AssertionError('Portable replay touched local assets or provider.')
    monkeypatch.setattr(reader, 'checked', forbidden)
    monkeypatch.setattr(Fake, 'extract', forbidden)
    verify_packet(saved)
    assert fake.calls == 1 and counts(db)['results'] == 1


def test_invalid_graph_preserved_as_run_without_fabricated_entities(queued, tmp_path):
    store, _, job, bundle, _ = queued
    g = graph(bundle); g['results'][0]['protocol_id'] = 'nonexistent'
    f = Fake(g); result = projector.run(store, job, provider_override=f)
    assert result['error_code'] == 'projector_schema_invalid'
    p = adapter.build(store.root, job); db = ProposalDatabase(tmp_path/'db')
    assert 'extraction' not in p['receipt'] and p['raw_output'] == f.text
    assert not any(p['rows'].values()) and not p['evidence']
    assert db.ingest(p)['inserted'] and not db.ingest(p)['inserted']
    assert counts(db) == {k:int(k in {'runs','bundles'}) for k in TABLES}
    assert json.loads(p['receipt']['projector_provenance']['artifacts']['diagnostic'])['details']


def test_wire_issues_are_not_lost_when_native_validation_passes(queued):
    store, _, job, bundle, _ = queued; g = graph(bundle)
    for evidence in g['results'][0]['evidence']:
        evidence['field'] = '/results/r' + evidence['field']
    result = projector.run(store, job, provider_override=Fake(g))
    assert json.loads(reader.checked(result['validation']).read_text())['valid']
    p = adapter.build(store.root, job)
    assert p['rows']['results'][0]['review_status'] == 'quarantined'
    assert any(code.startswith('provider_interface_') for code in p['rows']['results'][0]['issues'])


def test_source_findings_propagate_without_changing_science(queued, tmp_path):
    store, _, job, bundle, _ = queued; g = graph(bundle)
    second = deepcopy(g['results'][0]); second['id'] = 'derived'
    second['dependencies'] = [dict(result_id='r', relation='derived_from')]
    g['results'].append(second)
    projector.run(store, job, provider_override=Fake(g))
    f = findings(tmp_path/'findings.json', store, job, bundle)
    p = adapter.build(store.root, job, review_findings=f)
    assert p['receipt']['extraction'] == g
    assert all(r['review_status'] == 'quarantined' for r in p['rows']['results'])
    assert 'state_has_validation_issues' in p['rows']['results'][0]['issues']
    assert 'derived_input_has_validation_issues' in p['rows']['results'][1]['issues']
    assert len(p['receipt']['paper_review']['source_completeness_findings']) == 1
    assert not p['receipt']['paper_review']['scope_review_complete']
    assert len(p['rows']['results']) == 2


def test_paper_omission_separate_from_row_technical_status(terminal, tmp_path):
    store, job, bundle, _ = terminal
    f = findings(tmp_path/'findings.json', store, job, bundle, entity=False)
    p = adapter.build(store.root, job, review_findings=f)
    assert p['rows']['results'][0]['review_status'] == 'pending_review'
    assert not p['receipt']['paper_completed'] and len(p['rows']['results']) == 1


@pytest.mark.parametrize('change', ['anchor','owner','attempt','independent','author','path','duplicate'])
def test_untrusted_findings_fail_closed(terminal, tmp_path, change):
    store, job, bundle, _ = terminal
    f = findings(tmp_path/'findings.json', store, job, bundle)
    value = json.loads(f.read_text())
    if change == 'anchor': value['findings'][0]['anchors'][0]['quote'] = '7 K'
    if change == 'owner': value['findings'][0]['path'] = '/states/99'
    if change == 'attempt': value['attempt_sha256'] = '0'*64
    if change == 'independent': value['independent_review'] = True
    if change == 'author': value['author']['kind'] = 'human'
    if change == 'path': value['findings'][1]['path'] = '/results/0'
    if change == 'duplicate': value['findings'].append(value['findings'][0])
    f.write_text(canonical(value))
    with pytest.raises(ValueError): adapter.build(store.root, job, review_findings=f)


@pytest.mark.parametrize('change', ['value','validation','row','evidence','provider','scope','coverage','preflight',
    'prompt','schema','request','config','artifact','terminal','raw','model','job','approval','paper','workflow'])
def test_rehashed_packet_tampering_is_rejected(terminal, change):
    store, job, _, _ = terminal; p = adapter.build(store.root, job)
    r = p['receipt']; provenance = r['projector_provenance']
    if change == 'value': r['extraction']['results'][0]['quantity']['value'] = 7.0
    elif change == 'validation': r['validation']['resolved_evidence'] = []
    elif change == 'row': p['rows']['results'][0]['review_status'] = 'quarantined'
    elif change == 'evidence': p['evidence'][0]['start_char'] += 1
    elif change in ['provider','scope','coverage','preflight','terminal']:
        provenance[change + '_json'] += '\n'
    elif change in ['prompt','schema','request']:
        provenance['captured'][dict(prompt='input.txt', schema='output-schema.json', request='request.json')[change]] += '\n'
    elif change == 'config': provenance['config']['reasoning'] = 'high'
    elif change == 'artifact': provenance['artifacts']['binding'] += '\n'
    elif change == 'raw': p['raw_output'] += '\n'; r['raw_output_sha256'] = sha(p['raw_output'].encode())
    elif change == 'model': r['config']['model'] = 'assistant'
    elif change == 'job': p['job_id'] = '0'*64
    elif change == 'approval': r['scientific_acceptance'] = True
    elif change == 'paper': r['paper_completed'] = True
    elif change == 'workflow': r['config']['workflow'] = 'reviewed_reader_projection_v1'
    with pytest.raises((ValueError, KeyError)): verify_packet(rehash(p))


@pytest.mark.parametrize('layout', ['direct','nested','symlink','marker_after_open'])
def test_preparation_namespace_rejects_direct_store_ingest(terminal, tmp_path, layout):
    store, job, _, _ = terminal; packet = adapter.build(store.root, job)
    root = tmp_path/'preparation'; root.mkdir(); marker = root/'STAGING_PREPARATION.json'
    target = root/'nested' if layout == 'nested' else root
    if layout == 'symlink':
        alias = tmp_path/'alias'; alias.symlink_to(root, target_is_directory=True); target = alias
    if layout != 'marker_after_open': marker.write_text('{}')
    db = ProposalDatabase(target)
    marker.write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'): db.ingest(packet)
    assert not any(counts(db).values())


@pytest.mark.parametrize('stage', ['during_transaction','after_commit'])
def test_process_death_and_restart_preserve_atomic_idempotent_import(terminal, tmp_path, stage):
    store, job, _, _ = terminal; p = adapter.build(store.root, job)
    packet_path = tmp_path/'packet.json'; packet_path.write_text(canonical(p))
    db = ProposalDatabase(tmp_path/'target')
    code = '''
import json,os,sys
from contextlib import contextmanager
from pathlib import Path
from ingestion.materials_ner.proposals import ProposalDatabase
p=json.loads(Path(sys.argv[1]).read_text());db=ProposalDatabase(Path(sys.argv[2]))
original=db.connect
@contextmanager
def crashing():
 with original() as c:
  def trace(sql):
   if sql.startswith('INSERT INTO results'): os._exit(87)
  c.set_trace_callback(trace)
  yield c
if sys.argv[3]=='during_transaction': db.connect=crashing
db.ingest(p)
os._exit(88)
'''
    completed = subprocess.run([sys.executable,'-c',code,str(packet_path),str(db.path.parent),stage],
                               capture_output=True,text=True,timeout=60)
    assert completed.returncode == (87 if stage == 'during_transaction' else 88), completed.stderr
    before = counts(db)
    assert before['results'] == (0 if stage == 'during_transaction' else 1)
    if stage == 'during_transaction': assert not any(before.values())
    assert db.ingest(p)['inserted'] is (stage == 'during_transaction')
    assert not db.ingest(p)['inserted'] and counts(db)['results'] == 1
    with db.connect() as c:
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not c.execute('PRAGMA foreign_key_check').fetchall()


def test_missing_or_unfinished_queue_never_starts_work(queued, tmp_path):
    store, _, job, _, _ = queued
    with pytest.raises(ValueError, match='terminal_attempt_required'): adapter.build(store.root, job)
    assert store.summary()['attempts'] == 0
    missing = tmp_path/'absent'
    with pytest.raises(Exception): adapter.build(missing, job)
    assert not missing.exists()


def test_capture_preserves_original_crlf_bytes(tmp_path):
    p = tmp_path/'original'; raw = b'First line\r\nSecond line\r\n'
    p.write_bytes(raw)
    assert adapter._text(p).encode() == raw


def test_adapter_refuses_nested_preparation_before_creating_database(terminal, tmp_path):
    store, job, _, _ = terminal; packet = adapter.build(store.root, job)
    root = tmp_path/'preparation'; root.mkdir(); (root/'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'):
        adapter.ingest_local(packet, root/'nested')
    assert not (root/'nested').exists()
