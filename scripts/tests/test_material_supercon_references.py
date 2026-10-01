"""Offline parser, real packaged source integrity and scientific-boundary tests."""
from __future__ import annotations

import asyncio
import csv
import gzip
import hashlib
import io
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
from services import material_supercon_references as service  # noqa: E402


def source_bytes(rows, columns=None):
    columns = columns or [*service.SELECTED_COLUMNS, "author"]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\r\n")
    writer.writerow(["label " + key for key in columns])
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(key, "") for key in columns])
    return stream.getvalue().encode()


def encoded(**values):
    raw = source_bytes([{"num": "1", "element": "Nb", **values}])
    return service.parse_source_table(raw, require_known_snapshot=False)[0]


def projected(**values):
    return service.project_source_row(encoded(**values))


def quantities(row):
    return {q["field"]: q for q in row["quantities"]}


def test_source_hashes_exact_multiline_physical_bytes_and_crlf():
    raw = source_bytes([{"num": "2", "element": "Nb", "author": "A\r\nB"}])
    row = service.parse_source_table(raw, require_known_snapshot=False)[0]
    assert row["l"] == 3 and row["e"] == 4
    assert row["h"] == hashlib.sha256(b"".join(raw.splitlines(keepends=True)[2:4])).hexdigest()
    assert "A" not in row["v"] and "B" not in row["v"]


@pytest.mark.parametrize("rows", [
    [{"num": "1", "element": "Nb"}, {"num": "1", "element": "NbN"}],
    [{"num": "-1"}], [{"num": "1.0"}], [{"num": ""}], [{"num": "001"}],
    [{"num": "1", "tc": "9\x00"}], [{"num": "1", "title": "x" * 1001}],
])
def test_source_identity_or_cell_malformed_rejected(rows):
    with pytest.raises(ValueError):
        service.parse_source_table(source_bytes(rows), require_known_snapshot=False)


def test_missing_duplicate_and_badwidth_headers_rejected():
    for raw in [source_bytes([], columns=["num", "element"]),
                source_bytes([], columns=[*service.SELECTED_COLUMNS, "num"]),
                source_bytes([{"num": "1"}]) + b"2\tNb\r\n"]:
        with pytest.raises(ValueError):
            service.parse_source_table(raw, require_known_snapshot=False)


def test_immutable_snapshot_check_is_not_skipped_by_builder():
    with pytest.raises(ValueError, match="immutable source snapshot"):
        service.build_snapshot(source_bytes([{"num": "1", "element": "Nb"}]))


def test_source_bytes_bounded_before_parsing(monkeypatch):
    monkeypatch.setattr(service, "MAX_SOURCE_BYTES", 2)
    with pytest.raises(ValueError, match="byte bound"):
        service.parse_source_table(b"xxx", require_known_snapshot=False)


@pytest.mark.parametrize("field,raw_unit,unit,status", [
    ("tc", "K", "K", "reported"), ("tc", "", None, "unit_not_supplied"),
    ("tc", "k", None, "unit_requires_review"),
    ("lata", "A", "Å", "reported"), ("latc", "nm", "nm", "reported"),
    ("lata", "", None, "unit_not_supplied"),
    ("hc2t", "T", "T", "reported"), ("hc2t", "A", None, "unit_requires_review"),
    ("hc2t", "kA/m", "kA/m", "reported"),
    ("gap", "meV", "meV", "reported"), ("gap", "MeV", None, "unit_requires_review"),
    ("gap", "mV", None, "unit_requires_review"),
    ("gamma", "mJ/mol.K2", "mJ/(mol K²)", "reported"),
    ("gamma", "MJ/MOLE.K2", None, "unit_requires_review"),
    ("dtcdp", "K/kbar", "K/kbar", "reported"),
    ("dtcdp", "6.2", None, "unit_requires_review"),
    ("dtcdp", "GPa", None, "unit_requires_review"),
])
def test_quantity_units_dimension_case_and_missingness(field, raw_unit, unit, status):
    column = service.QUANTITIES[field][1]
    q = quantities(projected(**{field: "1.25", column: raw_unit}))[field]
    assert q["raw_value"] == "1.25" and q["value"] == 1.25
    assert q["raw_unit"] == (raw_unit or None) and q["unit"] == unit and q["status"] == status


