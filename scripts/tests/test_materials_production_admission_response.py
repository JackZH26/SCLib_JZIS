"""Read contract only; synthetic flags are not scientific validation."""
from copy import deepcopy

import pytest

from models.ml_foundation import ProductionAdmissionResponse
from services.material_visibility import sanitize_review_metadata


def metadata():
    return dict(production_admission=dict(policy='production90/1',
        quality_status='model_source_checked',batch_qualified=True,per_record_checked=True,
        reviewer_kind='model',independent_expert_review=False,selection_sha256='a'*64,
        audit_sha256='b'*64,source_scope='selected_source_assertion',complete_paper=False))


def test_record_review_is_public_without_private_output_or_validity_promotion():
    value=metadata();value['production_admission'].update(raw_output='private',path='/private/file')
    result=ProductionAdmissionResponse.from_extraction_metadata(value).model_dump()
    expected=metadata()['production_admission'];expected['review_kind']=expected.pop('reviewer_kind')
    expected['admission_route']='qualified_batch'
    assert result==expected
    assert ProductionAdmissionResponse.model_validate(sanitize_review_metadata(result)).model_dump()==result
    assert not result['independent_expert_review'] and not result['complete_paper']
    assert 'validity_status' not in result and 'scientific_acceptance' not in result


def test_batch_sampled_does_not_claim_individual_review():
    value=metadata();value['production_admission'].update(quality_status='batch_sampled',per_record_checked=False)
    result=ProductionAdmissionResponse.from_extraction_metadata(value)
    assert result.quality_status=='batch_sampled' and not result.per_record_checked


def test_individual_admission_preserves_the_failed_batch_status():
    value=metadata();value['production_admission'].update(batch_qualified=False,admission_route='individual_source_check')
    result=ProductionAdmissionResponse.from_extraction_metadata(value)
    assert result is not None and result.per_record_checked and not result.batch_qualified
    assert result.admission_route=='individual_source_check'
    value['production_admission'].update(per_record_checked=False,quality_status='batch_sampled')
    assert ProductionAdmissionResponse.from_extraction_metadata(value) is None


@pytest.mark.parametrize('change',[
    dict(quality_status='batch_sampled'),dict(per_record_checked='true'),
    dict(batch_qualified=False),dict(independent_expert_review=True),dict(audit_sha256='missing'),
])
def test_inconsistent_or_incomplete_metadata_cannot_create_a_review_badge(change):
    value=deepcopy(metadata());value['production_admission'].update(change)
    assert ProductionAdmissionResponse.from_extraction_metadata(value) is None


def test_legacy_claim_has_no_fabricated_admission_status():
    assert ProductionAdmissionResponse.from_extraction_metadata({}) is None
    assert ProductionAdmissionResponse.from_extraction_metadata(None) is None
