"""Input integrity tests; synthetic bytes below are not scientific UPFs or results."""

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "build_sclib_m4_calibration.py"
SPEC = importlib.util.spec_from_file_location("m4_calibration", MODULE_PATH)
calibration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calibration)


@pytest.mark.parametrize("path", ["/absolute", "../outside", "nested/../../outside", "a//b", "a/./b", "a\\b", ""])
def test_untrusted_artifact_paths_cannot_escape_or_alias(path):
    with pytest.raises(ValueError, match="normalized relative"):
        calibration.safe_relative(path)


def test_corruption_rejected_even_when_length_unchanged(tmp_path):
    original = b"synthetic input"
    pin = {"path": "input", "sha256": calibration.sha256(original), "bytes": len(original)}
    (tmp_path / "input").write_bytes(b"Synthetic input")
    with pytest.raises(ValueError, match="Pinned artifact changed"):
        calibration.read_pinned(tmp_path, pin)


def test_size_mismatch_rejected_even_with_matching_digest(tmp_path):
    content = b"synthetic"
    (tmp_path / "input").write_bytes(content)
    pin = {"path": "input", "sha256": calibration.sha256(content), "bytes": len(content) + 1}
    with pytest.raises(ValueError, match="Pinned artifact changed"):
        calibration.read_pinned(tmp_path, pin)


@pytest.mark.parametrize("parent_link", [False, True])
def test_symlink_files_and_parents_rejected(tmp_path, parent_link):
    (tmp_path / "real").mkdir()
    (tmp_path / "real/file").write_bytes(b"synthetic")
    (tmp_path / "link").symlink_to(tmp_path / "real" if parent_link else tmp_path / "real/file")
    with pytest.raises(ValueError, match="Symlink artifacts"):
        calibration.read_regular(tmp_path, "link/file" if parent_link else "link")


def test_changed_top_level_manifest_fails_before_creating_bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "bundle-manifest.json").write_text(json.dumps({"jobs": []}))
    with pytest.raises(ValueError, match="Unexpected source bundle manifest"):
        calibration.build(source, tmp_path / "output", tmp_path / "summary.json")
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "summary.json").exists()


def test_existing_output_never_replaced(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "retained").write_bytes(b"retained evidence")
    with pytest.raises(ValueError, match="preparations are immutable"):
        calibration.build(source, output, tmp_path / "summary.json")
    assert (output / "retained").read_bytes() == b"retained evidence"


def test_staged_core_reservations_cover_all_proposed_attempts():
    plan = calibration.protocol()
    for stage in plan["stages"]:
        bound = stage.get("maximum_reserved_core_seconds", stage.get("maximum_additional_reserved_core_seconds"))
        reservation = sum((job["ranks"] or stage["rank_upper_bound"]) * job["wall_seconds"] for job in stage["sequence"])
        assert reservation <= bound
    assert plan["authority"]["full_36_input_campaign_budget"] is None
    assert not plan["authority"]["auto_enqueue"]


def test_historical_electronic_success_does_not_turn_failed_mesh_windows_into_passes():
    history = calibration.protocol()["historical_vps_reference"]
    assert history["electronic_scf_converged"] == history["executions"]
    assert all(value > history["predeclared_tolerance_hartree_per_atom"] for value in history["energy_windows_hartree_per_atom"])
    assert history["finite_mesh_windows_passed"] == 0
