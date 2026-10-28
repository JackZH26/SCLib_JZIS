"""Known-correction preservation at the boundary between a local and released DB."""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner import reviewed_reader as rr
from materials_ner_tc_release_plan import exclusion_evidence, check_membership
from materials_ner_tc_sampling import BATCH_ROUTE, RECORD_ROUTE


def fixture(tmp_path, *, before_wrapper=True, changes=None):
    directory = tmp_path / 'record-reviews' / 'case'
    directory.mkdir(parents=True)
    admission = dict(policy='production90/1', selection_sha256='selection', audit_sha256='audit')
    locator = dict(run_id='run', source_result_id='r1', projection_sha256='projection')
    old = dict(id='claim', paper_id='arxiv:test', validity_status='pending', raw_record={'tc': 4},
        source_locator=locator, extraction_metadata={'production_admission': admission})
    new = deepcopy(old); new['validity_status'] = 'excluded'
    new.update(changes or {})
    before = directory / 'BEFORE.json'; before.write_text(json.dumps({'claim': old} if before_wrapper else old))
    after = directory / 'AFTER.json'; after.write_text(json.dumps(new))
    commit = dict(claim_id='claim', validity_status='excluded', before=rr.reference(before), after=rr.reference(after))
    (directory / 'COMMITTED.json').write_text(json.dumps(commit))
    row = dict(id='claim', paper_id='arxiv:test', validity_status='excluded',
        source_locator=locator, admission=admission, exclusion_reason='claim_not_currently_usable')
    return row, after


@pytest.mark.parametrize('wrapped', [False, True])
def test_corrected_record_stays_excluded_in_transfer_scope(tmp_path, wrapped):
    row, _ = fixture(tmp_path, before_wrapper=wrapped)
    updates = exclusion_evidence(tmp_path, [row])
    assert len(updates) == 1
    assert updates[0]['claim_id'] == 'claim'
    assert updates[0]['target_validity_status'] == 'excluded'
    assert updates[0]['original_admission'] == row['admission']


def test_missing_correction_proof_does_not_silently_reenable_the_record(tmp_path):
    with pytest.raises(ValueError, match='excluded_claim_without_correction_receipt'):
        exclusion_evidence(tmp_path, [{'id': 'unknown', 'exclusion_reason': 'claim_not_currently_usable'}])


def test_changed_retained_evidence_is_rejected(tmp_path):
    row, after = fixture(tmp_path)
    after.write_text(after.read_text() + ' ')
    with pytest.raises(ValueError, match='production90_input_changed'):
        exclusion_evidence(tmp_path, [row])


def test_a_validity_update_cannot_conceal_changed_tc(tmp_path):
    row, _ = fixture(tmp_path, changes={'raw_record': {'tc': 9}})
    with pytest.raises(ValueError, match='correction_rewrites_scientific_record'):
        exclusion_evidence(tmp_path, [row])


def test_correction_cannot_be_rebound_to_another_source_result(tmp_path):
    row, _ = fixture(tmp_path)
    row['source_locator'] = {**row['source_locator'], 'source_result_id': 'r2'}
    with pytest.raises(ValueError, match='correction_receipt_source_binding_mismatch'):
        exclusion_evidence(tmp_path, [row])


def test_sampled_bad_record_is_not_admittable_in_release(monkeypatch, tmp_path):
    import materials_ner_tc_release_plan as module
    monkeypatch.setattr(module, 'admission_quality', lambda *args: {'qualified': True})
    candidate = dict(work_id='arxiv:test', result_id='r1', run_id='run', status='eligible_for_source_audit')
    projection = tmp_path / 'projection.json'
    projection.write_text(json.dumps(dict(projection_sha256='projection', records=[candidate])))
    key = dict(work_id='arxiv:test', result_id='r1', run_id='run', projection_sha256='projection')
    selection = dict(schema='materials-native-tc-sample/1', method='simple_random_without_replacement',
        source_entries=[{'projection': rr.reference(projection)}])
    audit = dict(records=[{**key, 'verdict': 'incorrect', 'review_completed': True}])
    row = dict(paper_id='arxiv:test', source_locator=dict(run_id='run', source_result_id='r1', projection_sha256='projection'))
    for route in (BATCH_ROUTE, RECORD_ROUTE):
        with pytest.raises(ValueError, match='canonical_record_outside_original_admission'):
            check_membership([row], selection, audit, route)
