"""Language checks exempt only original evidence quotes, never metadata."""
from copy import deepcopy

import pytest

from materials_ner_tc_export_language import check_csv_rows, check_records


def test_original_quote_is_preserved_without_mutating_input():
    records = [{'id': 'record-1', 'evidence': [{'quote': '%図1\nTc = 4 K', 'role': 'value'}]}]
    original = deepcopy(records)
    assert check_records(records, source_evidence=True) == 1
    assert records == original
    with pytest.raises(ValueError, match='cjk_in_structured'):
        check_records(records)
    row = {'record_id': 'record-1', 'quote': records[0]['evidence'][0]['quote']}
    assert check_csv_rows('materials_evidence.csv', list(row), [row]) == 1
    assert row['quote'] == original[0]['evidence'][0]['quote']


@pytest.mark.parametrize('record', [
    {'measurement_method': '电阻率'},
    {'formula_as_written': '材料'},
    {'evidence': [{'quote': 'Original text', 'role': '数值'}]},
    {'metadata': {'quote': '非原文'}},
])
def test_non_quote_fields_are_not_exempt(record):
    with pytest.raises(ValueError, match='cjk_in_structured'):
        check_records([record], source_evidence=True)


@pytest.mark.parametrize('filename,row', [
    ('materials_results.csv', {'quote': '図1'}),
    ('materials_training.csv', {'feature_formula_as_written': '材料'}),
    ('materials_evidence.csv', {'quote': 'Original text', 'role': '数值'}),
])
def test_csv_exception_is_limited_to_evidence_quote(filename, row):
    with pytest.raises(ValueError, match='cjk_in_structured'):
        check_csv_rows(filename, list(row), [row])


def test_quote_exception_does_not_expose_private_paths():
    with pytest.raises(ValueError, match='private_path'):
        check_csv_rows('materials_evidence.csv', ['quote'], [{'quote': '/Users/private/file'}])
