"""Unregistered quantities still owe literal numeric fidelity; no Gold claims."""
from copy import deepcopy

import pytest

from ingestion.materials_ner.contract import Evidence, Quantity
from ingestion.materials_ner.quantities import unmapped_quantity_source_issues
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.wire_v10 import DetectionExtraction
from test_materials_ner_pipeline import quantity
from test_materials_ner_non_detection_targets import fixture, append_source


def check(raw, *, quote=None, **updates):
    value = Quantity.model_validate(dict(quantity(.5, 'μm', raw), **updates))
    evidence = [Evidence(block_id='B1', field='/quantity', quote=quote or raw)]
    before = value.model_dump()
    result = unmapped_quantity_source_issues(value, evidence, '/quantity')
    assert value.model_dump() == before
    return result


@pytest.mark.parametrize('raw,updates', [
    ('0.5', {}), ('≈0.5 μm', {'approximate': True}),
    ('0.5 ± 0.03 μm', {'uncertainty': {'minus': .03, 'plus': .03, 'kind': 'reported_unspecified', 'raw': '± 0.03'}}),
    ('0.50(3) μm', {'uncertainty': {'minus': .03, 'plus': .03, 'kind': 'reported_unspecified', 'raw': '± 0.03'}}),
    ('-0.5 μm', {'value': -.5}),
    ('0.4 to 0.6 μm', {'relation': 'interval', 'value': None, 'lower': .4, 'upper': .6}),
    ('0.4 μm to 0.6 μm', {'relation': 'interval', 'value': None, 'lower': .4, 'upper': .6}),
    ('≤ 0.5 μm', {'relation': 'le', 'value': None, 'upper': .5}),
    ('> 0.5 μm', {'relation': 'gt', 'value': None, 'lower': .5}),
    (r'0.5 \mu m', {}),
    ('0.5 A/(B C)', {'unit': 'A/(B C)'}),
])
def test_source_shapes_survive_without_physical_registration(raw, updates):
    assert check(raw, **updates) == []


@pytest.mark.parametrize('raw,updates,code', [
    ('0.5', {'relation': 'interval', 'value': None, 'lower': .45, 'upper': .55,
             'approximate': True}, 'numeric_value_disagrees_with_raw'),
    ('0.5 ± 0.03', {'relation': 'interval', 'value': None, 'lower': .47, 'upper': .53,
                     'uncertainty': {'minus': .03, 'plus': .03, 'kind': 'reported_unspecified', 'raw': '± 0.03'}}, 'numeric_value_disagrees_with_raw'),
    ('0.4 to 0.6', {}, 'numeric_value_disagrees_with_raw'),
    ('≈ 0.5', {}, 'approximation_marker_lost'),
    ('0.5 ± 0.03', {}, 'uncertainty_lost'),
    ('0.5 ± 0.03', {'uncertainty': {'minus': .02, 'plus': .02, 'kind': 'reported_unspecified', 'raw': '± 0.03'}}, 'uncertainty_disagrees_with_raw'),
    ('0.5', {'uncertainty': {'minus': .1, 'plus': .1, 'kind': 'reported_unspecified', 'raw': '± 0.03'}}, 'uncertainty_not_in_raw_requires_review'),
    ('0.5 nm', {}, 'numeric_source_unit_mismatch'),
    ('0.5 m', {'value': 500000}, 'numeric_source_unit_mismatch'),
    ('0.4 nm to 0.6 μm', {'relation': 'interval', 'value': None, 'lower': .4, 'upper': .6}, 'numeric_source_unit_mismatch'),
    ('0.5 A/(B C)', {'unit': 'A/B C'}, 'numeric_source_unit_mismatch'),
    ('lambda = 0.5', {}, 'numeric_raw_requires_review'),
    ('0.5 at 4 K', {}, 'numeric_source_unit_mismatch'),
])
def test_invented_shapes_and_ambiguous_units_are_explicit_failures(raw, updates, code):
    assert code in check(raw, **updates)


def test_quantity_requires_its_own_evidence_and_unreported_is_not_zero():
    assert check('0.5', quote='A different result was 8.8 K.') == ['quantity_raw_not_in_field_evidence']
    assert unmapped_quantity_source_issues(Quantity(status='not_reported'), [], '/quantity') == []


@pytest.mark.parametrize('invented', [False, True])
def test_full_validator_checks_unmapped_but_never_normalizes_or_releases_it(invented):
    bundle, _, raw = fixture(); append_source(bundle, 'The Josephson penetration depth was approximately 0.5 μm.')
    result = raw['observations'][0]['result']
    result.update(quantity_kind='unmapped', quantity_name_raw='Josephson penetration depth',
                  quantity=quantity(.5, 'μm', '0.5'), qualifiers=[])
    result['quantity']['approximate'] = True
    result['evidence'][0]['fields'].append('/quantity_name_raw')
    if invented:
        result['quantity'].update(relation='interval', value=None, lower=.45, upper=.55)
    extraction = DetectionExtraction.model_validate(raw).expand(bundle)
    before = deepcopy(extraction.model_dump())
    checked = validate_extraction(extraction, bundle)
    codes = {item['code'] for item in checked['issues'] if item['path'].startswith('/results/0')}
    assert 'unregistered_quantity_requires_domain_review' in codes
    assert ('numeric_value_disagrees_with_raw' in codes) == invented
    assert '/results/0/quantity' not in checked['normalized']
    assert not training_exclusions(extraction, bundle, checked)['results'][0]['eligible']
    assert extraction.model_dump() == before
