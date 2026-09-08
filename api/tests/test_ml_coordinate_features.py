"""Actual coordinate-file fixtures, never formula-inferred structures."""

import copy
import hashlib
import json

import pytest

from services.ml_coordinate_features import (
    AVOGADRO_PER_MOL,
    JSON_FORMAT,
    MAX_BYTES,
    MAX_SITES,
    POSCAR_FORMAT,
    coordinate_features,
)


def document():
    return {"version": JSON_FORMAT, "boundary_conditions": "bulk_3d_periodic",
            "cell_angstrom": [[3, 0, 0], [0, 3, 0], [0, 0, 3]],
            "sites": [{"element": "Mg", "fractional": [0, 0, 0], "occupancy": 1},
                      {"element": "B", "fractional": [0.5, 0.5, 0.5], "occupancy": 1},
                      {"element": "B", "fractional": [0.25, 0.25, 0.25], "occupancy": 1}]}


def encoded(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def calculate(value=None, *, formula="MgB2", coordinate_format=JSON_FORMAT, scope="bulk_3d_no_vacuum"):
    raw = encoded(document() if value is None else value) if type(value) is not bytes else value
    return coordinate_features(raw, hashlib.sha256(raw).hexdigest(), formula,
                               coordinate_format=coordinate_format, geometry_scope=scope)


def poscar(*, mode="Direct", scale="1.0", cell=None, positions=None, selective=False):
    lines = ["Synthetic fixture: not a measured crystal", scale,
             *(cell or ["3 0 0", "0 3 0", "0 0 3"]), "Mg B", "1 2"]
    if selective:
        lines.append("Selective dynamics")
    lines.append(mode)
    positions = positions or ["0 0 0", "0.5 0.5 0.5", "0.25 0.25 0.25"]
    lines.extend([line + " T F T" for line in positions] if selective else positions)
    return ("\n".join(lines) + "\n").encode()


def test_full_coordinate_json_mass_volume_units_hashes_and_no_scientific_authority():
    value = document()
    before = copy.deepcopy(value)
    result = calculate(value)
    assert value == before
    assert result["status"] == "computed", result
    assert result["feature_names"] == ["volume_per_atom_a3", "density_g_cm3"]
    assert result["units"] == ["angstrom^3/atom", "g/cm^3"]
    assert result["values"] == pytest.approx([9, 45.925 * 1e24 / (AVOGADRO_PER_MOL * 27)])
    assert result["reason_codes"] == []
    assert result["scientific_acceptance"] is result["ml_training_eligible"] is False
    assert result["provenance"]["artifact_sha256"] == hashlib.sha256(encoded(value)).hexdigest()
    assert result["provenance"]["site_count"] == 3
    assert result["provenance"]["cell_volume_angstrom3"] == 27
    assert "not_potcar_attestation" in result["provenance"]["species_basis"]
    assert "not_isotope_specific" in result["provenance"]["mass_basis"]
    assert calculate(value) == result


def test_permutation_translation_rotation_and_integer_supercell_invariants():
    base = calculate()
    value = document()
    value["sites"].reverse()
    for site in value["sites"]:
        site["fractional"] = [component + 3.25 for component in site["fractional"]]
    assert calculate(value)["values"] == pytest.approx(base["values"])
    value["cell_angstrom"] = [[0, 3, 0], [-3, 0, 0], [0, 0, 3]]
    assert calculate(value)["values"] == pytest.approx(base["values"])
    value = document()
    original = value["sites"]
    value["cell_angstrom"][0][0] *= 2
    value["sites"] = [dict(site, fractional=[(site["fractional"][0] + offset) / 2, *site["fractional"][1:]])
                      for offset in (0, 1) for site in original]
    supercell = calculate(value)
    assert supercell["status"] == "computed"
    assert supercell["values"] == pytest.approx(base["values"])
    assert supercell["provenance"]["site_count"] == 6


@pytest.mark.parametrize("selective", [False, True])
@pytest.mark.parametrize("mode", ["Direct", "Cartesian"])
def test_concrete_vasp5_poscar_and_scale_convention_matches_json(selective, mode):
    positions = ["0 0 0", "1.5 1.5 1.5", "0.75 0.75 0.75"] if mode == "Cartesian" else None
    raw = poscar(mode=mode, positions=positions, selective=selective)
    result = calculate(raw, coordinate_format=POSCAR_FORMAT)
    assert result["status"] == "computed", result
    assert result["values"] == pytest.approx(calculate()["values"])
    scaled = calculate(poscar(mode=mode, scale="2", positions=positions, selective=selective), coordinate_format=POSCAR_FORMAT)
    assert scaled["values"][0] == pytest.approx(result["values"][0] * 8)
    assert scaled["values"][1] == pytest.approx(result["values"][1] / 8)


def test_nonorthogonal_cartesian_inverse_uses_lattice_rows_and_global_scale():
    # Deliberately choose equivalent direct/cartesian coordinates; a column/row
    # or missing scale error can turn the last two into duplicate periodic sites.
    cell = ["2 0 0", "1 3 0", "0.5 0.25 4"]
    direct = poscar(cell=cell, scale="2", positions=["0 0 0", "0.5 0.5 0.5", "0.25 0.25 0.25"])
    cart = poscar(cell=cell, scale="2", mode="Cartesian", positions=["0 0 0", "1.75 1.625 2", "0.875 0.8125 1"])
    first, second = calculate(direct, coordinate_format=POSCAR_FORMAT), calculate(cart, coordinate_format=POSCAR_FORMAT)
    assert first["status"] == second["status"] == "computed"
    assert first["values"] == second["values"]
    duplicate = poscar(cell=cell, scale="2", mode="Cartesian", positions=["0 0 0", "2 0 0", "0.875 0.8125 1"])
    assert calculate(duplicate, coordinate_format=POSCAR_FORMAT)["reason_codes"] == ["duplicate_periodic_sites"]


@pytest.mark.parametrize("formula", ["Nb", "MgB3", "LaD10", "La₂Cu¹⁸O₄", "La2-xSrxCuO4", "FeSe/SrTiO3", "", None, True, "\ud800"])
def test_exact_claim_formula_binding_and_unresolved_isotopes_do_not_get_mass_features(formula):
    result = calculate(formula=formula)
    assert result["status"] == "unavailable" and result["values"] == [None, None]
    json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")


@pytest.mark.parametrize("occupancy", [0.5, 0, 2, True, False, None, "1"])
def test_disorder_or_non_numeric_occupancy_never_becomes_ordered_structure(occupancy):
    value = document()
    value["sites"][0]["occupancy"] = occupancy
    result = calculate(value)
    assert result["status"] == "unavailable"
    assert result["reason_codes"] == ["full_occupancy_required"]


@pytest.mark.parametrize("scope", [None, "slab", "monolayer", "moiré", "bulk", True, {}])
def test_no_bulk_or_no_vacuum_inference_from_three_periodic_lattice_vectors(scope):
    assert calculate(scope=scope)["reason_codes"] == ["reviewed_bulk_geometry_declaration_required"]


@pytest.mark.parametrize("change", [
    {"boundary_conditions": "slab_2d_periodic"}, {"space_group": 191},
    {"version": "sclib-coordinate/0.1"}, {"sites": []},
    {"cell_angstrom": [[3, 0, 0], [6, 0, 0], [0, 0, 3]]},
    {"cell_angstrom": [[3, 0, 0], [0, 3, 0], [0, 0, 1e-15]]},
    {"cell_angstrom": [[True, 0, 0], [0, 3, 0], [0, 0, 3]]},
    {"cell_angstrom": [[10**1000, 0, 0], [0, 3, 0], [0, 0, 3]]},
])
def test_strict_closed_cell_metadata_and_numerical_geometry_bounds(change):
    value = document()
    value.update(change)
    assert calculate(value)["values"] == [None, None]


def test_site_inventory_unknown_species_duplicates_and_resource_caps():
    for replacement in (dict(document()["sites"][0], element="D"),
                        dict(document()["sites"][0], isotope_mass=18),
                        dict(document()["sites"][0], fractional=[1, 0, 0]),
                        dict(document()["sites"][0], fractional=[True, 0, 0])):
        value = document()
        value["sites"][1] = replacement
        assert calculate(value)["status"] == "unavailable"
    value = document()
    value["sites"] *= MAX_SITES
    assert calculate(value)["reason_codes"] == ["coordinate_site_budget"]
    assert calculate(b"x" * (MAX_BYTES + 1))["reason_codes"] == ["coordinate_bytes_budget_or_type"]


@pytest.mark.parametrize("raw", [b"{", b"\xff", b'{"x":NaN}', b'{"version":1,"version":2}', b"[" * 1100])
def test_json_duplicate_nonfinite_utf8_and_deep_payloads_fail_closed(raw):
    result = calculate(raw)
    assert result["status"] == "unavailable" and result["values"] == [None, None]


@pytest.mark.parametrize("raw", [
    poscar(scale="-27"), poscar(scale="1 1 1"), poscar(mode="surprise"),
    poscar().replace(b"Mg B\n", b""), poscar().replace(b"Mg B\n", b"Mg_pv B\n"),
    poscar().replace(b"1 2\n", b"1 3\n"), poscar() + b"Cartesian\n0 0 0\n",
    poscar().replace(b"0.5 0.5 0.5", b"0.5 0.5 0.5 B"),
    poscar(selective=True).replace(b"T F T", b"true false true"),
])
def test_unsupported_poscar_variants_do_not_silently_discard_geometry_or_metadata(raw):
    result = calculate(raw, coordinate_format=POSCAR_FORMAT)
    assert result["status"] == "unavailable" and result["values"] == [None, None]


def test_independent_hash_pin_required_and_bad_format_metadata_fail_closed():
    raw = encoded(document())
    for expected in ("0" * 64, "A" * 64, None, True):
        result = coordinate_features(raw, expected, "MgB2", coordinate_format=JSON_FORMAT, geometry_scope="bulk_3d_no_vacuum")
        assert result["status"] == "unavailable"
    for coordinate_format in ("cif", "space_group", {}, None):
        result = calculate(raw, coordinate_format=coordinate_format)
        assert result["reason_codes"] == ["unsupported_coordinate_format"]
