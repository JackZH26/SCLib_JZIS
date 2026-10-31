"""Source selection must not upgrade byte identity into scientific readiness."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from materials_ner_corpus_readiness import capture, file_hash
from materials_ner_source_manifest import DECISIONS, freeze, verify
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.sources import load_bundle, save_bundle, sha
from test_materials_ner_corpus_readiness import fixture


def preparation(tmp_path, *, difference='metadata', choose=True):
    root, raw, plan, pin = fixture(tmp_path)
    first = load_bundle(next((root / 'bundles').glob('*.json')))
    second = deepcopy(first)
    second.title = 'An explicit alternative title'
    second.documents[0].parser += ':new'
    second.acquisition_notes.append('A retained parser diagnostic.')
    if difference == 'text':
        second.blocks[0].text += ' Another result was reported.'
        second.blocks[0].sha256 = sha(second.blocks[0].text.encode())
    elif difference == 'version':
        second.documents[0].publication_version = 'v2'
    second_id, _ = save_bundle(root, second)
    first_id = digest(first.model_dump())
    readiness = tmp_path / 'readiness'
    capture(root, plan, plan_sha256=pin, output=readiness)
    decision = {'work_id': first.work_id, 'candidate_bundle_sha256s': sorted([first_id, second_id]),
                'selected_bundle_sha256': second_id,
                'reason': 'Select the explicit parser representation and preserve both inputs.'}
    decisions = tmp_path / 'decisions.json'
    decisions.write_text(canonical({'schema': DECISIONS, 'source_plan_sha256': pin,
                                    'selections': [decision] if choose else []}))
    kwargs = dict(root=root, plan_path=plan, readiness=readiness,
                  readiness_files_sha256=file_hash(readiness / 'FILES.json'),
                  decisions_path=decisions, output=tmp_path / 'manifest')
    return kwargs, first_id, second_id, raw


def test_selection_preserves_denominator_and_never_claims_version_or_completion(tmp_path):
    args, first, chosen, original = preparation(tmp_path)
    before = original.read_bytes()
    result = freeze(**args)
    assert result['papers'] == sum(result['dispositions'].values()) == 4
    assert result['selected_works'] == result['explicit_equivalence_choices'] == 1
    assert result['dispositions']['aps_authorization_pending'] == 1
    assert result['dispositions']['original_source_missing'] == 1
    assert result['new_campaign_completed'] == result['new_campaign_enqueued'] == 0
    assert result['permits_model_dispatch'] is result['scientific_acceptance'] is False
    row = json.loads((args['output'] / 'selections.jsonl').read_text())
    assert row['bundle_sha256'] == chosen
    assert 'paper_coverage_audit_required' in row['preflight_holds']
    assert original.read_bytes() == before
    assert (args['root'] / 'bundles' / (first + '.json')).exists()
    header = args['output'] / 'MANIFEST.json'
    assert verify(header, sha256=file_hash(header))['verified']
    with pytest.raises(FileExistsError):
        freeze(**args)


def test_mtime_cannot_select_an_ambiguous_representation(tmp_path):
    args, first, _, _ = preparation(tmp_path, choose=False)
    os.utime(args['root'] / 'bundles' / (first + '.json'), (2100000000, 2100000000))
    result = freeze(**args)
    assert result['selected_works'] == 0
    assert result['dispositions']['source_selection_required'] == 1


@pytest.mark.parametrize('difference', ['text', 'version'])
def test_only_metadata_equivalence_can_resolve_a_choice(tmp_path, difference):
    args, *_ = preparation(tmp_path, difference=difference)
    with pytest.raises(ValueError, match='representations_not_equivalent'):
        freeze(**args)
    assert not args['output'].exists()


@pytest.mark.parametrize('mutation', ['source_changed', 'source_missing', 'source_symlink', 'snapshot_changed'])
def test_changed_inputs_refused_before_output(tmp_path, mutation):
    args, _, _, raw = preparation(tmp_path)
    if mutation == 'source_changed':
        raw.write_bytes(raw.read_bytes() + b' changed')
    elif mutation == 'source_missing':
        raw.unlink()
    elif mutation == 'source_symlink':
        target = tmp_path / 'copy'
        target.write_bytes(raw.read_bytes())
        raw.unlink()
        raw.symlink_to(target)
    else:
        (args['readiness'] / 'papers.jsonl').write_text('{}\n')
    with pytest.raises(ValueError):
        freeze(**args)
    assert not args['output'].exists()


@pytest.mark.parametrize('kind', ['extra_candidate', 'wrong_choice', 'duplicate_work', 'aps_substitution'])
def test_stale_or_out_of_scope_decisions_are_not_silently_applied(tmp_path, kind):
    args, *_ = preparation(tmp_path)
    decisions = json.loads(args['decisions_path'].read_text())
    decision = decisions['selections'][0]
    if kind == 'extra_candidate':
        decision['candidate_bundle_sha256s'].append('0' * 64)
    elif kind == 'wrong_choice':
        decision['selected_bundle_sha256'] = '0' * 64
    elif kind == 'duplicate_work':
        decisions['selections'].append(deepcopy(decision))
    else:
        decision['work_id'] = 'aps:10.example/one'
    args['decisions_path'].write_text(canonical(decisions))
    with pytest.raises(ValueError):
        freeze(**args)
    assert not args['output'].exists()


@pytest.mark.parametrize('target', ['source', 'manifest', 'selection', 'proof'])
def test_closed_manifest_verification_detects_later_drift(tmp_path, target):
    args, _, _, raw = preparation(tmp_path)
    freeze(**args)
    header = args['output'] / 'MANIFEST.json'
    pin = file_hash(header)
    paths = {'source': raw, 'manifest': header, 'selection': args['output'] / 'selections.jsonl',
             'proof': args['output'] / 'SELECTION_PROOF.json'}
    path = paths[target]
    path.write_bytes(path.read_bytes() + b' changed')
    with pytest.raises(ValueError):
        verify(header, sha256=pin)


def test_source_root_cannot_be_reused_as_output(tmp_path):
    args, *_ = preparation(tmp_path)
    args['output'] = args['root'] / 'new-manifest'
    with pytest.raises(ValueError, match='separate'):
        freeze(**args)
