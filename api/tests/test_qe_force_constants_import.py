"""Synthetic format adversaries; these are not executed or approved QE runs."""

import hashlib
import json
import math

import pytest

from services.qe_force_constants_import import (
    BOHR_TO_ANGSTROM,
    MAX_BYTES,
    MAX_PHYSICAL_LINES,
    ForceConstantsImportError,
    parse_force_constants,
)


def make_file(*, nat=2, grid=(2, 2, 1), ibrav=2, alat=10.5,
              cell=None, positions=None, long_range=False, born=True, labels=None):
    labels = labels or (["Al", "As"] if nat == 2 else ["Al"])
    rows = [f"{len(labels)} {nat} {ibrav} {alat} 0 0 0 0 0"]
    if ibrav == 0:
        rows.extend(" ".join(map(str, row)) for row in (cell or [[1, 0, 0], [0, 1, 0], [0, 0, 1]]))
    rows.extend(f"{i} '{label} ' 24590.765652728711" for i, label in enumerate(labels, 1))
    positions = positions or ([[0, 0, 0], [0.25, 0.25, 0.25]] if nat == 2 else [[0, 0, 0]])
    rows.extend(f"{i} {i if len(labels) == nat else 1} " + " ".join(map(str, position))
                for i, position in enumerate(positions, 1))
    rows.append("T 1.0" if born else "F")
    if born:
        rows.extend(["10 0 0", "0 10 0", "0 0 10"])
        for atom in range(1, nat + 1):
            rows.extend([str(atom), "2 0 0", "0 2 0", "0 0 2"])
    rows.append(" ".join(map(str, grid)))
    for i in range(1, 4):
        for j in range(1, 4):
            for na in range(1, nat + 1):
                for nb in range(1, nat + 1):
                    rows.append(f"{i} {j} {na} {nb}")
                    for m3 in range(1, grid[2] + 1):
                        for m2 in range(1, grid[1] + 1):
                            for m1 in range(1, grid[0] + 1):
                                rows.append(f"{m1} {m2} {m3} -2.24440957174E-01" + (" 1.0D-2" if long_range else ""))
    return ("\n".join(rows) + "\n").encode()


def parse(payload=None, *, source_formula="AlAs", expected_sha256=None):
    payload = make_file() if payload is None else payload
    expected_sha256 = hashlib.sha256(payload).hexdigest() if expected_sha256 is None else expected_sha256
    return parse_force_constants(payload=payload, expected_sha256=expected_sha256, source_formula=source_formula)


