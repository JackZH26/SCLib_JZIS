"""Training delivery preserves review provenance and excludes invalid labels."""
import hashlib
import json

import pytest

from materials_ner_tc_training_view import build


def record():
    return dict(id='record-1', paper_id='arxiv:test', work_id='work-1', split_group='work-1',
        sample_group='sample-1', cross_paper_reused_sample_group='unresolved',
        raw_record=dict(origin='observed', source_role='primary'), value_relation='exact', value_kelvin=5.1,
        quantity=dict(unit='K', approximate=True, uncertainty=None),
        compositions=[dict(formula_raw='TaIr2B2')], conditions=dict(pressure=dict(regime='unknown')),
        composition_context=dict(target_kind='bulk'), pressure_gpa=None, magnetic_field_t=None,
        tc_definition='onset', measurement_method='resistivity', publication_versions=['v1'],
        validity_status='pending', paper_status='published', publication_status='unknown',
        quality=dict(quality_status='batch_sampled', per_record_checked=False, batch_qualified=True,
            source_scope='selected_source_assertion', complete_paper=False))


def run(tmp_path, rows):
    source = tmp_path / 'source.jsonl'
    source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    out = tmp_path / 'training'
    manifest = build(source, out)
    included = [json.loads(line) for line in (out / 'TRAINING_ROWS.jsonl').read_text().splitlines()]
    excluded = [json.loads(line) for line in (out / 'EXCLUDED_FROM_SCALAR_VIEW.jsonl').read_text().splitlines()]
    return source, manifest, included, excluded


@pytest.mark.parametrize('field,status', [
    ('paper_status', 'retracted'), ('paper_status', 'withdrawn'), ('publication_status', 'refuted'),
    ('publication_status', 'retracted'), ('validity_status', 'excluded'), ('validity_status', 'superseded'),
])
def test_invalidated_snapshot_labels_are_not_training_examples(tmp_path, field, status):
    bad = record(); bad.update(id='record-2', **{field: status})
    _, manifest, included, excluded = run(tmp_path, [record(), bad])
    assert [r['record_id'] for r in included] == ['record-1']
    assert [r['record_id'] for r in excluded] == ['record-2']
    assert excluded[0]['remains_in_source_dataset'] is True
    assert manifest['excluded_from_scalar_view'] == 1


def test_unknown_status_and_batch_review_remain_explicit_without_becoming_features(tmp_path):
    source, manifest, rows, excluded = run(tmp_path, [record()])
    row = rows[0]
    assert not excluded
    assert row['provenance']['publication_status'] == 'unknown'
    assert row['provenance']['quality_status'] == 'batch_sampled'
    assert row['provenance']['per_record_checked'] is False
    assert row['provenance']['dataset_version'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert row['provenance']['source_versions'] == ['v1']
    assert row['features'] == dict(formula_as_written='TaIr2B2', specimen_form='bulk', pressure_regime='unknown')
    assert row['target']['tc_kelvin'] == 5.1
    assert manifest['provenance_is_not_model_input'] is True


def test_metadata_upgrade_keeps_the_existing_group_split(tmp_path):
    rows = []
    for i in range(30):
        row = record(); row.update(id=f'record-{i}', work_id=f'work-{i}', split_group=f'work-{i}', sample_group=f'sample-{i}')
        rows.append(row)
    _, _, included, _ = run(tmp_path, rows)
    for row in included:
        work = row['groups']['work_id']
        score = int(hashlib.sha256(('materials-reported-tc-training-view/1:' + work).encode()).hexdigest()[:16], 16) / 2**64
        assert row['groups']['split'] == ('train' if score < .8 else 'validation' if score < .9 else 'test')