@pytest.mark.parametrize("value", ["nan", "inf", "1e500", "9-10", "~4", "<3"])
def test_unresolved_or_nonfinite_values_preserved_not_silently_normalized(value):
    q = quantities(projected(tc=value, utc="K"))["tc"]
    assert q["raw_value"] == value and q["value"] is None
    assert q["status"] == "value_requires_review"


def test_distinct_tc_criteria_measurement_limit_and_pmax_are_never_joined():
    row = projected(tc="29", t1="24", t2="29", t3="32", tcsus="28", tcn="0", pmax="5", utc="K")
    q = quantities(row)
    assert q["t1"]["meaning"] == "zero_resistance_tc"
    assert q["t2"]["meaning"] == "midpoint_tc" and q["t3"]["meaning"] == "resistive_r100_tc"
    assert q["tcn"]["value"] == 0 and "not_tc" in q["tcn"]["meaning"]
    assert q["pmax"]["unit"] is None and q["pmax"]["status"] == "unit_not_supplied"
    assert "not_any_tc" in q["pmax"]["meaning"] and q["tc"]["temperature_raw"] is None
    assert "pressure" not in row and "tc_kelvin" not in row


def test_documented_and_undocumented_method_codes_distinct():
    row = projected(shape="6", analm="35", tcmeth="M")
    for field in ("sample_form", "structure_method", "tc_method"):
        assert row[field]["status"] == "requires_review" and row[field]["label"] is None
    good = projected(shape="3", analm="3", tcmeth="3")
    assert good["sample_form"]["label"] == "Single crystal bulk"
    assert good["structure_method"]["label"] == "Powder X-ray diffraction"
    assert good["tc_method"]["label"] == "Resistivity"
    assert projected()["tc_method"]["status"] == "not_supplied"


def test_spacegroup_invalid_identifier_is_preserved_and_no_doi_guess():
    row = projected(tblno="158982fig3", refno="PRB9991234", title="A source title")
    assert row["structure"]["space_group_number"] is None
    assert row["structure"]["space_group_number_raw"] == "158982fig3"
    assert row["url"] == service.DATA_DOI and row["bibliography"]["reference_code"] == "PRB9991234"
    assert projected(tblno="230")["structure"]["space_group_number"] == 230
    assert projected(tblno="231")["structure"]["space_group_number"] is None


def test_hc2_direction_temperature_raw_and_isotope_context_retained():
    row = projected(phc2t="12", uhc2="T", tempc2="4.2", isoel="O", isorat="90%", isotope="0.2")
    q = quantities(row)["phc2t"]
    assert q["direction"] == "H_parallel_ab" and q["temperature_raw"] == "4.2"
    assert "unit_not_supplied" in q["meaning"]
    assert row["isotope_element"] == "O" and row["isotope_exchange_ratio"] == "90%"
    assert quantities(row)["isotope"]["unit"] == "dimensionless"


def test_field_orientation_never_relabelled_as_length_tensor_axis():
    q = quantities(projected(pcohere="25", ncohere="30", ppenet="400", npenet="500"))
    for field in ("pcohere", "ppenet"):
        assert "H parallel to ab" in q[field]["label"] and q[field]["direction"] == "H_parallel_ab"
    for field in ("ncohere", "npenet"):
        assert "H normal to ab" in q[field]["label"] and q[field]["direction"] == "H_normal_ab"
    assert projected(shape="5")["sample_form"]["label"] == "Film (single)"


def test_real_derivation_style_metadata_preserved_without_observed_inference():
    row = projected(hc2zero="25", mhc2="resistivity, WHH", cohere="30", mcohere="calculated from Hc2(0)",
                    penet="400", mpenet="muon-SR", gamma="5", gamcom="parameter fitting from Hc measurement",
                    debyet="300", mdebye="calculated from elastic constant", gap="1.2", gapmeth="14")
    q = quantities(row)
    assert q["hc2zero"]["source_method_raw"] == "resistivity, WHH"
    assert q["cohere"]["method_label"] == "calculated from Hc2(0)" and q["cohere"]["method_status"] == "reported"
    assert q["gap"]["source_method_raw"] == "14" and q["gap"]["method_status"] == "requires_review"
    assert q["gap"]["method_label"] is None
    assert row["raw_source_method_fields"]["mdebye"] == "calculated from elastic constant"
    assert "knowledge_origin" not in row
    assert quantities(projected(gap="1.2", gapmeth="1"))["gap"]["method_label"] == "Tunneling"
    assert quantities(projected(gamma="5"))["gamma"]["method_status"] == "not_supplied"
    assert quantities(projected(hc2zero="25", mhc2="3"))["hc2zero"]["method_status"] == "requires_review"
    assert quantities(projected(hc1zero=".2", mhc1="3"))["hc1zero"]["method_label"] == "Resistivity"