def fail(code, payload, **kwargs):
    with pytest.raises(ForceConstantsImportError) as caught:
        parse(payload, **kwargs)
    assert str(caught.value) == code


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def test_complete_matrix_coordinates_hashes_are_replayable_not_scientific_approval():
    payload = make_file()
    result = parse(payload)
    assert parse(payload) == result
    assert result["status"] == "parsed"
    assert result["reason_codes"] == []
    assert result["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert set(result["authority"].values()) == {False}
    assert result["format_reference"]["producer_version"] is None
    assert result["inventory"]["entry_count"] == 9 * 4 * 4
    assert result["inventory"]["expected_entry_count"] == 144
    assert result["inventory"]["block_count"] == 36
    assert result["inventory"]["negative_value_count"] == 144
    assert result["inventory"]["coverage_complete"] is True
    assert result["coordinate_sha256"] == hashlib.sha256(canonical(result["coordinates"])).hexdigest()
    assert result["normalization"]["coordinate_basis"] == "periodic_representation_not_bulk_no_vacuum_attestation"
    assert "no_force_constant_to_frequency_recomputation" in result["limitations"]


def test_qe_fcc_orientation_cartesian_tau_and_actual_primitive_volume():
    result = parse()
    cell = result["coordinates"]["cell_angstrom"]
    a = 10.5 * BOHR_TO_ANGSTROM
    assert cell == [[-a / 2, 0, a / 2], [0, a / 2, a / 2], [-a / 2, a / 2, 0]]
    fraction = result["coordinates"]["sites"][1]["fractional"]
    assert fraction == pytest.approx([-0.25, 0.75, -0.25])
    rebuilt = [sum(fraction[j] * cell[j][i] for j in range(3)) for i in range(3)]
    assert rebuilt == pytest.approx([a * 0.25] * 3)
    assert {item["element"] for item in result["coordinates"]["sites"]} == {"Al", "As"}


def test_ibrav_zero_explicit_vectors_with_positive_alat_are_scaled_from_alat():
    result = parse(make_file(ibrav=0, alat=4, cell=[[1, 0, 0], [0, 2, 0], [0, 0, 3]]))
    assert result["coordinates"]["cell_angstrom"] == [[4 * BOHR_TO_ANGSTROM, 0, 0],
                                                      [0, 8 * BOHR_TO_ANGSTROM, 0],
                                                      [0, 0, 12 * BOHR_TO_ANGSTROM]]
    assert result["coordinates"]["sites"][1]["fractional"] == pytest.approx([0.25, 0.125, 1 / 12])


def test_ibrav_zero_zero_alat_vectors_are_bohr_and_tau_uses_first_vector_norm():
    result = parse(make_file(ibrav=0, alat=0, cell=[[4, 0, 0], [0, 8, 0], [0, 0, 12]]))
    assert result["coordinates"]["cell_angstrom"][0][0] == 4 * BOHR_TO_ANGSTROM
    assert result["coordinates"]["sites"][1]["fractional"] == pytest.approx([0.25, 0.125, 1 / 12])


def test_no_born_tensor_flag_does_not_invent_zero_observations():
    result = parse(make_file(born=False))
    observed = result["header"]["electrostatics"]
    assert observed["has_born_charges"] is False
    assert observed["dielectric"] == observed["born_charges"] == []
    assert observed["alpha"] is None


def test_unsupported_ibrav_validates_full_inventory_but_emits_no_coordinates():
    result = parse(make_file(ibrav=4))
    assert result["status"] == "quarantined"
    assert result["reason_codes"] == ["unsupported_ibrav_coordinate_convention"]
    assert result["inventory"]["coverage_complete"] is True
    assert result["coordinates"] is result["coordinate_sha256"] is None


@pytest.mark.parametrize(("formula", "reason"), [("Al2As", "force_constant_source_formula_mismatch"),
                                                  ("Al1-xAs", "unresolved_source_formula"),
                                                  ("13C", "unresolved_source_formula")])
def test_formula_is_checked_not_used_to_invent_sites(formula, reason):
    result = parse(source_formula=formula)
    assert result["status"] == "quarantined"
    assert reason in result["reason_codes"]
    assert result["coordinates"] is None


def test_integer_superformula_has_equal_atomic_fractions_not_identity_authority():
    assert parse(source_formula="Al2As2")["status"] == "parsed"
    assert parse(source_formula="Al2As2")["normalization"]["formula_comparison"] == "atomic_fractions_not_material_identity"


def test_alias_species_not_promoted_to_element():
    result = parse(make_file(labels=["Al_pv", "As"]))
    assert result["status"] == "quarantined"
    assert result["header"]["species"][0]["element"] is None
    assert "unresolved_force_constant_species" in result["reason_codes"]


def test_long_range_extra_column_is_fully_validated_then_quarantined():
    result = parse(make_file(long_range=True))
    assert result["inventory"]["layout"] == "short_and_long_range"
    assert result["inventory"]["entry_count"] == 144
    assert result["reason_codes"] == ["long_range_force_constant_context_unresolved"]
    assert result["coordinates"] is None


def test_matrix_inventory_digest_binds_every_value_not_just_counts_or_coordinates():
    before = parse()
    changed = make_file().replace(b"-2.24440957174E-01", b"+2.24440957174E-01", 1)
    after = parse(changed)
    assert after["inventory"]["entry_count"] == before["inventory"]["entry_count"]
    assert after["coordinate_sha256"] == before["coordinate_sha256"]
    assert after["inventory"]["matrix_inventory_sha256"] != before["inventory"]["matrix_inventory_sha256"]


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
def test_header_and_matrix_byte_locators_use_native_line_endings(ending):
    payload = make_file().replace(b"\n", ending)
    result = parse(payload)
    for value in result["header"]["celldm"]:
        span = value["locator"]
        assert payload[span["start_byte"]:span["end_byte"]].decode() == value["raw_text"]
    for site in result["header"]["sites"]:
        for value in site["cartesian_tau"]:
            span = value["locator"]
            assert payload[span["start_byte"]:span["end_byte"]].decode() == value["raw_text"]
    span = result["inventory"]["data_locator"]
    assert payload[span["start_byte"]:span["end_byte"]].startswith(b"1 1 1 1")
    assert payload[:span["start_byte"]].count(ending) + 1 == span["line"]


@pytest.mark.parametrize("bad_hash", ["0" * 64, "A" * 64, "1" * 63, True])
def test_hash_pin_is_strict_and_checked_before_parsing(bad_hash):
    with pytest.raises(ForceConstantsImportError):
        parse(expected_sha256=bad_hash)


def test_missing_matrix_entry_does_not_become_zero():
    data = make_file().splitlines(keepends=True)
    fail("incomplete_force_constant_file", b"".join(data[:-1]))


def test_duplicate_lattice_address_with_same_total_count_rejected():
    data = make_file().replace(b"2 1 1 -2.24440957174E-01", b"1 1 1 -2.24440957174E-01", 1)
    fail("force_constant_lattice_index_mismatch", data)


def test_duplicate_block_with_same_total_count_rejected():
    data = make_file().replace(b"1 1 1 2\n", b"1 1 1 1\n", 1)
    fail("force_constant_block_index_mismatch", data)


def test_extra_complete_block_or_footer_not_ignored():
    fail("unexpected_force_constant_trailing_records", make_file() + b"1 1 1 1\n1 1 1 0\n")


@pytest.mark.parametrize("raw", [b"NaN", b"Inf", b"1e999", b"1e-999", b"1e-999999", b"1i", "١".encode()])
def test_nonfinite_complex_underflow_or_non_native_numbers_rejected(raw):
    data = make_file().replace(b"-2.24440957174E-01", raw, 1)
    with pytest.raises(ForceConstantsImportError):
        parse(data)


def test_mixed_short_and_long_range_layout_rejected():
    data = make_file().replace(b"-2.24440957174E-01", b"-2.24440957174E-01 1", 1)
    fail("inconsistent_force_constant_matrix_layout", data)


def test_born_atom_index_must_be_exact_not_ignored_blank_record():
    data = make_file().replace(b"2\n2 0 0\n", b"1\n2 0 0\n", 1)
    fail("force_constant_born_index_mismatch", data)


def test_wrong_species_and_site_indices_rejected():
    fail("force_constant_species_index_mismatch", make_file().replace(b"2 'As '", b"1 'As '", 1))
    fail("force_constant_site_index_mismatch", make_file().replace(b"2 2 0.25", b"1 2 0.25", 1))


def test_unused_species_rejected_not_hidden_in_header():
    fail("unused_force_constant_species", make_file().replace(b"2 2 0.25", b"2 1 0.25", 1))


@pytest.mark.parametrize("cell", [[[1, 0, 0], [2, 0, 0], [0, 0, 1]],
                                  [[-1, 0, 0], [0, 1, 0], [0, 0, 1]]])
def test_degenerate_or_left_handed_cell_is_not_canonicalized(cell):
    fail("invalid_or_left_handed_force_constant_cell", make_file(ibrav=0, cell=cell))


def test_periodic_duplicate_sites_rejected():
    fail("duplicate_periodic_force_constant_site", make_file(positions=[[0, 0, 0], [-0.5, 0, 0.5]]))


def test_grid_budget_is_checked_before_any_matrix_allocations():
    data = make_file().replace(b"2 2 1\n", b"128 128 128\n", 1)
    fail("force_constant_matrix_inventory_limit", data)


def test_blank_payload_is_bounded_before_per_line_hydration():
    fail("force_constant_physical_line_limit", b"\n" * (MAX_PHYSICAL_LINES + 1))
    fail("force_constant_physical_line_limit", b"\n" * MAX_BYTES)


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_unicode_separator_is_not_fortran_newline(separator):
    data = make_file().replace(b"\n", separator.encode(), 1)
    fail("unsupported_unicode_line_separator", data)


def test_huge_cell_cannot_create_infinity_or_nan_coordinate_json():
    fail("force_constant_cell_magnitude_limit", make_file(alat=1e308))


@pytest.mark.parametrize("source_formula", [True, "", "\ud800", "Al" * 4097])
def test_malformed_source_formula_rejected_with_safe_static_reason(source_formula):
    fail("invalid_force_constant_source_formula", make_file(), source_formula=source_formula)


def test_no_hidden_nonfinite_payload_and_standard_json_roundtrip():
    result = json.loads(canonical(parse()))
    assert math.isfinite(result["coordinates"]["cell_angstrom"][0][0])
    assert result["authority"]["scientific_accepted"] is False
