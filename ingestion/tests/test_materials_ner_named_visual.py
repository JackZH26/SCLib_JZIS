"""Synthetic controls for source-named optical quantities; no physical Gold."""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner import visual_regions as visual, reviewed_proposals as projection
from ingestion.materials_ner.contract import canonical, digest, parse_extraction
from ingestion.materials_ner.sources import sha
from ingestion.materials_ner.proposals import verify_packet
from ingestion.materials_ner.validation import training_exclusions, CONTEXT_CONSISTENCY_VERSION
from test_materials_ner_reviewed_proposals import prepared
from test_materials_ner_visual_regions import region_case, make_packet


@pytest.fixture
def named_case(region_case):
    case, original = region_case
    g = case['extraction'].model_dump()
    r = g['results'][0]
    # Deliberately leave an otherwise familiar quantity unregistered. A name
    # or optical value must never silently choose its scientific category.
    r.update(quantity_kind='unmapped', quantity_name_raw='resistive onset')
    witness = deepcopy(r['evidence'][0]); witness['field'] = '/quantity_name_raw'
    r['evidence'].append(witness)
    case['extraction'] = parse_extraction(g)
    return case, original


def validate(case, *, consistency_version=None):
    support = visual.build(**case, version=visual.NAMED_VERSION)
    return projection.validate_graph(case['extraction'].model_dump(), case['bundle'], case['scope'],
        case['manifest'], support, consistency_version=consistency_version)


@pytest.mark.parametrize('policy', [None, CONTEXT_CONSISTENCY_VERSION])
def test_named_visual_keeps_domain_hold_and_no_normalization(named_case, policy):
    case, original = named_case
    before = deepcopy(case['extraction'].model_dump())
    extraction, checked = validate(case, consistency_version=policy)
    assert checked['validator_version'] == 'materials-ner-validation/1.28.0'
    assert checked['visual_evidence_policy'] == visual.NAMED_VERSION
    assert checked['issues'] == [dict(code='unregistered_quantity_requires_domain_review', path='/results/0')]
    assert not checked['valid'] and '/results/0/quantity' not in checked['normalized']
    optical = [e for e in checked['resolved_evidence'] if e.get('kind') == 'visual_region']
    assert len(optical) == 1 and optical[0]['transcription'] == '5 K'
    assert not {'quote', 'start_char', 'end_char'} & set(optical[0])
    assert extraction.model_dump() == before
    assert not training_exclusions(extraction, case['bundle'], checked)['results'][0]['eligible']


def test_v1_replay_does_not_gain_new_acceptance(named_case):
    case, _ = named_case
    with pytest.raises(ValueError, match='quantity_source_conflict'):
        visual.build(**case)
    support = visual.build(**case, version=visual.NAMED_VERSION)
    support['schema'] = visual.VERSION
    support['support_sha256'] = digest({k: v for k, v in support.items() if k != 'support_sha256'})
    with pytest.raises(ValueError, match='quantity_source_conflict'):
        visual.resolve(support, case['bundle'], case['manifest'], case['scope'], case['extraction'])


@pytest.mark.parametrize('changes,code', [
    ({'value': 7.0}, 'numeric_value_disagrees_with_raw'),
    ({'unit': 'meV'}, 'numeric_source_unit_mismatch'),
    ({'relation': 'le', 'value': None, 'upper': 5.0}, 'numeric_value_disagrees_with_raw'),
    ({'uncertainty': dict(minus=.1, plus=.1, kind='reported_unspecified', raw='0.1')},
     'uncertainty_not_in_raw_requires_review'),
])
def test_visual_unmapped_checks_numeric_shape_without_repair(named_case, changes, code):
    case, _ = named_case
    g = case['extraction'].model_dump(); g['results'][0]['quantity'].update(changes)
    case['extraction'] = parse_extraction(g)
    before = case['extraction'].model_dump()
    _, checked = validate(case)
    assert code in {i['code'] for i in checked['issues']}
    assert 'unregistered_quantity_requires_domain_review' in {i['code'] for i in checked['issues']}
    assert '/results/0/quantity' not in checked['normalized']
    assert case['extraction'].model_dump() == before