@pytest.mark.asyncio
@pytest.mark.parametrize("formula,records", [
    ("Nb-x", None), ("^10B", None), ("YBCO", None),
    ("Nb", [{"formula_raw": "^93Nb"}]),
    ("NbN", [{"formula_raw": "NbN0.9"}]),
    ("Nb", [{"formula_raw": "Nb"}, {"formula_raw": "NbH"}]),
])
async def test_source_identity_guard_before_any_snapshot_access(monkeypatch, formula, records):
    def forbidden():
        raise AssertionError("unresolved source attempted loading snapshot")
    monkeypatch.setattr(service, "_read_snapshot", forbidden)
    response = await service.fetch_material_supercon_references(formula, current_records=records)
    assert response["status"] == "not_applicable"
    assert response["references"] == [] and response["matches_total"] is None


@pytest.mark.asyncio
async def test_actual_packaged_rows_integrity_provenance_no_scientific_promotion():
    response = await service.fetch_material_supercon_references("Nb", current_records=[{"formula_raw": "Nb"}])
    assert response["status"] == "available" and response["matches_total"] == 19
    assert response["omitted_rows"] == 0 and not response["truncated"]
    assert all(response[key] is False for key in ("scientific_acceptance", "sample_identity_established", "phase_identity_established"))
    assert response["source_publication_status"] == "not_checked"
    assert response["dataset_version"] == "240322" and response["license"] == "CC BY 4.0"
    assert len(response["references"]) == 19
    assert [int(row["source_row_id"]) for row in response["references"]] == sorted(int(row["source_row_id"]) for row in response["references"])
    for row in response["references"]:
        assert row["id"] == "mdr:240322:oxide_metallic:" + row["source_row_id"]
        assert row["source_sha256"] == service.SOURCE_SHA256
        assert row["source_line"] >= 3 and row["source_line_end"] >= row["source_line"]
        assert len(row["source_row_sha256"]) == 64
        assert service._composition_key(row["formula"]) == service._composition_key("Nb")
        assert len(row["quantities"]) <= 32
        assert not {"author", "raw_source", "source_excerpt", "knowledge_origin", "pressure_gpa", "tc_kelvin"} & row.keys()
    original = response["references"][0]["formula"]
    response["references"][0]["formula"] = "corrupted caller value"
    again = await service.fetch_material_supercon_references("Nb")
    assert again["references"][0]["formula"] == original


@pytest.mark.asyncio
async def test_real_nbn_pbc_and_lasmofbis_coverage():
    nbn = await service.fetch_material_supercon_references("NbN")
    assert nbn["matches_total"] == 15
    assert any("gap" in quantities(row) for row in nbn["references"])
    pbc = await service.fetch_material_supercon_references("PbCe")
    assert pbc["matches_total"] == 1
    assert "tcn" in quantities(pbc["references"][0]) and "tc" not in quantities(pbc["references"][0])
    mixed = await service.fetch_material_supercon_references("La0.4Sm0.6O0.5F0.5BiS2")
    assert mixed["matches_total"] == 2
    assert any(row["structure"]["space_group"] and "lata" in quantities(row) for row in mixed["references"])


@pytest.mark.asyncio
async def test_true_no_match_is_limited_to_versioned_oxide_metallic_scope():
    response = await service.fetch_material_supercon_references("YScH10")
    assert response["status"] == "no_match" and response["matches_total"] == 0
    assert response["reason"] == "no_fixed_composition_row_in_oxide_metallic_240322"
    assert response["scope"].startswith("oxide_metallic")


def test_total_and_omission_honest_not_phase_complete(monkeypatch):
    rows = [encoded(num=str(n + 1)) for n in range(25)]
    monkeypatch.setattr(service, "_read_snapshot", lambda: ({"resource_sha256": "a" * 64}, {service._composition_key("Nb"): rows}))
    response = service._query_snapshot("Nb", "Nb")
    assert response["matches_total"] == 25 and len(response["references"]) == 20
    assert response["omitted_rows"] == 5 and response["truncated"]
    assert [row["source_row_id"] for row in response["references"]] == [str(n) for n in range(1, 21)]


