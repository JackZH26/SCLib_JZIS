"""Units, source channels and malformed data boundaries for computed gaps."""
import sys
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
from services.material_electronic_references import project_electronic_references as project, valid_electronic_references as valid  # noqa: E402
from services.material_calculation_references import project_calculation_references, _valid_cache  # noqa: E402


def electronic(gaps=None, **group):
    return {"dos_electronic": [{"band_gap": [{"value": 0.0, "index": 0}] if gaps is None else gaps, **group}]}


def test_joule_conversion_keeps_zero_dos_and_band_structure_channels_separate():
    data = electronic([{"value": 0.0, "index": 0}, {"value": 3.204353268e-19, "index": 1}], spin_polarized=True)
    data["band_structure_electronic"] = [{"band_gap": [{"value": 1.602176634e-19, "type": "indirect"}]}]
    result = project(data)
    assert result["status"] == "reported" and valid(result)
    bs, up, down = result["band_gaps"]
    assert bs["value_ev"] == 1 and bs["gap_type"] == "indirect" and bs["spin_channel_index"] is None
    assert up["value_ev"] == 0 and up["value_j"] == 0
    assert down["value_ev"] == 2 and down["value_j"] == 3.204353268e-19
    assert [up["spin_channel_index"], down["spin_channel_index"]] == [0, 1]
    assert bs["source_kind"] != up["source_kind"]
    assert "is_metal" not in result and "gap_structure" not in result


@pytest.mark.parametrize("value", [None, {}, {"dos_electronic": None}, {"dos_electronic": []}, electronic([])])
def test_missing_metadata_is_not_zero(value):
    result = project(value)
    assert result["status"] == "not_supplied" and result["band_gaps"] == [] and valid(result)


@pytest.mark.parametrize("value", [True, False, "0", None, -1, float("nan"), float("inf"), 1e308, 10**1000])
def test_unusable_value_requires_review_without_inventing_a_gap(value):
    result = project(electronic([{"value": value}]))
    assert result["status"] == "requires_review" and result["band_gaps"] == [] and valid(result)


@pytest.mark.parametrize("data", [
    [], {"dos_electronic": {}}, {"dos_electronic": [None]},
    {"dos_electronic": [{"band_gap": {"value": 0}}]},
    {"dos_electronic": [{"band_gap": []}] * 5}, electronic([{"value": 0}] * 3),
    electronic([{"value": 0, "index": True}]), electronic([{"value": 0, "index": -1}]),
    electronic([{"value": 0, "type": "unknown"}]), electronic(spin_polarized=0),
])
def test_malformed_or_oversized_fields_are_not_absence_or_silently_truncated(data):
    result = project(data)
    assert result["status"] == "requires_review" and not result["band_gaps"] and valid(result)


@pytest.mark.parametrize("patch", [{"value_ev": 0}, {"value_ev": True}, {"value_j": "1.602176634e-19"}, {"gap_type": "nodeless"}, {"spin_channel_index": False}, {"source_kind": "superconducting_gap"}, {"group_index": True}, {"source_passage": "not allowed"}])
def test_cache_cannot_change_units_channels_or_meaning(patch):
    result = project(electronic([{"value": 1.602176634e-19}]))
    assert valid(result)
    changed = deepcopy(result)
    changed["band_gaps"][0].update(patch)
    assert not valid(changed)


def test_calculation_projection_keeps_electronic_values_in_their_task_and_cache():
    body = {"data": [{"entry_id": "synthetic", "results": {
        "material": {"chemical_formula_hill": "Al4O6", "chemical_formula_reduced": "Al2O3"},
        "method": {"method_name": "DFT", "simulation": {"program_name": "VASP"}},
        "properties": {"electronic": electronic([{"value": 8.796750808977e-19, "index": 0}], spin_polarized=False)},
    }}], "pagination": {"total": 1}}
    result = project_calculation_references("Al2O3", body, retrieved_at="2026-10-05T00:00:00Z")
    assert _valid_cache(result, "Al2O3", "Al2O3")
    row = result["references"][0]
    assert row["electronic"]["band_gaps"][0]["value_ev"] == pytest.approx(5.4905)
    assert row["sample_identity_established"] is False and row["phase_identity_established"] is False
    row["electronic"]["band_gaps"][0]["value_ev"] = 0
    assert not _valid_cache(result, "Al2O3", "Al2O3")


def test_captured_public_alumina_window_keeps_phase_context_and_missing_values():
    fixtures = Path(__file__).parent / "fixtures"
    raw = (fixtures / "nomad-al2o3-electronic-response.json").read_bytes()
    receipt = json.loads((fixtures / "nomad-al2o3-electronic-receipt.json").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
    result = project_calculation_references("Al2O3", json.loads(raw), retrieved_at=receipt["captured_at_utc"])
    assert _valid_cache(result, "Al2O3", "Al2O3")
    assert result["matches_total"] == 387 and result["inspected_entries"] == 21 and len(result["references"]) == 20
    supplied = [row for row in result["references"] if row["electronic"]["status"] == "reported"]
    assert len(supplied) == 2 and sum(len(row["electronic"]["band_gaps"]) for row in supplied) == 3
    # These electronic results cannot be attached to a corundum host (SG 167).
    assert {row["space_group_number"] for row in supplied} == {61, 163}
    assert all(row["phase_identity_established"] is False for row in supplied)
    assert sum(row["electronic"]["status"] == "not_supplied" for row in result["references"]) == 18