@pytest.mark.parametrize('change', ['name_witness', 'raw_mismatch', 'duplicate_quantity', 'version'])
def test_named_visual_cannot_bypass_source_bindings(named_case, change):
    case, _ = named_case
    if change == 'name_witness':
        case['extraction'].results[0].evidence = [e for e in case['extraction'].results[0].evidence
                                                if e.field != '/quantity_name_raw']
        _, checked = validate(case)
        assert any(i['code'] == 'field_evidence_missing' and i['path'].endswith('/quantity_name_raw')
                   for i in checked['issues'])
    else:
        version = visual.NAMED_VERSION
        if change == 'raw_mismatch': case['extraction'].results[0].quantity.raw = '7 K'
        elif change == 'duplicate_quantity':
            witness = case['extraction'].results[0].evidence[0].model_copy(deep=True)
            witness.field = '/quantity'; case['extraction'].results[0].evidence.append(witness)
        else: version = 'materials-visual-result-evidence/999'
        with pytest.raises(ValueError): visual.build(**case, version=version)


def test_portable_named_packet_preserves_quarantine_and_pending_review(named_case, monkeypatch):
    from pathlib import Path
    p = make_packet(*named_case, version=visual.NAMED_VERSION)
    assert p['receipt']['state'] == 'quarantined'
    assert p['receipt']['extraction']['results'][0]['quantity_kind'] == 'unmapped'
    assert not p['scientific_acceptance'] and not p['ml_training_eligible']
    def forbidden(*args, **kw): raise AssertionError('portable verification read a live file')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setattr(Path, 'read_text', forbidden)
    verify_packet(p)


def region_asset(case, **changes):
    asset = case['assets'][0]
    observed = json.loads(asset['ocr_json'])
    observed.update(schema='materials-vision-text/2', region_of_interest=[.05, .05, .95, .95],
        minimum_text_height=.001, recognizer_coordinate_system='normalized_roi_lower_left',
        coordinates_transformed_to_full_page=True, **changes)
    asset.update(schema=visual.REGION_ASSET_VERSION, ocr_json=canonical(observed),
        ocr_sha256=sha(canonical(observed).encode()))
    asset['asset_id'] = digest({k: v for k, v in asset.items() if k != 'asset_id'})
    case['bindings'][0]['asset_id'] = asset['asset_id']
    return asset


def test_region_ocr_keeps_original_full_page_and_explicit_policy(named_case):
    case, _ = named_case
    before = deepcopy(case['assets'][0]['capture'])
    asset = region_asset(case)
    _, checked = validate(case)
    assert asset['capture'] == before
    assert checked['issues'] == [dict(code='unregistered_quantity_requires_domain_review', path='/results/0')]
    with pytest.raises(ValueError, match='legacy_asset_policy'): visual.build(**case)


@pytest.mark.parametrize('change,code', [
    ({'region_of_interest': [-.1, 0, 1, 1]}, 'region_bounds'),
    ({'minimum_text_height': .1}, 'ocr_minimum_text_height'),
    ({'coordinates_transformed_to_full_page': False}, 'ocr_coordinate_transform'),
    ({'region_of_interest': [.1, .1, .4, .4]}, 'selected_words_outside_ocr_region'),
])
def test_region_ocr_rejects_unsupported_config_or_misplaced_words(named_case, change, code):
    case, _ = named_case
    # Update a captured observation explicitly, then rehash it to ensure the
    # semantic check, rather than merely a checksum, rejects the mutation.
    asset = region_asset(case)
    observed = json.loads(asset['ocr_json']); observed.update(change)
    asset.update(ocr_json=canonical(observed), ocr_sha256=sha(canonical(observed).encode()))
    asset['asset_id'] = digest({k: v for k, v in asset.items() if k != 'asset_id'})
    case['bindings'][0]['asset_id'] = asset['asset_id']
    with pytest.raises(ValueError, match=code): validate(case)
