"""Admission boundaries using real frozen public contracts; private replay opt-in.

Set SCLIB_CANDIDATE_ADMISSION_PILOT_ROOT to the retained qe-pilot directory to
verify all nine genuine captures. This never invokes an engine or network.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import discovery_candidate_admission as admission  # noqa: E402


@pytest.fixture(scope="module")
def refs():
    return admission.retained_pilot_references(ROOT)


def native_request(key):
    return {"kind": "native_calculation", "adapter": "retained_qe_pilot_v1", "reading_sha256": key,
            "quantities": ["total_energy", "scf_error", "scf_iterations"], "bundle": "bundle-v1",
            "capture": "captured-attempt-2-v1", "readback": "read-attempt-2-v1"}


def source(kind="heuristic_prescreen"):
    return {"kind": kind, "labels": {"evidence_level": "DFT-screened", "checker_status": "verified"}}


def blocked(result, reason):
    item = result["evidence"][0]
    assert item["classification"] == "blocked"
    assert item["reason_codes"] == [reason]
    assert item["named_quantities"] == {}
    assert result["authority"] == admission.AUTHORITY


def test_frozen_reference_contains_nine_readings_three_states_not_nine_candidates(refs):
    assert len(refs) == 9
    assert len({v["state"]["structure"]["sha256"] for v in refs.values()}) == 3
    assert {v["state"]["formula"] for v in refs.values()} == {"Mg7AlB16"}
    assert {v["comparison"]["assessment"] for v in refs.values()} == {"sampled_window_outside_tolerance"}


def test_reported_dft_verified_label_does_not_create_calculation(tmp_path):
    original = source()
    result = admission.classify_candidate_evidence(None, original, [], tmp_path)
    assert result["source_classification"] == "heuristic_only"
    assert result["reported_source"] == original
    assert result["reported_source_verified"] is False
    assert result["evidence"] == []
    assert result["authority"] == admission.AUTHORITY
    result["reported_source"]["labels"]["checker_status"] = "changed"
    assert original["labels"]["checker_status"] == "verified"


def test_unknown_source_does_not_infer_heuristic_or_observed(tmp_path):
    result = admission.classify_candidate_evidence(None, source("unknown"), [], tmp_path)
    assert result["source_classification"] == "source_reported_metadata"
    assert result["authority"]["observed_origin_promoted"] is False


@pytest.mark.parametrize("change", ["parent_formula", "sibling_coordinates", "source_pin", "condition", "unknown"])
def test_copied_parent_or_sibling_or_conditions_never_match(refs, tmp_path, change):
    key, ref = next(iter(refs.items()))
    state = deepcopy(ref["state"])
    if change == "parent_formula":
        state["formula"] = state["host_formula"]
    elif change == "sibling_coordinates":
        state["structure"]["sha256"] = "a" * 64
    elif change == "source_pin":
        state["source_pins"][0]["sha256"] = "a" * 64
    elif change == "condition":
        state["conditions"]["pressure_gpa"] = 0
    else:
        state = None
    result = admission.classify_candidate_evidence(state, source(), [native_request(key)], tmp_path)
    blocked(result, "candidate_state_or_source_mismatch")


@pytest.mark.parametrize("quantity", ["Tc", "formation_energy", "energy_above_hull", "carrier_density", "bandwidth", "phonon_stability"])
def test_real_scf_reading_cannot_supply_uncomputed_property(refs, tmp_path, quantity):
    key, ref = next(iter(refs.items()))
    req = native_request(key)
    req["quantities"] = [quantity]
    blocked(admission.classify_candidate_evidence(ref["state"], source(), [req], tmp_path), "unsupported_named_quantity")


@pytest.mark.parametrize("change,reason", [
    ("missing_method", "invalid_shape"), ("unknown_engine", "unsupported_native_reader"),
    ("self_attestation", "invalid_shape"), ("unregistered_hash", "unregistered_native_reading"),
    ("missing_bytes", "artifact_unavailable_or_unsafe"),
])
def test_native_metadata_cannot_substitute_for_bytes_and_matching_reader(refs, tmp_path, change, reason):
    key, ref = next(iter(refs.items()))
    req = native_request(key)
    if change == "missing_method":
        del req["adapter"]
    elif change == "unknown_engine":
        req["adapter"] = "QE7.3.1_legacy"
    elif change == "self_attestation":
        req["validated"] = True
    elif change == "unregistered_hash":
        req["reading_sha256"] = "a" * 64
    blocked(admission.classify_candidate_evidence(ref["state"], source(), [req], tmp_path), reason)


def test_pinned_literature_is_located_source_not_scientific_property(tmp_path):
    raw = b"Source reports Tc=10 K for its sample; conditions require review."
    (tmp_path / "paper.txt").write_bytes(raw)
    req = {"kind": "literature", "artifact": {"path": "paper.txt", "bytes": len(raw), "sha256": admission.digest(raw)},
           "locator": {"start_byte": 15, "end_byte": 22, "sha256": admission.digest(raw[15:22])}}
    r = admission.classify_candidate_evidence(None, source("literature"), [req], tmp_path)
    assert r["evidence"][0]["classification"] == "pinned_literature_passage_requires_review"
    assert r["evidence"][0]["named_quantities"] == {}
    assert r["authority"]["observed_origin_promoted"] is False
    req["locator"]["sha256"] = "a" * 64
    blocked(admission.classify_candidate_evidence(None, source(), [req], tmp_path), "passage_hash_mismatch")


def test_provider_metadata_and_heuristic_source_preserved_separately(tmp_path):
    raw = b'{"provider_Tc":42}'
    (tmp_path / "record.json").write_bytes(raw)
    req = {"kind": "provider_metadata", "artifact": {"path": "record.json", "bytes": len(raw), "sha256": admission.digest(raw)}}
    r = admission.classify_candidate_evidence(None, source(), [req], tmp_path)
    assert r["source_classification"] == "heuristic_only"
    assert r["evidence"][0]["classification"] == "pinned_provider_metadata_requires_review"
    assert r["evidence"][0]["named_quantities"] == {}


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../escape", "a//b", "a\\b"])
def test_paths_cannot_escape_root(tmp_path, path):
    with pytest.raises(admission.AdmissionError, match="invalid_relative_path"):
        admission.Files(tmp_path).read(path)


def test_symlinks_and_nonregular_files_are_rejected(tmp_path):
    (tmp_path / "real").write_bytes(b"data")
    (tmp_path / "link").symlink_to(tmp_path / "real")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dirlink").symlink_to(tmp_path / "dir")
    for path in ["link", "dirlink/inner", "dir"]:
        with pytest.raises(admission.AdmissionError):
            admission.Files(tmp_path).read(path)


def test_same_fd_read_detects_mid_read_change(tmp_path, monkeypatch):
    p = tmp_path / "data"
    p.write_bytes(b"old")
    original = os.read
    changed = False
    def changing_read(fd, maximum):
        nonlocal changed
        if not changed:
            changed = True
            p.write_bytes(b"modified!")
        return original(fd, maximum)
    monkeypatch.setattr(os, "read", changing_read)
    with pytest.raises(admission.AdmissionError, match="artifact_changed_or_size_limit"):
        admission.Files(tmp_path).read("data")


def test_request_limits_and_invalid_json(tmp_path):
    with pytest.raises(admission.AdmissionError, match="evidence_count_limit"):
        admission.classify_candidate_evidence(None, source(), [{}] * 65, tmp_path)
    for raw in [b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}']:
        with pytest.raises(admission.AdmissionError):
            admission.decode(raw)
    (tmp_path / "large").write_bytes(b"abc")
    with pytest.raises(admission.AdmissionError, match="size_limit"):
        admission.Files(tmp_path).read("large", maximum=2)


def test_cli_output_does_not_include_artifact_path_on_failure(tmp_path, capsys):
    (tmp_path / "request.json").write_text(json.dumps({"candidate_identity": None, "reported_source": source(),
        "evidence_requests": [{"kind": "provider_metadata", "artifact": {"path": "private-file", "bytes": 3, "sha256": "a" * 64}}]}))
    assert admission.main(["--request", str(tmp_path / "request.json"), "--artifact-root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "private-file" not in output and str(tmp_path) not in output
    assert json.loads(output)["evidence"][0]["classification"] == "blocked"


@pytest.fixture(scope="module")
def real_pilot():
    raw = os.environ.get("SCLIB_CANDIDATE_ADMISSION_PILOT_ROOT")
    if not raw:
        pytest.skip("Private captured pilot not supplied; no synthetic positive admission.")
    return Path(raw)


def test_all_nine_actual_native_captures_named_outputs_only(real_pilot, refs):
    for key, ref in refs.items():
        r = admission.classify_candidate_evidence(ref["state"], source(), [native_request(key)], real_pilot)
        item = r["evidence"][0]
        assert item["classification"] == "native_candidate_calculation_bytes_verified", item
        assert item["named_quantities"]["total_energy"] == ref["report"]["observations"]["total_energy"]
        assert item["named_quantities"]["scf_iterations"]["value"] == ref["report"]["convergence"]["scf_steps"]
        assert item["basis_sampling_convergence_established"] is False
        assert item["mesh_window_assessment"] == "sampled_window_outside_tolerance"
        assert item["custody"]["native_parser_rerun_by_classifier"] is False
        assert item["custody"]["executed_runner_sha256"].startswith("527a9b")
        assert item["custody"]["runtime_binary_locally_rehashed"] is False
        assert r["reported_source"] == source() and r["authority"] == admission.AUTHORITY


def test_native_tampering_after_capture_is_rejected(real_pilot, refs, tmp_path):
    for directory in ["bundle-v1", "captured-attempt-2-v1", "read-attempt-2-v1"]:
        shutil.copytree(real_pilot / directory, tmp_path / directory)
    key, ref = next(iter(refs.items()))
    receipt_path = tmp_path / "captured-attempt-2-v1/jobs/mgb2-al-minus02-k2/execution-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    native = tmp_path / "captured-attempt-2-v1" / receipt["steps"][1]["xml"]["path"]
    old = native.read_bytes()
    native.write_bytes(old.replace(b"-6.064018619934994", b"-6.064018619934993"))
    assert native.read_bytes() != old
    blocked(admission.classify_candidate_evidence(ref["state"], source(), [native_request(key)], tmp_path), "artifact_hash_mismatch")
    native.write_bytes(old)
    recipe = tmp_path / "read-attempt-2-v1/reader-recipe/frontend/tests/component/discovery-qe-pilot.read.test.tsx"
    recipe.write_bytes((ROOT / "frontend/tests/component/discovery-qe-pilot.read.test.tsx").read_bytes())
    blocked(admission.classify_candidate_evidence(ref["state"], source(), [native_request(key)], tmp_path), "artifact_size_mismatch")
