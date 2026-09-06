"""Read-only, local JSONL anomaly rule impact reports."""
import importlib.util
import json
import socket
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/audit_anomaly_aggregation.py"
SPEC = importlib.util.spec_from_file_location("anomaly_impact", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def sample():
    return {"id": "mat:MgB2", "formula": "MgB2", "records": [
        {"paper_id": "synthetic:a", "tc_kelvin": 60, "measurement": "resistivity"}],
        "legacy_summary": {"tc_max": 45},
        "overrides": [{"field": "tc_max", "value": 45, "is_cap": True}]}


def test_cap_counterexample_report_keeps_raw_and_withholds_synthetic_value(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("No socket or database session is allowed")
    monkeypatch.setattr(socket, "socket", forbidden)
    from ingestion.extract import materials_aggregator
    monkeypatch.setattr(materials_aggregator, "_session_factory", forbidden)
    row = sample()
    original = deepcopy(row)
    report = AUDIT.audit_rows([row], current_year=2026)
    assert report["counts"]["value_changes"] == 1
    assert report["counts"]["proposed_raw_records_retained"] == 1
    change = report["samples"][0]["property_changes"][0]
    assert change["old_value"] == 45 and change["proposed_value"] is None
    assert change["proposed_result_id"] is None
    assert report["database_connections"] == report["database_rewrites"] == 0
    assert row == original


def test_legacy_numeric_drop_and_new_review_and_low_temperature_are_separate():
    row = sample()
    row["records"] = [{"paper_id": "a", "tc_kelvin": 400, "measurement": "resistivity"},
                      {"paper_id": "b", "tc_kelvin": 0.001, "measurement": "resistivity"}]
    row["legacy_summary"] = {}
    row["overrides"] = []
    report = AUDIT.audit_rows([row], current_year=2026)
    assert report["counts"]["legacy_dropped_before_grouping"] == 2
    assert report["counts"]["proposed_review_required"] == 1
    assert report["counts"]["proposed_no_findings"] == 1
    assert report["counts"]["fields_not_comparable"] == len(AUDIT.FIELDS)
    assert "value_changes" not in report["counts"]


def test_legacy_all_bad_fallback_is_not_mislabeled_as_deletion():
    dispositions = AUDIT._legacy_numeric_dispositions([{"tc_kelvin": 290}], [])
    assert dispositions[0]["status"] == "retained_all_flagged_fallback"
    dispositions = AUDIT._legacy_numeric_dispositions([{"tc_kelvin": 290}, {"tc_kelvin": 39}], [])
    assert dispositions[0]["status"] == "dropped_from_material_records"


def test_report_is_deterministic_and_does_not_leak_arbitrary_nested_old_metadata():
    row = sample()
    row["legacy_summary"]["property_evidence"] = {"properties": {"tc_max": {"selected": {
        "result_id": "old-result", "conditions": {"private_token": "SECRET-NEVER-EXPORTED",
        "measurement": {"nested_secret": "SECRET-NEVER-EXPORTED"}}}}}}
    first = AUDIT.audit_rows([row], current_year=2026)
    assert first == AUDIT.audit_rows([row], current_year=2026)
    assert "SECRET-NEVER-EXPORTED" not in json.dumps(first)
    assert first["counts"]["provenance_changed"] == 1


def test_cli_reads_without_rewriting_and_hashes_input(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text(json.dumps(sample()) + "\n")
    before = snapshot.read_bytes()
    completed = subprocess.run([sys.executable, str(SCRIPT), str(snapshot), "--current-year", "2026"], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert snapshot.read_bytes() == before
    assert len(report["input_sha256"]) == len(report["report_sha256"]) == 64
    assert report["joint_epc"] == "not_evaluated"


@pytest.mark.parametrize("reference", [
    {"field": "tc_max", "value": "NaN", "is_cap": True},
    {"field": "tc_max", "value": 45, "is_cap": "false"},
    {"field": "unknown", "value": 45, "is_cap": True},
])
def test_malformed_context_is_rejected_not_silently_ignored(reference):
    row = sample()
    row["overrides"] = [reference]
    with pytest.raises(ValueError): AUDIT.audit_rows([row], current_year=2026)
