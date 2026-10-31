"""Scientific snapshot invariants for a destination catalogue transfer."""
from copy import deepcopy

import pytest

from materials_ner_tc_transfer import typed, verify_planned_claims


def claim():
    return dict(id='claim', paper_id='arxiv:test', value_kelvin=4.2, validity_status='pending',
        raw_record={'quantity': {'raw': '4.2 K'}}, extraction_metadata={
            'native_origin': {'identity_binding_sha256': 'source', 'packet_hash': 'packet'},
            'production_admission': {'policy': 'production90/1', 'quality_status': 'batch_sampled'}})


def test_destination_binding_can_change_without_changing_scientific_provenance():
    original = claim(); candidate = deepcopy(original)
    candidate['extraction_metadata']['native_origin']['identity_binding_sha256'] = 'destination'
    verify_planned_claims({'rows': {'material_claims': [candidate]}}, {'claim': original})


@pytest.mark.parametrize('mutation', ['tc', 'raw', 'quality', 'packet'])
def test_scientific_or_review_changes_are_not_treated_as_catalogue_rebinding(mutation):
    original = claim(); candidate = deepcopy(original)
    if mutation == 'tc': candidate['value_kelvin'] = 9.2
    if mutation == 'raw': candidate['raw_record']['quantity']['raw'] = '9.2 K'
    if mutation == 'quality': candidate['extraction_metadata']['production_admission']['quality_status'] = 'model_source_checked'
    if mutation == 'packet': candidate['extraction_metadata']['native_origin']['packet_hash'] = 'other'
    with pytest.raises(ValueError, match='transfer_(claim_value|scientific_provenance)_changed'):
        verify_planned_claims({'rows': {'material_claims': [candidate]}}, {'claim': original})


def test_an_extra_eligible_result_cannot_expand_the_transferred_snapshot():
    original = claim(); extra = {**deepcopy(original), 'id': 'extra'}
    with pytest.raises(ValueError, match='transfer_claim_scope_changed'):
        verify_planned_claims({'rows': {'material_claims': [original, extra]}}, {'claim': original})


def test_json_anchor_is_compatible_with_the_existing_canonical_put_interface():
    from datetime import datetime
    row = typed('works', {'id': '49e6791f-7a0d-5b1c-8bd1-e81646b81b6d', 'created_at': '2026-10-26T15:12:52+00:00'})
    assert isinstance(row['id'], str)  # _put owns UUID conversion.
    assert isinstance(row['created_at'], datetime)
