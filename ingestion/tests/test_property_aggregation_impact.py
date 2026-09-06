"""Offline impact reports distinguish value, source and condition changes."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ingestion.property_evidence import build_property_evidence

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/audit_property_aggregation.py"
SPEC = importlib.util.spec_from_file_location("property_aggregation_impact", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def sample():
    return {"id": "mat:synthetic-hc2", "formula": "MgB2", "hc2_tesla": 100.0,
            "hc2_conditions": "along c at 5 K", "records": [
                {"paper_id": "synthetic:a", "hc2_tesla": 20.0, "hc2_conditions": "along c at 5 K"},
                {"paper_id": "synthetic:b", "hc2_tesla": 100.0, "hc2_conditions": "along ab at 0 K"},
            ]}


def field(report, name):
    return next(row for row in report["samples"][0]["properties"] if row["property"] == name)


def test_impact_separates_added_source_from_changed_conditions_without_value_change(monkeypatch):
    material = sample()
    original = copy.deepcopy(material)
    def no_network(*args, **kwargs):
        raise AssertionError("Offline impact audit must not open a socket")
    monkeypatch.setattr(socket, "socket", no_network)
    report = AUDIT.build_impact_report([material])
    hc2 = field(report, "hc2_tesla")
    assert hc2["supported_value_changes"] is False
    assert hc2["provenance_change"] == "added"
    assert hc2["conditions_changed_fields"] == ["hc2_conditions"]
    assert report["stored_values_rewritten"] == 0
    assert report["scientific_acceptance_implied"] is False
    assert material == original


def test_unknown_legacy_summary_is_not_claimed_as_zero_impact():
    material = {"id": "source-only", "formula": "MgB2", "records": sample()["records"]}
    change = field(AUDIT.build_impact_report([material]), "hc2_tesla")
    assert change["supported_value_changes"] is None
    assert change["comparison_status"] == "legacy_summary_field_missing"
    assert change["proposed_source_supported_value"] is None


def test_capped_value_is_withheld_in_supported_view_without_selecting_raw_high_value():
    report = AUDIT.build_impact_report([{"id": "capped", "tc_max": 45.0, "records": [
        {"paper_id": "synthetic:cap", "tc_kelvin": 60.0, "measurement": "resistivity"},
    ]}])
    change = field(report, "tc_max")
    assert change["status"] == "untraceable"
    assert change["legacy_catalogue_value"] == 45.0
    assert change["proposed_source_supported_value"] is None
    assert change["supported_value_changes"] is True


def test_actual_prior_provenance_is_compared_instead_of_always_called_added():
    material = sample()
    material["property_evidence"] = build_property_evidence(
        material["records"], scope_id=material["id"], legacy_summary={"hc2_tesla": 20.0})
    change = field(AUDIT.build_impact_report([material]), "hc2_tesla")
    assert change["provenance_change"] == "changed"
    assert change["old_result_id"] != change["proposed_result_id"]


def test_state_and_structure_only_changes_are_reported_independently():
    material = sample()
    material["hc2_conditions"] = "along ab at 0 K"
    prior = build_property_evidence(material["records"], scope_id=material["id"], legacy_summary=material)
    selected = prior["properties"]["hc2_tesla"]["selected"]
    selected["state"]["state_id"] = "old-state"
    selected["state"]["pressure_semantics"]["pressure_gpa"] = 15.0
    selected["structure"]["space_group"] = "old-space-group"
    material["property_evidence"] = prior
    report = AUDIT.build_impact_report([material])
    change = field(report, "hc2_tesla")
    assert change["supported_value_changes"] is False
    assert change["provenance_change"] == "unchanged"
    assert change["conditions_changed_fields"] == []
    assert change["state_changed_fields"] == ["pressure_semantics", "state_id"]
    assert change["structure_changed_fields"] == ["space_group"]
    assert report["totals"]["state_changed"] >= 1
    assert report["totals"]["structure_changed"] >= 1


def test_state_formula_and_pressure_policy_changes_are_not_lost_by_audit_allowlist():
    material = sample()
    prior = build_property_evidence(material["records"], scope_id=material["id"], legacy_summary=material)
    selected = prior["properties"]["hc2_tesla"]["selected"]
    selected["state"]["formula"] = "Old composition"
    selected["state"]["pressure_semantics"]["classifier_version"] = "old-pressure-policy"
    material["property_evidence"] = prior
    change = field(AUDIT.build_impact_report([material]), "hc2_tesla")
    assert change["state_changed_fields"] == ["formula", "pressure_semantics"]
    assert change["proposed_state"]["formula"] is None  # No borrowing from material.formula.


def test_old_tc_flat_conditions_are_compared_with_result_conditions():
    material = {"id": "tc-conditions", "tc_max": 39.0, "tc_max_conditions": "old catalogue context",
                "records": [{"paper_id": "synthetic:tc", "tc_kelvin": 39.0,
                             "tc_conditions": "reported source context"}]}
    change = field(AUDIT.build_impact_report([material]), "tc_max")
    assert change["old_conditions"]["tc_conditions"] == "old catalogue context"
    assert change["conditions_changed_fields"] == ["tc_conditions"]


def test_prior_envelope_and_nonstandard_lattice_cannot_leak_nested_private_metadata():
    material = sample()
    material["lattice_params"] = {"a": 3.0, "private_config": {"password": "SYNTHETIC_SECRET"}}
    material["property_evidence"] = {"properties": {"hc2_tesla": {"selected": {
        "result_id": {"private": "SYNTHETIC_SECRET"},
        "conditions": {"internal_metadata": {"token": "SYNTHETIC_SECRET"},
                       "measurement_method": {"token": "SYNTHETIC_SECRET"}},
        "state": {"internal": "SYNTHETIC_SECRET", "pressure_semantics": {
            "internal": "SYNTHETIC_SECRET", "raw_value": {"key": "SYNTHETIC_SECRET"}}},
        "structure": {"internal": "SYNTHETIC_SECRET", "lattice_params": {
            "a": {"token": "SYNTHETIC_SECRET"}, "private": "SYNTHETIC_SECRET"}},
    }}}}
    report = AUDIT.build_impact_report([material])
    serialized = json.dumps(report)
    assert "SYNTHETIC_SECRET" not in serialized
    assert "internal_metadata" not in serialized
    assert "private_config" not in serialized
    assert "unsupported_or_oversize_value" in serialized
    assert field(report, "hc2_tesla")["old_result_id"] is None


def test_material_and_record_reordering_produces_same_report():
    first = sample()
    second = {**sample(), "id": "mat:second"}
    before = AUDIT.build_impact_report([first, second], sample_limit=1)
    after = AUDIT.build_impact_report([
        {**second, "records": list(reversed(second["records"]))},
        {**first, "records": list(reversed(first["records"]))},
    ], sample_limit=1)
    assert before == after
    assert len(before["samples"]) == 1
    assert before["totals"]["materials_evaluated"] == 2


def test_input_contract_rejects_duplicate_ids_and_nonobject_records():
    with pytest.raises(ValueError, match="unique"):
        AUDIT.build_impact_report([sample(), sample()])
    with pytest.raises(TypeError, match="list of objects"):
        AUDIT.build_impact_report([{"id": "bad", "records": [42]}])


def test_cli_reads_local_fixture_leaves_input_bytes_unchanged_and_emits_hashed_report(tmp_path):
    path = tmp_path / "synthetic.jsonl"
    path.write_text(json.dumps(sample()) + "\n")
    before = path.read_bytes()
    result = subprocess.run([sys.executable, str(SCRIPT), str(path)], check=True,
                            capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["input_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["report_sha256"] == AUDIT._report_hash(report)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    assert not result.stderr
