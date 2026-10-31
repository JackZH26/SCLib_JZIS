"""Source acquisition cannot route any fresh or resumed batch to a remote DB."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ingestion.materials_ner import campaign, database, window_campaign
from ingestion.materials_ner.cli import main
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_campaign import make_packet
from test_materials_ner_pipeline import FakeProvider, example


def forbid_remote(*args, **kwargs):
    raise AssertionError('A source-read host must never reach a remote database bridge')


@pytest.mark.parametrize('loss', ['receipt', 'database'])
def test_source_host_is_read_only_and_resume_replays_local_rows_without_model_calls(tmp_path, monkeypatch, loss):
    monkeypatch.setattr(database, 'bridge', forbid_remote)
    bundle, raw = example()
    bundle.work_id = raw['work_id'] = 'arxiv:2401.00001'
    plan = tmp_path / 'plan.json'
    plan.write_text(canonical({'schema': 'materials-ner-source-plan/1', 'papers': [
        {'id': bundle.work_id, 'source': 'arxiv', 'old_ner_records': 1},
        {'id': 'aps:synthetic', 'source': 'aps', 'old_ner_records': 100}]}))
    hosts, calls = [], []
    def acquire(root, plan_path, **kwargs):
        hosts.append(kwargs['ssh_host'])
        save_bundle(root, bundle)
    def execute(store, job_id, max_seconds):
        calls.append(job_id)
        return run_one(store, job_id=job_id, provider_override=FakeProvider(raw))
    monkeypatch.setattr(campaign, 'acquire_batch', acquire)
    monkeypatch.setattr(campaign, 'run_one', execute)
    options = dict(batch_size=1, source_ssh_host='source-reader.example', progress=lambda _: None)
    first = campaign.run_campaign(tmp_path, plan, **options)
    assert hosts == ['source-reader.example'] and len(calls) == 1
    assert first['proposal_database']['tables']['results'] == 1
    store = Store(tmp_path)
    packet = import_packet(store, calls[0])
    local_receipt = tmp_path / 'local-imports' / (packet['run_id'] + '.json')
    historical_remote = tmp_path / 'imports' / (packet['run_id'] + '.json')
    historical_remote.parent.mkdir(exist_ok=True)
    historical_remote.write_text('{"historical_remote_evidence":"preserve"}')
    if loss == 'receipt':
        local_receipt.unlink()
    else:
        # A receipt remains while the destination is restored/re-created empty.
        (tmp_path / 'proposals.sqlite3').unlink()
    second = campaign.run_campaign(tmp_path, plan, **options)
    assert len(calls) == 1
    assert second['proposal_database']['tables']['runs'] == 1
    assert second['proposal_database']['tables']['results'] == 1
    assert historical_remote.read_text() == '{"historical_remote_evidence":"preserve"}'
    receipt = json.loads(local_receipt.read_text())
    assert receipt['remote'] is None
    assert receipt['packet_hash'] == packet['packet_hash']
    assert receipt['local_destination'] == str(tmp_path / 'proposals.sqlite3')
    assert receipt['local']['inserted'] is (loss == 'database')
    campaign.run_campaign(tmp_path, plan, **options)
    assert len(calls) == 1
    assert json.loads(local_receipt.read_text())['local']['inserted'] is False


def test_remote_destination_requires_a_named_database_argument(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'bridge', forbid_remote)
    store, packet = make_packet(tmp_path)
    with pytest.raises(TypeError):
        database.ingest_job(store, packet['job_id'], 'ambiguous-host')
    assert not (tmp_path / 'proposals.sqlite3').exists()
    result = database.ingest_job(store, packet['job_id'])
    assert result['remote'] is None
    assert result['local']['inserted']
    assert not database.ingest_job(store, packet['job_id'])['local']['inserted']


@pytest.mark.parametrize('command', [
    ['window-campaign', '--plan', 'plan.json', '--name', 'test', '--ssh-host', 'ambiguous-host'],
    ['database', '--ssh-host', 'ambiguous-host'],
])
def test_ambiguous_remote_cli_options_fail_before_queue_creation(tmp_path, command):
    with pytest.raises(SystemExit) as exc:
        main(['--root', str(tmp_path / 'state'), *command])
    assert exc.value.code == 2
    assert not (tmp_path / 'state').exists()


@pytest.mark.parametrize('flag', ['--source-ssh-host', '--ssh-host'])
def test_source_cli_option_and_compatibility_alias_only_reach_acquisition(tmp_path, monkeypatch, flag):
    calls = []
    def capture(root, plan_path, **kwargs):
        calls.append(kwargs)
        return {'synthetic': True}
    monkeypatch.setattr(campaign, 'run_campaign', capture)
    main(['--root', str(tmp_path / 'state'), 'campaign', '--plan', 'plan.json',
          flag, 'source-reader.example'])
    assert calls[0]['source_ssh_host'] == 'source-reader.example'
    assert 'ssh_host' not in calls[0] and 'database_ssh_host' not in calls[0]


def test_old_campaign_cannot_accept_an_ambiguous_host_keyword(tmp_path):
    with pytest.raises(TypeError):
        campaign.run_campaign(tmp_path, tmp_path / 'plan.json', ssh_host='ambiguous-host')
    with pytest.raises(TypeError):
        window_campaign.run_window_campaign(tmp_path, tmp_path / 'plan.json', name='test', ssh_host='ambiguous-host')
    assert not (tmp_path / 'queue.sqlite3').exists()


def test_legacy_selection_refuses_multiple_representations(tmp_path):
    bundle, _ = example()
    save_bundle(tmp_path, bundle)
    other = deepcopy(bundle)
    other.title += ' new metadata'
    save_bundle(tmp_path, other)
    with pytest.raises(ValueError, match='explicit_source_selection_required'):
        campaign.available_bundles(tmp_path, {bundle.work_id})


def test_window_resume_also_recovers_an_empty_destination_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'bridge', forbid_remote)
    store, packet = make_packet(tmp_path)
    job_id = packet['job_id']
    plan_path = tmp_path / 'plan.json'
    plan = {'schema': 'materials-ner-source-plan/1', 'papers': [{'id': packet['work_id'], 'source': 'arxiv'}]}
    plan_path.write_text(canonical(plan))
    config = window_campaign.configuration(model='gpt-6-luna', max_input_tokens=30000, timeout_seconds=300)
    state = {'config': config, 'plan_sha256': digest(plan), 'max_chars': 4000,
             'papers': {packet['work_id']: {'jobs': [job_id]}}, 'outcomes': []}
    folder = tmp_path / 'campaigns' / 'resume'
    folder.mkdir(parents=True)
    (folder / 'windows-state.json').write_text(canonical(state))
    monkeypatch.setattr(window_campaign, 'run_one', forbid_remote)
    report = window_campaign.run_window_campaign(tmp_path, plan_path, name='resume')
    assert report['attempted_this_run'] == 0
    assert ProposalDatabase(tmp_path).summary()['tables']['runs'] == 1
    report = window_campaign.run_window_campaign(tmp_path, plan_path, name='resume')
    assert report['attempted_this_run'] == 0
    assert ProposalDatabase(tmp_path).summary()['tables']['runs'] == 1
