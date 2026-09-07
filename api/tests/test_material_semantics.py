"""Synthetic SC10 fixtures, not scientific adjudication or measured findings."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from services.material_semantics import (
    MATERIAL_SEMANTICS_FIELDS,
    MATERIAL_SEMANTICS_VERSION,
    MAX_EVIDENCE,
    MAX_RECORDS,
    STATUS_VOCABULARY,
    build_material_semantics,
)

ROOT = Path(__file__).resolve().parents[2]


def _record(**changes):
    return {"paper_id": "synthetic:one", "sample_id": "sample:a", **changes}


def _report(records, **changes):
    return build_material_semantics(records, scope_id="mat:synthetic", **changes)


def _property(records, field="has_competing_order", **changes):
    return _report(records, **changes)["properties"][field]


def test_api_and_ingestion_vendor_identical_contract_bytes():
    assert (ROOT / "api/services/material_semantics.py").read_bytes() == (
        ROOT / "ingestion/ingestion/material_semantics.py"
    ).read_bytes()


def test_small_versioned_vocabulary_is_explicit():
    assert MATERIAL_SEMANTICS_VERSION == "material-semantics/1.0.0"
    assert set(MATERIAL_SEMANTICS_FIELDS) == {"has_competing_order", "is_unconventional", "pairing_symmetry"}
    assert set(STATUS_VOCABULARY) == {"reported", "unknown", "not_reported", "not_extracted", "not_computed", "failed", "conflicted", "not_applicable"}


@pytest.mark.parametrize("records", [[], [_record()], [_record(has_competing_order=None)], [_record(competing_order=None)], [_record(t_cdw_k=25)], [_record(t_sdw_k=25, t_afm_k=30)]])
def test_missing_order_evidence_and_order_temperatures_are_not_false_or_true(records):
    prop = _property(records)
    assert prop["status"] == "unknown"
    assert prop["value"] is None


@pytest.mark.parametrize("order", ["CDW", "AFM", "SDW", "Mott_insulator", "PDW"])
def test_explicit_order_indicator_is_reported_but_not_causal_competition(order):
    prop = _property([_record(competing_order=order)])
    assert prop["status"] == "reported" and prop["value"] is True
    evidence = prop["evidence"][0]
    assert evidence["source_value"] == order
    assert evidence["basis"] == "reported_competing_order_label"
    assert "reported_order_indicator_not_causal_competition" in evidence["reason_codes"]
    assert evidence["knowledge_origin"] == "Unknown"


@pytest.mark.parametrize("invalid", ["false", "true", 0, 1, [], {}, "none", "unknown"])
def test_boolean_fields_do_not_coerce_strings_numbers_or_placeholders(invalid):
    prop = _property([_record(has_competing_order=invalid)])
    assert prop["status"] == "unknown" and prop["value"] is None


@pytest.mark.parametrize("field", ["has_competing_order", "is_unconventional"])
def test_unqualified_false_is_retained_as_evidence_not_material_absence(field):
    prop = _property([_record(**{field: False})], field)
    assert prop["status"] == "unknown" and prop["value"] is None
    evidence = prop["evidence"][0]
    assert evidence["value"] is False
    assert evidence["status"] == "reported"
    assert evidence["negative_qualified"] is False
    assert evidence["eligible_for_summary"] is False


@pytest.mark.parametrize("field", ["has_competing_order", "is_unconventional"])
def test_qualified_false_preserves_source_method_and_detection_window(field):
    prop = _property([_record(**{field: False}, measurement="NMR",
                             detection_conditions={"temperature_min_k": 2, "temperature_max_k": 100, "detection_limit": "stated instrument noise floor"})], field)
    assert prop["status"] == "reported" and prop["value"] is False
    evidence = prop["evidence"][0]
    assert evidence["negative_qualified"] is True
    assert evidence["method"] == "NMR"
    assert evidence["detection_conditions"]["temperature_min_k"] == 2
    assert evidence["paper_id"] == "synthetic:one"


@pytest.mark.parametrize("conditions", ["unknown", "not_reported", [], {}, {"description": "unknown"}, {"temperature_min_k": "unknown"}, {"temperature_min_k": True}, {"temperature_min_k": 100, "temperature_max_k": 2}, {"temperature_min_k": float("nan")}, {"temperature_min_k": -1}])
def test_missing_invalid_or_ambiguous_detection_conditions_do_not_qualify_absence(conditions):
    prop = _property([_record(has_competing_order=False, method="NMR", detection_conditions=conditions)])
    assert prop["status"] == "unknown" and prop["value"] is None
    assert not prop["evidence"][0]["negative_qualified"]


@pytest.mark.parametrize("status", ["unknown", "not_reported", "not_extracted", "not_computed", "failed"])
def test_explicit_missingness_and_processing_statuses_remain_distinct(status):
    prop = _property([_record(has_competing_order_status=status, has_competing_order_reason="Synthetic pipeline declaration")])
    assert prop["status"] == status
    assert prop["value"] is None


def test_not_applicable_requires_a_source_bound_reason_and_is_never_false():
    raw = _record(has_competing_order_status="not_applicable")
    assert _property([raw])["status"] == "unknown"
    raw["has_competing_order_reason"] = "No superconducting state is asserted in this scoped synthetic record."
    prop = _property([raw])
    assert prop["status"] == "not_applicable" and prop["value"] is None
    assert prop["evidence"][0]["status_reason"] == raw["has_competing_order_reason"]
    raw.pop("paper_id")
    assert _property([raw])["status"] == "unknown"


@pytest.mark.parametrize("record", [
    _record(has_competing_order=False, competing_order="CDW"),
    _record(has_competing_order=True, has_competing_order_status="not_reported"),
    _record(pairing_symmetry="d-wave", pairing_symmetry_status="not_applicable"),
])
def test_contradictory_channels_are_extraction_conflicts_not_scientific_disputes(record):
    report = _report([record])
    assert report["conflicts"]["extraction_conflict"]["detected"] is True
    assert report["conflicts"]["scientific_dispute"]["status"] == "not_reported"


def test_family_prior_is_separate_and_never_fills_an_observed_field():
    report = _report([_record()], family="cuprate", legacy_summary={"pairing_symmetry": "d-wave", "is_unconventional": True})
    assert report["properties"]["pairing_symmetry"]["value"] is None
    assert report["properties"]["is_unconventional"]["value"] is None
    assert report["priors"]
    for prior in report["priors"]:
        assert prior["knowledge_origin"] == "Inferred"
        assert prior["applicability"]["universally_applicable"] is False
        assert prior["provenance"]["scientific_citation"] is None
    assert report["scientific_acceptance"] is False


def test_source_report_can_differ_from_legacy_prior_without_being_overwritten():
    report = _report([_record(pairing_symmetry="s-wave")], family="cuprate", legacy_summary={"pairing_symmetry": "d-wave"})
    prop = report["properties"]["pairing_symmetry"]
    assert prop["status"] == "reported" and prop["value"] == "s-wave"
    assert "legacy_summary_not_source_supported" in prop["reason_codes"]
    assert report["priors"][0]["value"] == "d-wave"


@pytest.mark.parametrize("length", [100, 101, 161])
def test_pairing_storage_boundary_never_truncates_or_mutates_raw_report(length):
    raw = _record(pairing_symmetry="s" * length)
    original = deepcopy(raw)
    prop = _property([raw], "pairing_symmetry", source_statuses={"synthetic:one": "active"})
    assert raw == original
    if length == 100:
        assert prop["status"] == "reported"
        assert prop["value"] == raw["pairing_symmetry"]
    else:
        assert prop["status"] == "unknown" and prop["value"] is None
        assert prop["evidence"][0]["value"] is None
        assert "pairing_symmetry_value_exceeds_storage_limit" in prop["evidence"][0]["reason_codes"]


def test_explicit_record_inference_stays_labeled_and_family_default_is_ineligible():
    prop = _property([_record(is_unconventional=True, knowledge_origin="Inferred")], "is_unconventional")
    assert prop["status"] == "reported"
    assert prop["evidence"][0]["knowledge_origin"] == "Inferred"
    prior = _property([_record(is_unconventional=True, is_unconventional_basis="family_prior")], "is_unconventional")
    assert prior["status"] == "unknown" and prior["value"] is None


def test_distinct_known_states_create_variability_without_majority_voting():
    records = [_record(pairing_symmetry="d-wave", sample_id="sample:a")] * 8 + [_record(pairing_symmetry="s-wave", sample_id="sample:b")]
    report = _report(records)
    assert report["properties"]["pairing_symmetry"]["status"] == "unknown"
    assert report["properties"]["pairing_symmetry"]["value"] is None
    assert report["conflicts"]["state_variability"]["detected"] is True
    assert report["conflicts"]["extraction_conflict"]["detected"] is False
    assert report["conflicts"]["scientific_dispute"]["status"] == "not_reported"
    assert report == _report(list(reversed(records)))


def test_unknown_state_alternatives_are_not_asserted_to_be_distinct_states():
    report = _report([{"paper_id": "synthetic:a", "pairing_symmetry": "s-wave"},
                      {"paper_id": "synthetic:b", "pairing_symmetry": "d-wave"}])
    assert report["properties"]["pairing_symmetry"]["status"] == "unknown"
    assert report["conflicts"]["state_variability"]["detected"] is False
    assert report["conflicts"]["scientific_dispute"]["status"] == "not_reported"


def test_same_supplied_result_revision_with_incompatible_values_is_extraction_conflict():
    report = _report([_record(result_id="result:one", result_revision=1, pairing_symmetry="d-wave"),
                      _record(result_id="result:one", result_revision=1, pairing_symmetry="s-wave")])
    assert report["properties"]["pairing_symmetry"]["status"] == "conflicted"
    assert report["conflicts"]["extraction_conflict"]["detected"] is True
    assert report["conflicts"]["scientific_dispute"]["status"] == "not_reported"


@pytest.mark.parametrize("condition", [
    {"sample_id": "sample:b"}, {"state_id": "state:b"}, {"pressure_gpa": 3}, {"doping_level": 0.2},
])
def test_tc_variation_with_explicit_different_context_is_only_a_variability_diagnostic(condition):
    left = _record(tc_kelvin=10, pressure_gpa=2, state_id="state:a", doping_level=0.1)
    right = {**left, "tc_kelvin": 20, **condition}
    report = _report([left, right])
    assert "tc_kelvin" not in report["properties"]
    assert "tc_kelvin" in report["conflicts"]["state_variability"]["properties"]
    assert report["conflicts"]["scientific_dispute"]["status"] == "not_reported"
    assert report["conflicts"]["extraction_conflict"]["detected"] is False


@pytest.mark.parametrize("records", [
    [_record(tc_kelvin=1), _record(tc_kelvin=400)],
    [{"tc_kelvin": 1}, {"tc_kelvin": 400}],
    [_record(tc_kelvin=10, pressure_gpa=2), _record(tc_kelvin="<20 K", pressure_gpa=3)],
])
def test_tc_spread_alone_and_unresolved_point_values_never_establish_a_dispute(records):
    report = _report(records)
    assert not report["conflicts"]["state_variability"]["detected"]
    assert not report["conflicts"]["extraction_conflict"]["detected"]
    assert report["conflicts"]["scientific_dispute"]["status"] == "not_reported"


def test_explicit_dispute_markers_remain_unadjudicated_and_manual_legacy_hold_is_retained():
    report = _report([_record(disputed=True)], legacy_summary={"disputed": True})
    dispute = report["conflicts"]["scientific_dispute"]
    assert dispute["status"] == "reported_unadjudicated" and dispute["count"] == 2
    assert dispute["scientific_acceptance"] is False
    assert any(item["reason_codes"] == ["legacy_governance_dispute_flag"] for item in dispute["evidence"])


@pytest.mark.parametrize("statuses", [{}, {"synthetic:one": None}, {"synthetic:one": "unknown"}, {"synthetic:one": "retracted"}, {"synthetic:one": "corrected"}, {"synthetic:one": {"status": "active"}}, []])
def test_supplied_unknown_invalid_or_held_source_statuses_lower_summary_eligibility(statuses):
    prop = _property([_record(has_competing_order=True)], source_statuses=statuses)
    assert prop["status"] == "unknown" and prop["value"] is None


def test_ingestion_unknown_source_status_is_disclosed_and_api_can_check_active_source():
    raw = [_record(has_competing_order=True)]
    unchecked = _report(raw)
    checked = _report(raw, source_statuses={"synthetic:one": "published"})
    assert unchecked["properties"]["has_competing_order"]["status"] == "reported"
    assert "current_source_status_not_checked" in unchecked["warnings"]
    assert checked["properties"]["has_competing_order"]["status"] == "reported"
    assert checked["properties"]["has_competing_order"]["evidence"][0]["source_status"] == "active"


def test_derived_envelopes_cannot_forge_values_or_remove_holds():
    record = _record(needs_review=True, has_competing_order=True,
        visibility={"public_catalogue_eligible": True}, material_semantics={"properties": {"has_competing_order": {"status": "reported", "value": True}}})
    report = _report([record])
    assert report["properties"]["has_competing_order"]["value"] is None
    forged_only = _property([_record(material_semantics=record["material_semantics"])])
    assert forged_only["value"] is None


def test_source_and_extraction_confidence_do_not_count_as_independent_replication():
    records = [_record(root_work_id="work:one", sample_id="sample:1", confidence=0.99),
               _record(paper_id="journal:one", doi="10.synthetic/one", root_work_id="work:one", sample_id="sample:2"),
               _record(root_work_id="work:one", sample_id="sample:1", confidence=0.99)]
    report = _report(records, legacy_summary={"total_papers": 9})
    support = report["support"]
    assert support["occurrence_count"] == 3 and support["distinct_occurrence_count"] == 2
    assert support["bibliographic_identifier_count"] == 3
    assert support["independent_work_count"] is None and support["independent_replication_count"] is None
    assert support["legacy_total_papers"] == 9
    assert support["legacy_total_papers_matches_identifier_count"] is False
    assert support["identity_adjudicated"] is False


def test_reported_summary_keeps_an_inspectable_contributor_despite_unknown_evidence_limit():
    records = [_record(paper_id=f"synthetic:{i}") for i in range(MAX_EVIDENCE + 5)]
    records.append(_record(paper_id="synthetic:positive", has_competing_order=True))
    prop = _property(records)
    assert prop["status"] == "reported" and prop["value"] is True
    assert prop["evidence_truncated"] is True
    assert len(prop["evidence"]) == MAX_EVIDENCE
    assert prop["evidence"][0]["paper_id"] == "synthetic:positive"
    assert prop["evidence"][0]["eligible_for_summary"] is True


def test_private_structured_metadata_is_not_copied_to_public_projection():
    raw = _record(has_competing_order=True, reviewer_email="PRIVATE", admin_decision={"note": "PRIVATE"},
                  source_locator={"table": "I", "reviewer_email": "PRIVATE"},
                  detection_conditions={"temperature_min_k": 2, "reviewer": {"email": "PRIVATE"}})
    before = deepcopy(raw)
    report = _report([raw])
    assert "PRIVATE" not in json.dumps(report)
    assert raw == before


def test_limit_or_malformed_record_is_explicit_and_never_approves_partial_summary():
    report = _report([_record(has_competing_order=True)] * (MAX_RECORDS + 1))
    assert report["properties"]["has_competing_order"]["status"] == "unknown"
    assert "assessment_incomplete" in report["warnings"]
    assert report["support"]["assessment_complete"] is False
    malformed = _report([_record(has_competing_order=True), None])
    assert malformed["properties"]["has_competing_order"]["value"] is None
    assert malformed["support"]["invalid_occurrence_count"] == 1


def test_public_projection_is_json_safe_for_nonfinite_unrelated_numeric_inputs():
    report = _report([_record(has_competing_order=True, tc_kelvin=float("nan"))])
    json.dumps(report, allow_nan=False)
    assert report["conflicts"]["scientific_dispute"]["status"] == "not_reported"


def test_generic_declared_property_conflict_does_not_invent_its_scientific_or_extraction_cause():
    report = _report([_record(pairing_symmetry_status="conflicted", pairing_symmetry_reason="The reported interpretation is unresolved.")])
    assert report["properties"]["pairing_symmetry"]["status"] == "conflicted"
    assert report["properties"]["pairing_symmetry"]["value"] is None
    assert not report["conflicts"]["extraction_conflict"]["detected"]
    assert report["conflicts"]["scientific_dispute"]["status"] == "not_reported"


@pytest.mark.parametrize("change", [{"source_status": {"bad": "shape"}}, {"source_status": "unrecognized-status"}, {"review_reason": []}])
def test_malformed_source_and_governance_metadata_cannot_support_a_reported_property(change):
    prop = _property([_record(has_competing_order=True, **change)])
    assert prop["status"] == "unknown" and prop["value"] is None


def test_private_decision_annotations_do_not_create_new_occurrence_identities():
    plain = _record(has_competing_order=True)
    annotated = {**plain, "admin_decision": {"reviewer": "private"}, "reviewed_at": "2026-09-07"}
    assert _report([plain]) == _report([annotated])