def test_invalid_snapshot_is_unavailable_not_no_match(monkeypatch):
    def broken():
        raise ValueError("integrity failure")
    monkeypatch.setattr(service, "_read_snapshot", broken)
    response = service._query_snapshot("Nb", "Nb")
    assert response["status"] == "unavailable" and response["matches_total"] is None


def test_malformed_nested_snapshot_is_unavailable_not_500(monkeypatch):
    def broken():
        raise RecursionError("deep invalid json")
    monkeypatch.setattr(service, "_read_snapshot", broken)
    assert service._query_snapshot("Nb", "Nb")["status"] == "unavailable"


def test_real_resource_manifest_hashes_and_projection_allowlist():
    manifest = json.loads(service.MANIFEST_PATH.read_text())
    raw = service.RESOURCE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["resource_sha256"]
    plain = gzip.decompress(raw)
    assert hashlib.sha256(plain).hexdigest() == manifest["decompressed_sha256"]
    assert len(raw) <= service.MAX_RESOURCE_BYTES and len(plain) <= service.MAX_DECOMPRESSED_BYTES
    doc = json.loads(plain)
    assert len(doc["rows"]) == 33458 and len({row["n"] for row in doc["rows"]}) == 33458
    assert doc["columns"] == list(service.SELECTED_COLUMNS)
    assert "author" not in doc["columns"] and "commt" not in doc["columns"]
    assert manifest["row_hash_basis"] == "complete_original_physical_source_lines_including_line_endings"


def test_manifest_integrity_rechecked_on_cold_load(monkeypatch, tmp_path):
    manifest = json.loads(service.MANIFEST_PATH.read_text())
    manifest["source_sha256"] = "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(service, "MANIFEST_PATH", path)
    monkeypatch.setattr(service, "_snapshot", None)
    with pytest.raises(ValueError, match="manifest"):
        service._read_snapshot()


@pytest.mark.parametrize("invalid", [[], [[]], None, "not a manifest", 42])
def test_manifest_non_object_is_unavailable(monkeypatch, tmp_path, invalid):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(invalid))
    monkeypatch.setattr(service, "MANIFEST_PATH", path)
    monkeypatch.setattr(service, "_snapshot", None)
    assert service._query_snapshot("Nb", "Nb")["status"] == "unavailable"


def test_raw_resource_and_decompression_byte_bounds(monkeypatch):
    monkeypatch.setattr(service, "_snapshot", None)
    with monkeypatch.context() as patch:
        patch.setattr(service, "MAX_RESOURCE_BYTES", 2)
        assert service._query_snapshot("Nb", "Nb")["status"] == "unavailable"
    with monkeypatch.context() as patch:
        patch.setattr(service, "MAX_DECOMPRESSED_BYTES", 2)
        assert service._query_snapshot("Nb", "Nb")["status"] == "unavailable"


def test_resource_sha_failure_is_unavailable(monkeypatch, tmp_path):
    resource = tmp_path / "tampered.gz"
    resource.write_bytes(service.RESOURCE_PATH.read_bytes()[:-1] + b"x")
    monkeypatch.setattr(service, "RESOURCE_PATH", resource)
    monkeypatch.setattr(service, "_snapshot", None)
    assert service._query_snapshot("Nb", "Nb")["status"] == "unavailable"


@pytest.mark.asyncio
async def test_cpu_worker_off_eventloop_and_cancel_keeps_permit(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def work(formula, query):
        entered.set()
        assert release.wait(3)
        return service._base(formula, "no_match", query=query)
    workers = asyncio.Semaphore(1)
    monkeypatch.setattr(service, "_workers", workers)
    monkeypatch.setattr(service, "_query_snapshot", work)
    task = asyncio.create_task(service.fetch_material_supercon_references("Nb"))
    for _ in range(100):
        if entered.is_set():
            break
        await asyncio.sleep(.001)
    assert entered.is_set()
    task.cancel()
    await asyncio.sleep(.01)
    assert workers.locked() and task.done()
    with pytest.raises(asyncio.CancelledError):
        await task
    queued = asyncio.create_task(service.fetch_material_supercon_references("Nb"))
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert workers.locked()
    release.set()
    for _ in range(100):
        if not workers.locked():
            break
        await asyncio.sleep(.001)
    assert not workers.locked()
