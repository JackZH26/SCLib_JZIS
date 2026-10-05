"""Real frozen source reconstruction and invalid-source regression tests."""

import importlib.util
import hashlib
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


def test_elastic_tokens_preserve_signed_zero_negative_and_nonfinite_source_values():
    reference = builder.build(captured())
    rows = reference["rows"]
    assert reference["elastic_coverage"] == {"both_moduli": 126, "finite_tensor": 132, "nonfinite_tensor": 1, "missing_tensor": 51}
    assert sum(row["bulk_modulus"]["value"] is None for row in rows) == 58
    assert sum(row["shear_modulus"]["value"] is None for row in rows) == 58
    assert sum((row["bulk_modulus"]["value"] or 0) < 0 for row in rows) == 2
    assert sum((row["shear_modulus"]["value"] or 0) < 0 for row in rows) == 3
    assert sum(row["elastic_tensor"]["status"] == "finite" and row["bulk_modulus"]["status"] == "supplied" for row in rows) == 126
    sic = next(row for row in rows if row["id"] == "JVASP-22644")
    assert sic["bulk_modulus"]["raw"] == "213.29"
    assert sic["shear_modulus"]["raw"] == "190.65"
    assert sic["elastic_tensor"]["raw"][0] == ["489.0", "103.7", "49.2", "-0.0", "-0.0", "0.0"]
    invalid = next(row for row in rows if row["id"] == "JVASP-95531")
    assert invalid["elastic_tensor"]["status"] == "source_nonfinite"
    assert invalid["elastic_tensor"]["nonfinite_count"] == 6
    assert invalid["elastic_tensor"]["raw"][0][:2] == ["5e-324", "NaN"]
    assert invalid["bulk_modulus"]["value"] is None
    # The derived download is standard JSON; original NaNs remain strings only.
    json.dumps(reference, allow_nan=False)
    # A new edition cannot overwrite the previously released finite reference.
    old = builder.ASSETS / "discovery-host-reference-2026-10-05.json"
    assert hashlib.sha256(old.read_bytes()).hexdigest() == "1d3ead91305af81948269ba975a920ce200fc51daf86a3e42c11c0241fd8b257"
    for previous, current, entry in zip(json.loads(old.read_bytes())["rows"], rows, json.loads(captured())["entries"], strict=True):
        assert {key: current[key] for key in previous} == previous
        tokens = json.loads(entry["source_record_json"], parse_int=str, parse_float=str, parse_constant=str)
        assert current["elastic_tensor"]["raw"] == ([] if tokens["elastic_tensor"] == "na" else tokens["elastic_tensor"])


@pytest.mark.parametrize("field,value", [
    ("bulk_modulus_kv", None), ("shear_modulus_gv", True), ("bulk_modulus_kv", "unknown"),
    ("elastic_tensor", None), ("elastic_tensor", [[0.0] * 6] * 5),
    ("elastic_tensor", [["0.0"] * 6] * 6), ("elastic_tensor", [[float("inf")] * 6] * 6),
])
def test_invalid_elastic_fields_fail_instead_of_silent_missing_or_zero(field, value):
    source = json.loads(captured())
    record = json.loads(source["entries"][0]["source_record_json"])
    record[field] = value
    source["entries"][0]["source_record_json"] = json.dumps(record)
    with pytest.raises(ValueError):
        builder.build(json.dumps(source).encode())
