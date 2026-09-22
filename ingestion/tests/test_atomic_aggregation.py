"""SC02 atomic catalogue selections; no database or model calls."""
from __future__ import annotations

import copy
from itertools import permutations

from ingestion.extract.materials_aggregator import _derive_summary, _OverrideEntry
from ingestion.property_evidence import build_property_evidence


def record(paper, **fields):
    return {"paper_id": paper, "formula": "MgB2", "year": 2024,
            "tc_kelvin": 39.0, "measurement": "resistivity",
            "evidence_type": "primary_experimental", **fields}


def test_maximum_hc2_conditions_come_from_the_same_result():
    rows = [record("a", hc2_tesla=20.0, hc2_conditions="along c at 5 K"),
            record("b", hc2_tesla=100.0, hc2_conditions="along ab at 0 K")]
    result = _derive_summary("MgB2", rows)
    assert result["hc2_tesla"] == 100.0
    assert result["hc2_conditions"] == "along ab at 0 K"


def test_missing_hc2_conditions_never_borrow_a_different_measurement():
    rows = [record("a", hc2_tesla=20.0, hc2_conditions="along c at 5 K"),
            record("b", hc2_tesla=100.0)]
    assert _derive_summary("MgB2", rows)["hc2_conditions"] is None


def test_lattice_remains_one_record_while_text_structure_aliases_wait_for_relation_review():
    rows = [record("a", year=2010, lattice_a=3.0, crystal_structure="hexagonal", space_group="P6/mmm"),
            record("b", year=2001, lattice_a=4.0, lattice_c=7.0,
                   crystal_structure="tetragonal", space_group="P4/mmm")]
    selected = []
    for ordered in permutations(rows):
        result = _derive_summary("MgB2", list(ordered))
        selected.append((result["lattice_params"], result["crystal_structure"], result["space_group"]))
    assert selected[0] == selected[1]
    assert selected[0] in [({"a": 3.0}, None, None),
                          ({"a": 4.0, "c": 7.0}, None, None)]
    assert rows[0]["space_group"] == "P6/mmm"  # Raw text is retained.


def test_tied_hc2_provenance_and_conditions_are_order_invariant():
    rows = [record("a", hc2_tesla=20.0, hc2_conditions="along c at 5 K"),
            record("b", hc2_tesla=20.0, hc2_conditions="along ab at 0 K")]
    summaries = [_derive_summary("MgB2", list(ordered)) for ordered in permutations(rows)]
    assert summaries[0]["hc2_conditions"] == summaries[1]["hc2_conditions"]


def test_tied_tc_conditions_keep_deterministic_source_provenance():
    rows = [record("a", sample_form="single_crystal"), record("b", sample_form="thin_film")]
    summaries = [_derive_summary("MgB2", list(ordered)) for ordered in permutations(rows)]
    assert summaries[0]["tc_max_conditions"] == summaries[1]["tc_max_conditions"]


def test_hc2_reference_withholds_unreviewed_value_without_manufacturing_cap():
    rows = [record("a", hc2_tesla=100.0, hc2_conditions="along ab at 0 K")]
    result = _derive_summary("MgB2", rows, overrides=[
        _OverrideEntry("hc2_tesla", "50", True, "legacy cap", None)])
    assert result["hc2_tesla"] is None
    assert result["hc2_conditions"] is None
    bundle = build_property_evidence(result["records"], scope_id="mat:MgB2", legacy_summary=result)
    assert bundle["properties"]["hc2_tesla"]["selected"] is None
    assert result["records"] == rows


def test_legacy_cap_does_not_gain_a_fabricated_source_or_revive_uncapped_value():
    raw = [record("a", tc_kelvin=60.0)]
    before = copy.deepcopy(raw)
    summary = _derive_summary("MgB2", raw, overrides=[
        _OverrideEntry("tc_max", "45", True, "legacy cap", None)])
    assert summary["tc_max"] is None
    bundle = build_property_evidence(summary["records"], scope_id="mat:MgB2", legacy_summary=summary)
    assert bundle["properties"]["tc_max"]["selected"] is None
    assert raw == before


def test_different_run_epc_maxima_are_not_joint_inputs_and_median_is_not_an_observation():
    rows = [record("a", lambda_eph=3.0, omega_log_k=500.0, rho_exponent=1.0,
                   state_id="state-a", structure_id="structure-a", run_id="run-a"),
            record("b", lambda_eph=1.0, omega_log_k=1000.0, rho_exponent=3.0,
                   state_id="state-b", structure_id="structure-b", run_id="run-b")]
    before = copy.deepcopy(rows)
    summary = _derive_summary("MgB2", rows)
    assert summary["lambda_eph"] == 3.0 and summary["omega_log_k"] == 1000.0
    assert summary["rho_exponent"] == 2.0  # retained catalogue median, no synthetic source
    bundle = build_property_evidence(summary["records"], scope_id="mat:MgB2", legacy_summary=summary)
    assert bundle["not_joint_observation"] is True
    assert bundle["properties"]["rho_exponent"]["selected"] is None
    assert bundle["properties"]["rho_exponent"]["status"] == "untraceable"
    assert bundle["joint_epc"]["status"] != "eligible"
    assert rows == before


def test_exact_structure_override_cannot_bypass_pending_relation_policy():
    rows = [record("a", lattice_a=3.0, lattice_c=7.0,
                   crystal_structure="tetragonal", space_group="P4/mmm")]
    summary = _derive_summary("MgB2", rows, overrides=[
        _OverrideEntry("space_group", '"P1"', False, "legacy curator text", None)])
    assert summary["space_group"] is None
    bundle = build_property_evidence(summary["records"], scope_id="mat:MgB2", legacy_summary=summary)
    assert bundle["properties"]["space_group"]["selected"] is None
    assert rows[0]["space_group"] == "P4/mmm"
