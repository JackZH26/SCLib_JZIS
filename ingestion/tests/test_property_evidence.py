"""Atomic property projection regressions; no database, cloud or model access."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ingestion import property_evidence as engine
from ingestion.extract.scientific_values import parse_scientific_value
from ingestion.property_evidence import (
    EVIDENCE_LIMIT,
    PROPERTY_FIELDS,
    build_property_evidence,
    legacy_result_id,
)


def build(records, legacy=None, **kwargs):
    return build_property_evidence(records, scope_id="mat:synthetic", legacy_summary=legacy, **kwargs)


def selected(bundle, field):
    return bundle["properties"][field]["selected"]


def computed(**overrides):
    return {
        "formula": "H3S", "paper_id": "synthetic:one", "knowledge_origin": "Computed",
        "source_role": "primary", "method": "DFPT", "protocol_id": "protocol:pbe",
        "state_id": "state:150gpa", "structure_id": "structure:im3m",
        "run_id": "run:1", "pressure_gpa": "150 GPa", **overrides,
    }


def test_hc2_maximum_keeps_same_result_direction_temperature_method_and_source():
    a = {"hc2_tesla": 20, "hc2_conditions": "H || c; T = 5 K", "hc2_direction": "c",
         "hc2_temperature_k": 5, "measurement": "resistivity", "paper_id": "synthetic:a"}
    b = {"hc2_tesla": "100 T", "hc2_conditions": "H || ab; T = 0 K", "hc2_direction": "ab",
         "hc2_temperature_k": 0, "measurement": "resistivity", "paper_id": "synthetic:b"}
    result = build([a, b], {"hc2_tesla": 100, "hc2_conditions": a["hc2_conditions"]})
    choice = selected(result, "hc2_tesla")
    assert choice["value"] == 100
    assert choice["conditions"]["hc2_conditions"] == b["hc2_conditions"]
    assert choice["conditions"]["hc2_direction"] == "ab"
    assert choice["conditions"]["hc2_temperature_k"]["value"] == 0
    assert choice["conditions"]["measurement"] == "resistivity"
    assert choice["source"]["paper_id"] == "synthetic:b"


def test_no_conditions_are_borrowed_from_another_record():
    a = {"hc2_tesla": 20, "hc2_conditions": "along c at 5 K"}
    b = {"hc2_tesla": 100}
    assert selected(build([a, b], {"hc2_tesla": 100}), "hc2_tesla")["conditions"]["hc2_conditions"] is None


def test_reordering_changes_neither_tied_provenance_nor_evidence():
    records = [
        {"hc2_tesla": 100, "paper_id": "synthetic:b", "hc2_conditions": "ab at 0 K"},
        {"hc2_tesla": 100, "paper_id": "synthetic:a", "hc2_conditions": "c at 0 K"},
    ]
    assert build(records, {"hc2_tesla": 100}) == build(list(reversed(records)), {"hc2_tesla": 100})


def test_raw_records_remain_unchanged_and_annotations_do_not_mint_new_identity():
    record = {"tc_kelvin": "39 K", "formula": "MgB2", "source_locator": {"page": 2}}
    original = deepcopy(record)
    identity = legacy_result_id(record, scope_id="mat:synthetic")
    derived = {**record, "result_classification": {}, "pressure_semantics": {}, "property_evidence": {},
               "visibility": {"version": "material-visibility/1.0.0", "state": "pending"}}
    assert legacy_result_id(derived, scope_id="mat:synthetic") == identity
    assert legacy_result_id({**record, "tc_kelvin": 40}, scope_id="mat:synthetic") != identity
    build([record])
    assert record == original


@pytest.mark.parametrize("legacy,expected", [({"tc_max": None}, "not_reported"), ({}, "not_reported"), ({"tc_max": 250}, "untraceable")])
def test_existing_summary_policy_is_not_replaced_by_a_hidden_high_value(legacy, expected):
    result = build([{"tc_kelvin": 310}], legacy)
    assert result["properties"]["tc_max"]["status"] == expected
    assert selected(result, "tc_max") is None
    assert result["properties"]["tc_max"]["evidence"][0]["value"] == 310


def test_censored_and_range_values_remain_browsable_not_scalar_selections():
    for raw in ("<95 K", "80–95 K"):
        result = build([{"tc_kelvin": raw}], {"tc_max": 95})
        prop = result["properties"]["tc_max"]
        assert prop["status"] == "untraceable" and prop["selected"] is None
        assert prop["evidence"][0]["quantity"]["raw_value"] == raw
        assert prop["evidence"][0]["quantity"]["upper"] == 95


def test_stale_normalized_quantities_are_reparsed_and_property_locator_is_used():
    proposal = parse_scientific_value("39 K", "tc_kelvin", source_locator={"page": 7, "private_note": "secret"})
    record = {"tc_kelvin": 300, "source_locator": {"page": 1},
              "scientific_values": {"tc_kelvin": {**proposal, "value": 300}}}
    assert selected(build([record], {"tc_max": 300}), "tc_max") is None
    choice = selected(build([record], {"tc_max": 39}), "tc_max")
    assert choice["value"] == 39 and choice["source"]["source_locator"] == {"page": 7}


def test_typed_missing_raw_cannot_fall_back_to_compatibility_scalar():
    record = {"hc2_tesla": 100, "scientific_values": {"hc2_tesla": {"status": "parsed", "value": 100}}}
    prop = build([record], {"hc2_tesla": 100})["properties"]["hc2_tesla"]
    assert prop["status"] == "untraceable"
    assert prop["evidence"][0]["quantity"]["errors"] == ["missing_raw_proposal"]


def test_tc_splits_and_ambient_choose_matching_result_origin_and_pressure():
    observed = {"tc_kelvin": 39, "knowledge_origin": "Observed", "pressure_condition": "ambient pressure", "paper_id": "synthetic:obs"}
    computed_record = {"tc_kelvin": 39, "knowledge_origin": "Computed", "paper_id": "synthetic:calc"}
    result = build([observed, computed_record], {"tc_max_experimental": 39, "tc_max_theoretical": 39, "tc_ambient": 39})
    assert selected(result, "tc_max_experimental")["source"]["paper_id"] == "synthetic:obs"
    assert selected(result, "tc_max_theoretical")["source"]["paper_id"] == "synthetic:calc"
    assert selected(result, "tc_ambient")["state"]["pressure_semantics"]["pressure_state"] == "explicit_ambient"
    missing = {**observed, "pressure_condition": None, "pressure_gpa": 0, "sample_form": "bulk"}
    assert selected(build([missing], {"tc_ambient": 39}), "tc_ambient") is None


def test_equal_tc_headline_uses_legacy_contributing_origin_pool():
    records = [{"tc_kelvin": 39, "knowledge_origin": "Observed", "paper_id": "synthetic:obs"},
               {"tc_kelvin": 39, "knowledge_origin": "Computed", "paper_id": "synthetic:calc"}]
    result = build(records, {"tc_max": 39, "tc_max_experimental": 39, "tc_max_theoretical": 39})
    assert selected(result, "tc_max")["origin"]["knowledge_origin"] == "Observed"
    result = build(records, {"tc_max": 39, "tc_max_experimental": None, "tc_max_theoretical": 39})
    assert selected(result, "tc_max")["origin"]["knowledge_origin"] == "Computed"
    result = build(records[1:], {"tc_max": 39, "tc_max_experimental": 39})
    assert selected(result, "tc_max") is None
    assert "legacy_origin_pool_untraceable" in result["properties"]["tc_max"]["warnings"]


@pytest.mark.parametrize("marker", [{"result_status": "not_detected"}, {"outcome_state": "inconclusive"}, {"transition_observed": False}])
def test_explicit_nonpositive_outcome_does_not_support_a_tc_headline(marker):
    assert selected(build([{"tc_kelvin": 39, **marker}], {"tc_max": 39}), "tc_max") is None


def test_structure_lattice_cannot_be_assembled_from_different_records():
    records = [
        {"lattice_a": 3, "space_group": "P1", "paper_id": "synthetic:a"},
        {"lattice_c": 9, "space_group": "P2", "paper_id": "synthetic:b"},
    ]
    prop = build(records, {"lattice_params": {"a": 3, "c": 9}})["properties"]["lattice_params"]
    assert prop["status"] == "untraceable" and prop["selected"] is None
    choice = selected(build(records), "lattice_params")
    assert len(choice["value"]) == 1
    assert choice["structure"]["space_group"] in {"P1", "P2"}
    assert choice["structure"]["lattice_params"] == choice["value"]


def test_lattice_supported_subset_does_not_revive_omitted_legacy_component():
    record = {"lattice_a": "0.3 nm", "lattice_c": "9 Å", "space_group": "P1", "crystal_structure": "triclinic"}
    choice = selected(build([record], {"lattice_params": {"a": 3}}), "lattice_params")
    assert choice["value"] == {"a": 3}
    assert choice["structure"]["lattice_params"] == {"a": 3, "c": 9}
    assert choice["structure"]["space_group"] == "P1"


def test_median_is_not_synthesized_into_a_scientific_observation():
    records = [{"rho_exponent": 2}, {"rho_exponent": 4}]
    prop = build(records, {"rho_exponent": 3})["properties"]["rho_exponent"]
    assert prop["status"] == "untraceable" and prop["statistic"] == "catalogue_median"
    prop = build(records, {"rho_exponent": 2})["properties"]["rho_exponent"]
    assert prop["status"] == "supported"
    assert "catalogue_statistic_not_joint_observation" in prop["warnings"]


def test_discrete_prior_without_raw_support_is_not_an_observation():
    result = build([{"formula": "YBCO"}], {"pairing_symmetry": "d-wave", "is_unconventional": True})
    assert result["properties"]["pairing_symmetry"]["status"] == "untraceable"
    assert result["properties"]["is_unconventional"]["status"] == "untraceable"
    assert not {"ambient_sc", "disputed", "retracted"} & set(PROPERTY_FIELDS)


def test_public_projection_is_bounded_and_does_not_dump_nested_private_metadata():
    secret = "sensitive-nested-value"
    record = {"hc2_tesla": 100, "provenance": {"admin": secret},
              "scientific_values": {"hc2_tesla": {"private": secret}},
              "source_locator": {"page": 1, "private": secret}}
    encoded = json.dumps(build([record], {"hc2_tesla": 100}))
    assert secret not in encoded
    records = [{"hc2_tesla": i + 1, "paper_id": f"synthetic:{i}"} for i in range(35)]
    prop = build(records)["properties"]["hc2_tesla"]
    assert len(prop["evidence"]) == EVIDENCE_LIMIT
    assert prop["total_evidence_count"] == 35 and prop["truncated"]
    assert prop["selected"] in prop["evidence"]


def test_epc_same_record_without_state_structure_run_is_still_pending():
    result = build([{"lambda_eph": 3, "omega_log_k": 1000, "knowledge_origin": "Computed", "method": "DFPT"}])
    assert result["joint_epc"]["status"] == "pending"
    assert result["joint_epc"]["selected"] is None


def test_independent_lambda_and_omega_maxima_are_not_an_epc_pair():
    records = [computed(lambda_eph=3, run_id="run:a"), computed(omega_log_k=1000, run_id="run:b")]
    result = build(records)
    assert selected(result, "lambda_eph")["value"] == 3
    assert selected(result, "omega_log_k")["value"] == 1000
    assert result["joint_epc"]["status"] == "pending" and result["joint_epc"]["evaluated_pair_count"] == 0


def test_complete_explicit_epc_association_is_not_physical_applicability():
    records = [computed(lambda_eph=3), computed(omega_log_k=1000)]
    result = build(records)
    pair = result["joint_epc"]["selected"]
    assert result["joint_epc"]["status"] == "eligible"
    assert pair["lambda"]["value"] == 3 and pair["omega_log"]["value"] == 1000
    assert pair["allen_dynes_applicability"] == "not_assessed"
    assert result["not_joint_observation"] is True
    assert build(list(reversed(records))) == result


@pytest.mark.parametrize("left,right", [
    ({"pressure_gpa": "150 GPa"}, {"pressure_gpa": "160 GPa"}),
    ({"sample_form": "bulk"}, {"sample_form": "thin film"}),
    ({"substrate": "STO"}, {"substrate": "MgO"}),
    ({"doping_level": 0.1}, {"doping_level": 0.2}),
    ({"lattice_a": 3}, {"lattice_a": 4}),
    ({"temperature_k": 5}, {"temperature_k": 10}),
    ({"measurement_temperature_k": 5}, {"measurement_temperature_k": 10}),
    ({"space_group": "P1"}, {"space_group": "P2"}),
])
def test_known_conflicting_state_values_veto_joint_epc(left, right):
    result = build([computed(lambda_eph=3, **left), computed(omega_log_k=1000, **right)])
    assert result["joint_epc"]["status"] == "pending"


def test_joint_selection_cannot_bypass_existing_cap_or_null_summary():
    records = [computed(lambda_eph=3, omega_log_k=1000)]
    for legacy in ({"lambda_eph": None, "omega_log_k": None}, {"lambda_eph": 1, "omega_log_k": 100}, {}):
        result = build(records, legacy)
        assert result["joint_epc"]["selected"] is None
        assert result["joint_epc"]["status"] == "pending"


def review_for(records, **extra):
    return {
        "status": "accepted", "review_id": "review:1", "review_revision": "revision:1",
        "state_id": "state:150gpa", "structure_id": "structure:im3m", "protocol_id": "protocol:pbe",
        "result_ids": [legacy_result_id(record, scope_id="mat:synthetic") for record in records],
        **extra,
    }


def test_raw_review_assertion_is_not_trusted_but_external_review_can_resolve_missing_ids():
    raw = {"lambda_eph": 3, "omega_log_k": 1000, "knowledge_origin": "Computed",
           "method": "DFPT", "reviewed": True, "review_status": "accepted"}
    assert build([raw])["joint_epc"]["status"] == "pending"
    result = build([raw], reviewed_epc_matches=[review_for([raw])])
    assert result["joint_epc"]["status"] == "eligible"
    assert result["joint_epc"]["selected"]["association_basis"] == "external_review"


@pytest.mark.parametrize("changed", [{"state_id": "state:other"}, {"structure_id": "structure:other"}, {"protocol_id": "protocol:other"}])
def test_review_cannot_override_candidate_known_identity(changed):
    records = [computed(lambda_eph=3, run_id=None), computed(omega_log_k=1000, run_id=None)]
    result = build(records, reviewed_epc_matches=[review_for(records, **changed)])
    assert result["joint_epc"]["status"] == "pending"


def test_review_cannot_override_calculation_protocol_alias():
    record = computed(lambda_eph=3, omega_log_k=1000, protocol_id=None,
                      calculation_protocol="known:old", run_id=None)
    result = build([record], reviewed_epc_matches=[review_for([record])])
    assert result["joint_epc"]["status"] == "pending"


def test_conflicting_pressure_or_protocol_cannot_be_fixed_by_identity_alone():
    for changes in ({"pressure_condition": "ambient pressure"},
                    {"calculation_protocol": "contradictory:protocol"}):
        record = computed(lambda_eph=3, omega_log_k=1000, **changes)
        assert build([record])["joint_epc"]["status"] == "pending"
        assert build([record], reviewed_epc_matches=[review_for([record])])["joint_epc"]["status"] == "pending"


def test_review_revision_changes_pair_identity_and_malformed_reviews_are_ignored():
    records = [{"lambda_eph": 3, "omega_log_k": 1000, "knowledge_origin": "Computed"}]
    first = build(records, reviewed_epc_matches=[review_for(records)])
    second = build(records, reviewed_epc_matches=[review_for(records, review_revision="revision:2")])
    assert first["joint_epc"]["selected"]["pair_id"] != second["joint_epc"]["selected"]["pair_id"]
    malformed = review_for(records, result_ids=[{"bad": "nested"}])
    assert build(records, reviewed_epc_matches=[malformed])["joint_epc"]["status"] == "pending"


def test_unrelated_epc_states_do_not_generate_a_cartesian_product():
    records = [computed(lambda_eph=2, run_id=f"lambda:{i}") for i in range(100)]
    records.extend(computed(omega_log_k=100, run_id=f"omega:{i}") for i in range(100))
    result = build(records, property_fields=("lambda_eph", "omega_log_k"))
    assert result["joint_epc"]["evaluated_pair_count"] == 0


def test_epc_budget_is_explicit_and_never_reports_incomplete_count_as_exact(monkeypatch):
    monkeypatch.setattr(engine, "EPC_COMPARISON_BUDGET", 3)
    records = [computed(lambda_eph=i + 1) for i in range(2)]
    records.extend(computed(omega_log_k=100 + i) for i in range(2))
    result = build(records)["joint_epc"]
    assert result["evaluated_pair_count"] == 3 and result["truncated"]
    assert result["total_pair_count"] is None and not result["total_pair_count_exact"]
    assert result["total_pair_count_lower_bound"] == 3
    assert result == build(list(reversed(records)))["joint_epc"]


def test_aggregator_can_request_small_projection_without_joint_work():
    result = build([computed(hc2_tesla=100, lambda_eph=3, omega_log_k=1000)],
                   include_joint_epc=False, property_fields=("hc2_tesla", "lattice_params"))
    assert set(result["properties"]) == {"hc2_tesla", "lattice_params"}
    assert result["joint_epc"]["status"] == "not_evaluated"
    assert result["joint_epc"]["evaluated_pair_count"] == 0
    with pytest.raises(ValueError):
        build([], property_fields=("private_provenance",))


def test_independent_deployment_modules_are_byte_identical():
    root = Path(__file__).resolve().parents[2]
    assert (root / "ingestion/ingestion/property_evidence.py").read_bytes() == (
        root / "api/services/property_evidence.py"
    ).read_bytes()


def test_state_composition_notation_is_same_record_not_summary_fallback():
    record = {"hc2_tesla": 100, "formula": "FeSe0.9", "formula_raw": "FeSe₀.₉"}
    choice = selected(build([record], {"hc2_tesla": 100, "formula": "FeSe"}), "hc2_tesla")
    assert choice["state"]["formula"] == "FeSe0.9"
    assert choice["state"]["formula_raw"] == "FeSe₀.₉"
    missing = selected(build([{"hc2_tesla": 100}], {"hc2_tesla": 100, "formula": "FeSe"}), "hc2_tesla")
    assert missing["state"]["formula"] is None
    assert missing["state"]["formula_raw"] is None


def test_composition_notation_is_bounded_and_never_dumps_nested_private_values():
    secret = "private-formula-provenance"
    record = {"hc2_tesla": 100, "formula": "A" * 201, "formula_raw": {"private": secret}}
    result = build([record], {"hc2_tesla": 100})
    choice = selected(result, "hc2_tesla")
    assert choice["state"]["formula"] is None
    assert choice["state"]["formula_raw"] is None
    assert secret not in json.dumps(result)
    assert "A" * 201 not in json.dumps(result)


def test_formula_notation_does_not_establish_or_reject_epc_composition_identity():
    records = [computed(lambda_eph=3, formula="H3S"), computed(omega_log_k=1000, formula="SH3")]
    pair = build(records)["joint_epc"]["selected"]
    assert pair is not None
    assert pair["lambda"]["state"]["formula"] == "H3S"
    assert pair["omega_log"]["state"]["formula"] == "SH3"
