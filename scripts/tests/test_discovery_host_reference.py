"""Real frozen source reconstruction and invalid-source regression tests."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "build_discovery_host_reference.py"
spec = importlib.util.spec_from_file_location("host_reference_builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def captured():
    return (builder.ASSETS / builder.SOURCE_NAME).read_bytes()


def test_all_frozen_records_reconstruct_without_inventing_properties():
    reference = builder.build(captured())
    assert reference == json.loads((builder.ASSETS / builder.OUTPUT_NAME).read_bytes())
    rows = reference["rows"]
    assert len(rows) == 184
    assert len({row["formula"] for row in rows}) == 22
    assert sum(row["plottable"] for row in rows) == 180
    assert {row["id"] for row in rows if not row["plottable"]} == {
        "JVASP-86503", "JVASP-63690", "JVASP-152573", "JVASP-190301"
    }
    assert all("ehull" not in row for row in rows)
    assert any(row["band_gap"]["raw"] == "0.0" for row in rows)
    assert reference["authority"]["catalogue_updates"] == 0
    assert reference["authority"]["stable_host_certified"] is False


@pytest.mark.parametrize("field,value", [
    ("formation_energy_peratom", None), ("formation_energy_peratom", True),
    ("optb88vdw_bandgap", "na"), ("optb88vdw_bandgap", -1),
    ("func", "TBmBJ"), ("formula", "LaH10"), ("typ", "2D"),
])
def test_invalid_source_never_becomes_a_zero_or_another_method(field, value):
    source = json.loads(captured())
    record = json.loads(source["entries"][0]["source_record_json"])
    record[field] = value
    source["entries"][0]["source_record_json"] = json.dumps(record)
    with pytest.raises(ValueError):
        builder.build(json.dumps(source).encode())


def test_an_unrelated_structure_cannot_supply_the_axes():
    source = json.loads(captured())
    record = json.loads(source["entries"][0]["source_record_json"])
    record["atoms"]["elements"][0] = "H"
    source["entries"][0]["source_record_json"] = json.dumps(record)
    with pytest.raises(ValueError, match="composition"):
        builder.build(json.dumps(source).encode())


def test_truncated_or_reordered_source_is_rejected():
    source = json.loads(captured())
    source["entries"] = list(reversed(source["entries"]))
    with pytest.raises(ValueError, match="row order"):
        builder.build(json.dumps(source).encode())
    source["entries"].pop()
    with pytest.raises(ValueError, match="Incomplete"):
        builder.build(json.dumps(source).encode())
