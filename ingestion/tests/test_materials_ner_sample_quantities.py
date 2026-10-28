"""Composition and isotope quantities cannot invent numbers from source symbols."""
from copy import deepcopy

import pytest

from ingestion.materials_ner.contract import Extraction
from ingestion.materials_ner.sources import sha
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from test_materials_ner_pipeline import example, quantity


def check(value, *, collection='variables', quoted=None):
    bundle, raw = example()
    member = 'amount' if collection == 'variables' else 'fraction'
    entry = ({'symbol': 'y', 'site': 'O', 'basis': 'unresolved', member: value}
             if collection == 'variables' else {'element': 'O', 'mass_number': 18, member: value})
    sample = raw['samples'][0]
    sample[collection] = [entry]
    sentence = 'Synthetic composition assertion: ' + (quoted or value.get('raw') or 'not reported') + '.'
    bundle.blocks[0].text += ' ' + sentence
    bundle.blocks[0].sha256 = sha(bundle.blocks[0].text.encode())
    sample['evidence'].append(dict(block_id=bundle.blocks[0].id, field=f'/{collection}/0', quote=sentence))
    extraction = Extraction.model_validate(raw)
    before = deepcopy(extraction.model_dump())
    report = validate_extraction(extraction, bundle)
    assert extraction.model_dump() == before
    assert not report['scientific_acceptance']
    assert not training_exclusions(extraction, bundle, report)['results'][0]['eligible']
    path = f'/samples/0/{collection}/0/{member}'
    assert path not in report['normalized']  # No inferred basis or conversion.
    return {i['code'] for i in report['issues'] if i['path'] == path}


@pytest.mark.parametrize('collection', ['variables', 'isotopes'])
@pytest.mark.parametrize('raw,updates,code', [
    ('y', {'value': 0}, 'numeric_raw_requires_review'),
    ('0.1 to 0.2', {'value': .15}, 'numeric_value_disagrees_with_raw'),
    ('< 0.2', {'value': None, 'relation': 'ge', 'lower': .2}, 'numeric_value_disagrees_with_raw'),
    ('0.15(2)', {'value': .15}, 'uncertainty_lost'),
    ('≈ 0.15', {'value': .15}, 'approximation_marker_lost'),
    ('15 %', {'value': .15, 'unit': '1'}, 'numeric_source_unit_mismatch'),
])
def test_symbol_zero_means_bounds_uncertainty_and_unit_changes_are_held(collection, raw, updates, code):
    assert code in check(dict(quantity(.15, '1', raw), **updates), collection=collection)


@pytest.mark.parametrize('collection', ['variables', 'isotopes'])
@pytest.mark.parametrize('raw,updates', [
    ('0', {'value': 0}),  # Explicit measured/nominal zero is not missingness.
    ('0.15', {}),
    ('15 %', {'value': 15, 'unit': '%'}),
    ('0.1 to 0.2', {'value': None, 'relation': 'interval', 'lower': .1, 'upper': .2}),
    ('< 0.2', {'value': None, 'relation': 'lt', 'upper': .2}),
    ('0.15(2)', {'uncertainty': {'kind': 'reported_unspecified', 'minus': .02, 'plus': .02, 'raw': '(2)'}}),
])
def test_explicit_source_shapes_survive_without_chemical_inference(collection, raw, updates):
    assert check(dict(quantity(.15, '1', raw), **updates), collection=collection) == set()


@pytest.mark.parametrize('status', ['not_reported', 'not_accessible', 'not_extracted', 'ambiguous', 'conflicted', 'not_applicable'])
def test_unknown_symbol_stays_unresolved_without_requiring_an_invented_number(status):
    assert check(dict(status=status, raw='y', unit='1')) == set()


def test_number_in_another_source_field_does_not_support_composition():
    assert check(quantity(0, '1', '0'), quoted='oxygen deficiency y was not determined') == {'quantity_raw_not_in_field_evidence'}
