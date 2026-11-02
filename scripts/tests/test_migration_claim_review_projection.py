"""Historical comparisons retain all v1 values and refuse v2 claim history."""
from copy import deepcopy
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]))
from migration_revision_scope import pre_claim_review_rows


@pytest.mark.parametrize("table",["scientific_result_subjects","scientific_result_decisions"])
def test_only_absent_vs_null_legacy_target_is_equivalent(table):
    row={"id":"same","property_id":"exact-property","subject_version":"scientific-result-subject/1.0.0",
         "record_sha256":"retained-hash","basis_json":"literal bytes","value":39}
    original=deepcopy(row)
    assert pre_claim_review_rows(table,[row])==pre_claim_review_rows(table,[{**row,"claim_id":None}])
    assert row==original
    changed={**row,"claim_id":None,"record_sha256":"different"}
    assert pre_claim_review_rows(table,[changed])!=pre_claim_review_rows(table,[row])


@pytest.mark.parametrize("row",[
    {"claim_id":"a-claim","property_id":None,"subject_version":"scientific-result-subject/2.0.0"},
    {"claim_id":None,"property_id":None,"subject_version":"scientific-result-subject/1.0.0"},
    {"claim_id":None,"property_id":"a-property","subject_version":"scientific-result-subject/2.0.0"},
])
def test_new_or_malformed_history_is_not_hidden(row):
    with pytest.raises(AssertionError): pre_claim_review_rows("scientific_result_subjects",[row])


def test_other_tables_never_lose_a_claim_field():
    rows=[{"claim_id":"scientific-label","id":"one"}]
    assert pre_claim_review_rows("ml_examples",rows)==rows


def test_historical_answer_comparison_preserves_every_old_field_and_hash():
    row={'id':'old-answer','answer':'literal old answer','record_sha256':'original-receipt-hash'}
    assert pre_claim_review_rows('ask_history',[row])==pre_claim_review_rows('ask_history',[
        {**row,'content_evidence_receipt_version':None}])
    assert pre_claim_review_rows('ask_history',[row])!=pre_claim_review_rows('ask_history',[
        {**row,'answer':'changed','content_evidence_receipt_version':None}])


def test_retained_v2_marker_cannot_be_hidden_by_historical_projection():
    with pytest.raises(AssertionError,match='Retained content history'):
        pre_claim_review_rows('ask_history',[{'id':'v2','content_evidence_receipt_version':'ask-answer-evidence/2.0.0'}])
