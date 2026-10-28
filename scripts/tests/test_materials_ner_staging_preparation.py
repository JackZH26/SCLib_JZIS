"""An isolated preparation namespace cannot accidentally run old NER workflows."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from materials_ner_source_manifest import freeze, file_hash
from materials_ner_staging import prepare
from test_materials_ner_source_manifest import preparation
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one


def prepared_input(tmp_path):
    args, *_ = preparation(tmp_path)
    freeze(**args)
    manifest = args['output'] / 'MANIFEST.json'
    options = dict(name='test-full-corpus', manifest=manifest, manifest_sha256=file_hash(manifest))
    return args, options, tmp_path / 'new-staging'


def test_separate_empty_namespace_resumes_without_accepting_historical_success(tmp_path):
    args, options, root = prepared_input(tmp_path)
    first = prepare(root, **options)
    second = prepare(root, **options)
    assert first == second
    assert first['queue']['jobs'] == first['queue']['attempts'] == 0
    assert all(n == 0 for n in first['proposal_database']['tables'].values())
    assert Store(args['root']).summary()['jobs'] == 1
    assert first['source_verification']['papers'] == 4
    assert first['model_calls'] == first['new_campaign_completed'] == 0


def test_legacy_queue_api_and_worker_cannot_dispatch_from_preparation(tmp_path):
    _, options, root = prepared_input(tmp_path)
    prepare(root, **options)
    store = Store(root)
    with pytest.raises(ValueError, match='staging_preparation_only'):
        store.enqueue(work_id='arxiv:2401.00001', bundle_hash='0' * 64,
                      config={'workflow': 'single_pass_v1'})
    with pytest.raises(ValueError, match='staging_preparation_only'):
        store.claim()
    with pytest.raises(ValueError, match='staging_preparation_only'):
        run_one(store)
    assert store.summary()['attempts'] == store.summary()['jobs'] == 0


@pytest.mark.parametrize('destination', ['source_root', 'source_child', 'source_parent', 'manifest_child', 'preexisting'])
def test_namespace_cannot_overlap_source_evidence_or_existing_unowned_state(tmp_path, destination):
    args, options, _ = prepared_input(tmp_path)
    roots = {'source_root': args['root'], 'source_child': args['root'] / 'nested',
             'source_parent': args['root'].parent, 'manifest_child': args['output'] / 'nested',
             'preexisting': tmp_path / 'existing'}
    root = roots[destination]
    if destination == 'preexisting':
        root.mkdir()
    with pytest.raises(ValueError):
        prepare(root, **options)
    assert not (root / 'STAGING_PREPARATION.json').exists()


def test_preparation_identity_drift_is_not_overwritten(tmp_path):
    _, options, root = prepared_input(tmp_path)
    prepare(root, **options)
    before = (root / 'STAGING_PREPARATION.json').read_bytes()
    with pytest.raises(ValueError, match='existing_namespace'):
        prepare(root, **dict(options, name='different-campaign'))
    assert (root / 'STAGING_PREPARATION.json').read_bytes() == before


def test_modified_source_prevents_prepare_before_creating_queue(tmp_path):
    args, options, root = prepared_input(tmp_path)
    source = next((args['root'] / 'sources').iterdir())
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='input_pin_mismatch'):
        prepare(root, **options)
    assert not root.exists()
