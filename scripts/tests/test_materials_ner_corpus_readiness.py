"""Corpus accounting must preserve missing sources and never recycle old success."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from materials_ner_corpus_readiness import capture, source_action
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.sources import parse_local, save_bundle, sha
from ingestion.materials_ner.store import Store


def fixture(tmp_path):
    root = tmp_path / 'runtime'
    (root / 'sources').mkdir(parents=True)
    raw = b'The sample has a superconducting transition at 5 K.'
    path = root / 'sources' / sha(raw)
    path.write_bytes(raw)
    bundle = parse_local(path, work_id='arxiv:2401.00001', title='Synthetic source',
                         source_uri='https://arxiv.org/src/2401.00001v1',
                         processing_permission='allowed', publication_version='v1')
    save_bundle(root, bundle)
    papers = [
        {'id': 'arxiv:2401.00001', 'source': 'arxiv', 'acquisition_status': 'available_in_gcs'},
        {'id': 'arxiv:2401.00002', 'source': 'arxiv', 'acquisition_status': 'available_in_gcs'},
        {'id': 'arxiv:2401.00003', 'source': 'arxiv', 'acquisition_status': 'missing_archive'},
        {'id': 'aps:10.example/one', 'source': 'aps', 'acquisition_status': 'aps_authorization_pending',
         'alternate_work_ids': ['arxiv:2401.00001']},
    ]
    plan = {'schema': 'materials-ner-source-plan/1', 'papers': papers, 'summary': {'papers': 4}}
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text(canonical(plan))
    store = Store(root)
    store.enqueue(work_id=bundle.work_id, bundle_hash=digest(bundle.model_dump()), config={'model': 'synthetic'})
    with store.connect() as db:
        db.execute("UPDATE jobs SET state='succeeded',attempts=1")
    return root, path, plan_path, digest(plan)


def test_full_denominator_and_old_success_do_not_certify_new_campaign(tmp_path):
    root, source, plan, pin = fixture(tmp_path)
    out = tmp_path / 'snapshot'
    summary = capture(root, plan, plan_sha256=pin, output=out)
    assert summary['papers'] == sum(summary['next_source_actions'].values()) == 4
    assert summary['legacy_job_states'] == {'succeeded': 1}
    assert summary['new_campaign_completed'] == summary['scientifically_accepted'] == summary['ml_qualified'] == 0
    assert summary['original_source_objects_checked'] == 1
    assert summary['verified_original_bytes'] == source.stat().st_size
    rows = {r['work_id']: r for r in map(json.loads, (out / 'papers.jsonl').read_text().splitlines())}
    assert rows['aps:10.example/one']['next_source_action'] == 'aps_authorization_pending'
    assert rows['arxiv:2401.00003']['next_source_action'] == 'original_source_missing'
    assert all(r['new_campaign_state'] == 'not_enqueued' for r in rows.values())
    # The reader cannot silently replace a previous immutable readiness snapshot.
    with pytest.raises(FileExistsError):
        capture(root, plan, plan_sha256=pin, output=out)


@pytest.mark.parametrize('change', ['changed', 'missing', 'symlink'])
def test_bundle_without_original_bytes_is_not_ready(tmp_path, change):
    root, source, plan, pin = fixture(tmp_path)
    raw = source.read_bytes()
    if change == 'changed':
        source.write_bytes(raw + b' Changed.')
    else:
        source.unlink()
        if change == 'symlink':
            elsewhere = tmp_path / 'other'
            elsewhere.write_bytes(raw)
            source.symlink_to(elsewhere)
    summary = capture(root, plan, plan_sha256=pin, output=tmp_path / 'snapshot')
    assert summary['unverified_original_objects'] == 1
    assert summary['next_source_actions']['source_representation_or_bytes_repair_required'] == 1


def test_no_source_mtime_selection_and_withdrawal_is_held():
    paper = {'source': 'arxiv', 'acquisition_status': 'available_in_gcs'}
    bundle = {'original_bytes_verified': True, 'processing_allowed': True,
              'has_original_main_document': True, 'pdf_wrapper_only': False}
    assert source_action(paper, [bundle, bundle], None, []) == 'source_selection_required'
    assert source_action(paper, [bundle], {'exclude_from_new_ner': True}, []) == 'source_advisory_hold'


def test_plan_pin_precedes_any_output(tmp_path):
    root, _, plan, _ = fixture(tmp_path)
    out = tmp_path / 'snapshot'
    with pytest.raises(ValueError, match='source_plan_pin_mismatch'):
        capture(root, plan, plan_sha256='0' * 64, output=out)
    assert not out.exists()
