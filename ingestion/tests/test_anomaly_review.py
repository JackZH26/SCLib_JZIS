"""SC03 review-only numeric policy; fixtures do not perform database or cloud I/O."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ingestion.anomaly_review import (
    ANOMALY_POLICY_VERSION,
    PUBLIC_FINDING_LIMIT,
    assess_record_anomalies,
    build_anomaly_review,
    eligible_for_property,
    record_property_quantity,
    rule_registry,
)
from ingestion.property_evidence import (
    ATOMIC_SELECTION_POLICY,
    build_property_evidence,
    legacy_result_id,
)


def assess(record, **kwargs):
    return assess_record_anomalies(record, scope_id="mat:synthetic", **kwargs)


def rules(assessment):
    return {finding["rule_id"] for finding in assessment["findings"]}


def ref(field="tc_max", threshold=45, **extra):
    return {"field": field, "threshold": threshold, "reference_id": "manual_overrides:synthetic", **extra}


def computed(**overrides):
    return {"knowledge_origin": "Computed", "method": "DFPT", "state_id": "s:1",
            "structure_id": "str:1", "run_id": "run:1", "protocol_id": "p:1", **overrides}


def test_sixty_kelvin_plus_forty_five_reference_never_creates_forty_five():
    record = {"tc_kelvin": 60, "hc2_tesla": 100}
    original = deepcopy(record)
    context = {"compound_thresholds": [ref()]}
    review = assess(record, **context)
    assert "legacy_compound_reference_review" in rules(review)
    assert not eligible_for_property(review, "tc_max")
    assert eligible_for_property(review, "hc2_tesla")
    bundle = build_property_evidence([record], scope_id="mat:synthetic",
                                    legacy_summary={"tc_max": 45}, anomaly_context=context)
    prop = bundle["properties"]["tc_max"]
    assert prop["selected"] is None
    assert prop["evidence"][0]["value"] == 60
    assert "anomaly_review_required" in prop["warnings"]
    assert record == original


def test_upper_reference_never_borrows_an_unreported_lower_value():
    records = [{"tc_kelvin": 60}, {"tc_kelvin": 45}]
    bundle = build_property_evidence(records, scope_id="mat:synthetic",
                                    legacy_summary={"tc_max": 45},
                                    anomaly_context={"compound_thresholds": [ref()]})
    assert bundle["properties"]["tc_max"]["selected"]["value"] == 45
    assert bundle["properties"]["tc_max"]["selected"]["quantity"]["raw_value"] == 45


@pytest.mark.parametrize("raw", [0.001, "1e-3 K", "1 mK", "0.000001 K"])
def test_positive_low_tc_has_no_heuristic_lower_floor(raw):
    result = assess({"tc_kelvin": raw})
    assert result["status"] == "no_findings"
    assert eligible_for_property(result, "tc_max")
    assert not result["scientific_acceptance"]


@pytest.mark.parametrize("record", [
    {"tc_kelvin": 300, "pressure_gpa": 200, "knowledge_origin": "Computed"},
    {"tc_kelvin": 300, "pressure_condition": "ambient pressure", "knowledge_origin": "Observed"},
    {"tc_kelvin": 300},
])
def test_broad_reference_explicitly_covers_all_pressures_and_origins(record):
    result = assess(record)
    finding = next(item for item in result["findings"] if item["rule_id"] == "tc_high_review")
    assert finding["category"] == "unusual"
    assert finding["quantity"]["value"] == 300
    assert finding["applicability"]["pressure_scope"] == "all_pressures_including_unknown"
    assert finding["applicability"]["origin_scope"] == "all_origins"
    assert finding["applicability"]["physical_limit"] is False
    assert not eligible_for_property(result, "tc_max")
    assert eligible_for_property(result, "hc2_tesla")


@pytest.mark.parametrize("pressure", [None, 0])
def test_missing_or_unexplained_zero_pressure_does_not_trigger_ambient_reference(pressure):
    result = assess({"tc_kelvin": 160, "knowledge_origin": "Observed", "pressure_gpa": pressure})
    assert "tc_ambient_reference_review" not in rules(result)
    assert "pressure_evidence_conflict" not in rules(result)


def test_ambient_reference_requires_local_explicit_condition_and_observed_origin():
    observed = {"tc_kelvin": 160, "knowledge_origin": "Observed", "pressure_condition": "ambient pressure"}
    result = assess(observed)
    assert "tc_ambient_reference_review" in rules(result)
    assert not eligible_for_property(result, "tc_ambient")
    assert not eligible_for_property(result, "tc_max")
    assert not eligible_for_property(result, "tc_kelvin")
    assert "tc_ambient_reference_review" not in rules(assess({**observed, "knowledge_origin": "Computed"}))


def test_family_reference_is_record_local_and_unknown_family_does_not_get_45k_ceiling():
    assert assess({"tc_kelvin": 60})["status"] == "no_findings"
    assert "tc_family_reference_review" in rules(assess({"tc_kelvin": 60}, family="mgb2"))
    record_family = assess({"tc_kelvin": 60, "family": "iron_based"}, family="mgb2")
    assert "tc_family_reference_review" not in rules(record_family)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "20 kbar", {"private": "secret"}])
def test_numeric_format_invalidity_is_not_unusual_physics(value):
    result = assess({"tc_kelvin": value})
    assert result["status"] == "format_invalid"
    assert "numeric_format_invalid" in rules(result)
    assert not eligible_for_property(result, "tc_max")
    json.dumps(result, allow_nan=False)


def test_units_and_raw_proposals_are_reparsed_before_threshold_comparison():
    assert "pressure_high_review" not in rules(assess({"pressure_gpa": "20 kbar"}))
    assert "pressure_high_review" in rules(assess({"pressure_gpa": "6000 kbar"}))
    record = {"tc_kelvin": 300, "scientific_values": {"tc_kelvin": {
        "raw_value": "39 K", "input_unit": None, "status": "parsed", "value": 300,
    }}}
    assert assess(record)["status"] == "no_findings"


def test_lambda_zero_and_negative_pressure_are_review_not_physical_impossibility():
    result = assess({"lambda_eph": 0, "pressure_gpa": -1})
    assert result["status"] == "review_required"
    assert rules(result) == {"parameter_reference_review", "negative_pressure_protocol_review"}
    assert all(finding["category"] == "unusual" for finding in result["findings"])
    assert eligible_for_property(result, "tc_max")
    assert not eligible_for_property(result, "lambda_eph")


def test_hydride_rule_needs_same_result_and_fully_bounded_low_pressure():
    assert "hydride_low_pressure_high_tc_review" in rules(assess(
        {"family": "hydride", "tc_kelvin": 120, "pressure_gpa": "20–30 GPa"}))
    for pressure in (None, 0, "20–60 GPa", "~20 GPa", ">20 GPa"):
        assert "hydride_low_pressure_high_tc_review" not in rules(assess(
            {"family": "hydride", "tc_kelvin": 120, "pressure_gpa": pressure}))
    split = build_anomaly_review([
        {"family": "hydride", "tc_kelvin": 120, "pressure_gpa": 200},
        {"family": "hydride", "tc_kelvin": 5, "pressure_condition": "ambient pressure"},
    ], scope_id="mat:synthetic")
    assert "hydride_low_pressure_high_tc_review" not in split["rule_counts"]


def test_ambient_override_does_not_apply_to_high_pressure_or_other_views():
    threshold = ref("tc_ambient", 20)
    ambient = assess({"tc_kelvin": 39, "pressure_condition": "ambient pressure", "knowledge_origin": "Observed"},
                     compound_thresholds=[threshold])
    assert not eligible_for_property(ambient, "tc_ambient")
    assert eligible_for_property(ambient, "tc_max")
    high = assess({"tc_kelvin": 39, "pressure_gpa": 20, "knowledge_origin": "Observed"},
                  compound_thresholds=[threshold])
    assert high["status"] == "no_findings"


def test_legacy_exact_numeric_override_always_requires_source_backed_revision():
    reference = ref("hc2_tesla", 20, mode="unreviewed_exact_override")
    for value in (10, 20, 100):
        record = {"hc2_tesla": value}
        result = assess(record, compound_thresholds=[reference])
        assert "legacy_numeric_override_requires_revision" in rules(result)
        assert not eligible_for_property(result, "hc2_tesla")
        assert result["findings"][0]["quantity"]["value"] == value
        assert record["hc2_tesla"] == value


def test_raw_reviewed_or_admin_decision_cannot_self_approve():
    record = {"tc_kelvin": 300, "reviewed": True, "review_status": "accepted",
              "admin_decision": {"rule": "tc_high_review", "accepted": True},
              "anomaly_review": {"status": "no_findings", "review_required_properties": []}}
    assert not eligible_for_property(assess(record), "tc_max")


def test_annotation_never_changes_legacy_sc02_source_identity():
    record = {"tc_kelvin": 300}
    before = legacy_result_id(record, scope_id="mat:synthetic")
    after = legacy_result_id({**record, "anomaly_review": assess(record)}, scope_id="mat:synthetic")
    assert before == after


def test_public_assessments_do_not_dump_private_fields_or_overlong_raw_values():
    secret = "private-source-secret"
    record = {"tc_kelvin": {"private": secret}, "private_notes": secret,
              "scientific_values": {"hc2_tesla": {"raw_value": "A" * 300}}}
    result = assess(record)
    rendered = json.dumps(result)
    assert secret not in rendered and "A" * 300 not in rendered
    assert result["raw_preserved"]
    assert record["private_notes"] == secret


def test_findings_have_stable_complete_review_metadata_and_no_auto_correction():
    record = {"tc_kelvin": 300, "pressure_gpa": 600}
    first = assess(record)
    assert first == assess(deepcopy(record))
    for finding in first["findings"]:
        assert finding["rule_id"] and finding["rule_version"] == ANOMALY_POLICY_VERSION
        assert finding["finding_id"] and finding["applicability"] and finding["reason"]
        assert finding["outcome"] == "pending"
        assert finding["action"] == "retain_raw_and_review"
        assert "corrected_value" not in finding and "replacement" not in finding


def test_parameter_or_lattice_anomaly_only_blocks_its_own_atomic_property():
    record = {"tc_kelvin": 39, "hc2_tesla": "invalid", "lattice_a": 3, "lattice_c": "bad",
              "space_group": "P1", "knowledge_origin": "Observed"}
    result = build_property_evidence([record], scope_id="mat:synthetic")
    assert result["properties"]["tc_max"]["selected"]["value"] == 39
    assert result["properties"]["hc2_tesla"]["selected"] is None
    assert result["properties"]["lattice_params"]["selected"] is None
    crystal = result["properties"]["space_group"]["selected"]
    assert crystal is not None and crystal["structure"]["lattice_params"] is None
    assert crystal["structure"]["lattice_quantities"]["c"]["raw_value"] == "bad"


def test_joint_epc_cannot_bypass_parameter_or_state_anomalies():
    for extra in ({"lambda_eph": 11, "omega_log_k": 1000}, {"lambda_eph": 2, "omega_log_k": 1000, "pressure_gpa": 600}):
        record = computed(**extra)
        result = build_property_evidence([record], scope_id="mat:synthetic")
        assert result["joint_epc"]["selected"] is None
        assert result["joint_epc"]["status"] == "pending"


def test_public_record_and_finding_limits_do_not_make_counts_or_eligibility_inexact():
    refs = [ref("hc2_tesla", i, reference_id=f"manual_overrides:{i}") for i in range(60)]
    record = {"hc2_tesla": 100}
    result = assess(record, compound_thresholds=refs)
    assert result["total_findings"] == 60
    assert len(result["findings"]) == PUBLIC_FINDING_LIMIT
    assert result["findings_truncated"] and not eligible_for_property(result, "hc2_tesla")
    report = build_anomaly_review([record, {"tc_kelvin": 300}], scope_id="mat:synthetic",
                                  compound_thresholds=refs, record_limit=1)
    assert report["total_records"] == 2 and len(report["records"]) == 1
    assert report["records_truncated"] and report["rule_counts"]["legacy_compound_reference_review"] == 60


def test_huge_finite_uncertainty_never_exports_synthetic_infinite_extents():
    result = assess({"tc_kelvin": "1e308 +/- 1e308 K"})
    assert "tc_high_review" in rules(result)
    json.dumps(result, allow_nan=False)
    finding = next(f for f in result["findings"] if f["rule_id"] == "tc_high_review")
    assert finding["quantity"]["upper"] is None
    assert finding["quantity"]["value"] == 1e308


def test_year_policy_keeps_1911_and_uses_only_explicit_current_year():
    assert assess({"year": 1911}, current_year=2026)["status"] == "no_findings"
    assert "record_year_review" in rules(assess({"year": 2028}, current_year=2026))
    assert "record_year_format_invalid" in rules(assess({"year": 2026.5}, current_year=2026))
    assert assess({"year": "1911"}, current_year=2026)["status"] == "no_findings"
    with pytest.raises(ValueError):
        assess({}, current_year=True)
    left, right = assess({"year": 1911}, current_year=2026), assess({"year": 1911}, current_year=2027)
    assert left["result_id"] == right["result_id"]
    assert left["evaluation_year"] == 2026 and right["evaluation_year"] == 2027
    assert assess({})["evaluation_year"] is None
    report = build_anomaly_review([{"year": 1911}], scope_id="mat:synthetic", current_year=2026)
    assert report["evaluation_year"] == report["records"][0]["evaluation_year"] == 2026


def test_no_findings_and_no_raw_record_are_not_scientific_acceptance():
    good = assess({"tc_kelvin": 39})
    malformed = assess(None)
    assert not good["scientific_acceptance"]
    assert malformed["status"] == "format_invalid"
    assert not eligible_for_property(malformed, "hc2_tesla")
    assert not eligible_for_property({"version": "old", "review_required_properties": []}, "tc_max")


def test_registry_is_fresh_and_contains_no_physical_ceiling_or_clamp_instruction():
    first = rule_registry()
    first[0]["description"] = "modified by consumer"
    assert rule_registry()[0]["description"] != first[0]["description"]
    assert all(item["physical_limit"] is False for item in rule_registry())
    assert all(item["action"] == "retain_raw_and_review" for item in rule_registry())


def test_versioned_headline_policy_uses_eligible_observed_pool_after_view_reference():
    records = [{"tc_kelvin": tc, "knowledge_origin": origin} for tc, origin in (
        (39, "Observed"), (30, "Observed"), (30, "Computed"),
    )]
    legacy = {"tc_max": 30, "tc_max_experimental": 39, "tc_max_theoretical": 30}
    context = {"compound_thresholds": [ref("tc_max", 35)], "selection_policy": ATOMIC_SELECTION_POLICY}
    result = build_property_evidence(records, scope_id="mat:synthetic", legacy_summary=legacy,
                                     anomaly_context=context)
    selected = result["properties"]["tc_max"]["selected"]
    assert selected["value"] == 30 and selected["origin"]["knowledge_origin"] == "Observed"
    for policy in (None, "future-or-untrusted-version"):
        old = build_property_evidence(records, scope_id="mat:synthetic", legacy_summary=legacy,
                                      anomaly_context={**context, "selection_policy": policy})
        assert old["properties"]["tc_max"]["selected"] is None
        assert "legacy_origin_pool_untraceable" in old["properties"]["tc_max"]["warnings"]


def test_versioned_headline_policy_ignores_split_only_override_and_ineligible_origin_candidates():
    context = {"selection_policy": ATOMIC_SELECTION_POLICY,
               "compound_thresholds": [ref("tc_max_experimental", 39, mode="unreviewed_exact_override")]}
    records = [{"tc_kelvin": 30, "knowledge_origin": origin} for origin in ("Observed", "Computed")]
    result = build_property_evidence(records, scope_id="mat:synthetic",
        legacy_summary={"tc_max": 30, "tc_max_experimental": None, "tc_max_theoretical": 30}, anomaly_context=context)
    assert result["properties"]["tc_max"]["selected"]["origin"]["knowledge_origin"] == "Observed"
    for observed in ({"tc_kelvin": ">30 K"}, {"tc_kelvin": 39},
                     {"tc_kelvin": 30, "transition_observed": False}):
        result = build_property_evidence([{**observed, "knowledge_origin": "Observed"}, records[1]],
            scope_id="mat:synthetic", legacy_summary={"tc_max": 30, "tc_max_experimental": 39},
            anomaly_context={"selection_policy": ATOMIC_SELECTION_POLICY, "compound_thresholds": [ref("tc_max", 35)]})
        assert result["properties"]["tc_max"]["selected"]["origin"]["knowledge_origin"] == "Computed"


def test_raw_numeric_accessor_supports_aliases_and_same_record_lattice_without_trusting_cached_value():
    record = {"tc": "1 mK", "pressure": "20 kbar", "lattice_params": {"a": "0.4 nm", "c": "bad"},
              "hc2_tesla": 900, "scientific_values": {"hc2_tesla": {"raw_value": "10 T", "value": 900}}}
    original = deepcopy(record)
    assert record_property_quantity(record, "tc_max")["value"] == 0.001
    assert record_property_quantity(record, "tc")["value"] == 0.001
    assert record_property_quantity(record, "pressure")["value"] == 2
    assert record_property_quantity(record, "lattice_a")["value"] == 4
    assert record_property_quantity(record, "lattice_c")["status"] == "invalid"
    assert record_property_quantity(record, "hc2_tesla")["value"] == 10
    assert record == original
    for unsupported in ("lattice_params", "private_field"):
        with pytest.raises(ValueError):
            record_property_quantity(record, unsupported)


def test_property_gate_and_archive_use_same_explicit_year_context():
    record = {"tc_kelvin": 30, "year": 2028}
    result = build_property_evidence([record], scope_id="mat:synthetic",
        anomaly_context={"current_year": 2026})
    candidate = result["properties"]["tc_max"]["evidence"][0]
    assert candidate["anomaly_review"] == assess(record, current_year=2026)
    assert candidate["anomaly_review"]["review_required_properties"] == ["year"]


@pytest.mark.parametrize("record,field", [
    ({"tc_kelvin": 39, "tc": 400}, "tc_max"),
    ({"pressure_gpa": 2, "pressure": "600 GPa"}, "pressure_gpa"),
    ({"lattice_a": 3, "lattice_params": {"a": 4}}, "lattice_params"),
    ({"tc_kelvin": 39, "tc": "~39 K"}, "tc_max"),
    ({"tc_kelvin": 39, "tc": "<39 K"}, "tc_max"),
    ({"tc_kelvin": 39, "tc": "unrecognized notation"}, "tc_max"),
])
def test_coexisting_raw_channels_cannot_shadow_conflicting_or_unresolved_evidence(record, field):
    original = deepcopy(record)
    result = assess(record)
    assert "raw_quantity_conflict" in rules(result)
    assert not eligible_for_property(result, field)
    assert record == original
    bundle = build_property_evidence([record], scope_id="mat:synthetic")
    if field in bundle["properties"]:
        assert bundle["properties"][field]["selected"] is None
        assert "anomaly_review_required" in bundle["properties"][field]["warnings"]


@pytest.mark.parametrize("record", [
    {"tc_kelvin": 0.001, "tc": "1 mK"},
    {"pressure_gpa": 2, "pressure": "20 kbar"},
    {"lattice_a": 3, "lattice_params": {"a": "0.3 nm"}},
    {"tc_kelvin": "39 +/- 1 K", "tc": "39000 +/- 1000 mK"},
])
def test_equivalent_raw_channels_agree_after_unit_conversion(record):
    assert "raw_quantity_conflict" not in rules(assess(record))


def test_typed_raw_supersedes_own_compatibility_scalar_but_not_independent_alias():
    record = {"tc_kelvin": 400, "scientific_values": {"tc_kelvin": {
        "raw_value": "39 +/- 1 K", "value": 999, "status": "invalid",
    }}}
    assert assess(record)["status"] == "no_findings"
    assert "raw_quantity_conflict" not in rules(assess({**record, "tc": "39000 +/- 1000 mK"}))
    conflict = assess({**record, "tc": "30 K"})
    assert "raw_quantity_conflict" in rules(conflict)
    finding = next(item for item in conflict["findings"] if item["rule_id"] == "raw_quantity_conflict")
    assert finding["applicability"]["source_channels"] == ["scientific_values.tc_kelvin.raw_value", "tc"]
    assert finding["quantity"]["raw_value"] == "39 +/- 1 K"


def test_unresolved_reference_target_cannot_bypass_all_known_property_gates():
    unknown = assess({"tc_kelvin": 39}, compound_thresholds=[ref("unknown_field")])
    assert "review_context_unresolved" in rules(unknown)
    assert not eligible_for_property(unknown, "tc_max")
    assert not eligible_for_property(unknown, "hc2_tesla")
    known = assess({"tc_kelvin": 39}, compound_thresholds=[ref("tc_max", "invalid-threshold")])
    assert not eligible_for_property(known, "tc_max")
    assert eligible_for_property(known, "hc2_tesla")


def test_api_and_ingestion_policy_modules_are_byte_identical():
    root = Path(__file__).resolve().parents[2]
    assert (root / "ingestion/ingestion/anomaly_review.py").read_bytes() == (
        root / "api/services/anomaly_review.py").read_bytes()
