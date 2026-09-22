"""Two bounded bulk-coordinate descriptors, not a structure validation service.

Reads a closed explicit-site JSON format or a strict documented VASP5 POSCAR
subset. No symmetry expansion, CIF guessing, isotope masses, vacuum correction,
partial occupancy, or formula-to-coordinate inference is performed. A separate
review must bind the declared bulk/no-vacuum applicability to retained evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from importlib.resources import files

from services._composition import formula_enrichment as composition_parser
from services.ml_composition import ELEMENTS, composition_features

VERSION = "ml-coordinate-features/1.0.0"
JSON_FORMAT = "sclib-coordinate/1.0.0"
POSCAR_FORMAT = "vasp-poscar/1.0.0"
FEATURE_NAMES = ("volume_per_atom_a3", "density_g_cm3")
UNITS = ("angstrom^3/atom", "g/cm^3")
MAX_BYTES = 1_048_576
MAX_SITES = 256
MAX_CELL_COMPONENT_ANGSTROM = 10_000.0
MAX_POSITION_COMPONENT = 1_000_000.0
MIN_RELATIVE_CELL_VOLUME = 1e-12
PERIODIC_DUPLICATE_FRACTIONAL_TOLERANCE = 1e-8
COMPOSITION_FRACTION_TOLERANCE = 1e-10
AVOGADRO_PER_MOL = 6.02214076e23  # Exact SI constant; masses use the local conventional table.
_HASH = re.compile(r"^[0-9a-f]{64}$")
_NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")


class CoordinateFeatureError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise CoordinateFeatureError(code)


def _number(value, maximum):
    return type(value) in {int, float} and abs(value) <= maximum and math.isfinite(value)


def _triple(value, maximum):
    _require(type(value) is list and len(value) == 3 and all(_number(x, maximum) for x in value),
             "invalid_coordinate_triplet")
    return [float(x) for x in value]


def _det(cell):
    a, b, c = cell
    return a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])


def _cell(value):
    _require(type(value) is list and len(value) == 3, "invalid_cell")
    cell = [_triple(row, MAX_CELL_COMPONENT_ANGSTROM) for row in value]
    determinant = _det(cell)
    norm_product = math.prod(math.sqrt(math.fsum(x * x for x in row)) for row in cell)
    _require(math.isfinite(determinant) and norm_product > 0
             and abs(determinant) > max(1e-12, MIN_RELATIVE_CELL_VOLUME * norm_product),
             "degenerate_or_ill_conditioned_cell")
    return cell


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_coordinate_json_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise CoordinateFeatureError("nonfinite_coordinate_json")


def _json_coordinates(text):
    try:
        data = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except CoordinateFeatureError:
        raise
    except (ValueError, RecursionError):
        raise CoordinateFeatureError("invalid_coordinate_json") from None
    _require(type(data) is dict and set(data) == {"version", "boundary_conditions", "cell_angstrom", "sites"},
             "invalid_coordinate_json_fields")
    _require(data["version"] == JSON_FORMAT and data["boundary_conditions"] == "bulk_3d_periodic",
             "unsupported_coordinate_geometry")
    cell = _cell(data["cell_angstrom"])
    _require(type(data["sites"]) is list and 0 < len(data["sites"]) <= MAX_SITES, "coordinate_site_budget")
    sites = []
    for site in data["sites"]:
        _require(type(site) is dict and set(site) == {"element", "fractional", "occupancy"}, "invalid_coordinate_site_fields")
        _require(type(site["element"]) is str and site["element"] in ELEMENTS, "unknown_or_isotopic_coordinate_species")
        _require(type(site["occupancy"]) in {int, float} and site["occupancy"] == 1, "full_occupancy_required")
        sites.append((site["element"], _triple(site["fractional"], MAX_POSITION_COMPONENT)))
    return cell, sites


def _line_numbers(line, count):
    parts = line.split()
    _require(len(parts) == count and all(_NUMBER.fullmatch(part) for part in parts), "unsupported_poscar_numeric_line")
    values = [float(part) for part in parts]
    _require(all(_number(value, MAX_POSITION_COMPONENT) for value in values), "invalid_poscar_number")
    return values


def _fractional(cartesian, cell):
    # Rows are lattice vectors; solve r = f1*a + f2*b + f3*c by Cramer's rule.
    denominator = _det(cell)
    return [_det([cartesian if j == i else cell[j] for j in range(3)]) / denominator for i in range(3)]


def _poscar_coordinates(text):
    """Explicit VASP5 species, one positive scale, Direct/Cartesian, optional T/F.

    Negative/three-axis scales, omitted species, labels/pseudopotential aliases,
    velocities and MD continuation blocks are explicitly unsupported. A POSCAR
    species line does not authenticate the separate POTCAR used by a real run.
    See https://vasp.at/wiki/POSCAR for the upstream format and scale convention.
    """
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    _require(8 <= len(lines) <= MAX_SITES + 10 and all(len(line) <= 4096 for line in lines), "unsupported_poscar_layout")
    scale = _line_numbers(lines[1], 1)[0]
    _require(scale > 0, "unsupported_poscar_scale")
    cell = _cell([[scale * value for value in _line_numbers(line, 3)] for line in lines[2:5]])
    species = lines[5].split()
    _require(0 < len(species) <= len(ELEMENTS) and len(set(species)) == len(species)
             and all(element in ELEMENTS for element in species), "explicit_poscar5_species_required")
    counts = lines[6].split()
    _require(len(counts) == len(species) and all(re.fullmatch(r"[1-9][0-9]{0,2}", value) for value in counts), "invalid_poscar_species_counts")
    counts = [int(value) for value in counts]
    total = sum(counts)
    _require(0 < total <= MAX_SITES, "coordinate_site_budget")
    index = 7
    selective = lines[index].strip().lower() == "selective dynamics"
    if selective:
        index += 1
    _require(index < len(lines), "unsupported_poscar_layout")
    mode = lines[index].strip().lower()
    _require(mode in {"direct", "cartesian"}, "unsupported_poscar_coordinate_mode")
    index += 1
    _require(len(lines) == index + total, "unsupported_poscar_trailing_or_missing_data")
    ordered_species = [element for element, count in zip(species, counts, strict=True) for _ in range(count)]
    sites = []
    for element, line in zip(ordered_species, lines[index:], strict=True):
        parts = line.split()
        if selective:
            _require(len(parts) == 6 and all(flag in {"T", "F"} for flag in parts[3:]), "invalid_poscar_selective_flags")
        else:
            _require(len(parts) == 3, "unsupported_poscar_position_fields")
        position = _line_numbers(" ".join(parts[:3]), 3)
        if mode == "cartesian":
            position = _fractional([scale * component for component in position], cell)
        sites.append((element, _triple(position, MAX_POSITION_COMPONENT)))
    return cell, sites


def _check_sites(sites):
    normalized = []
    for _, position in sites:
        current = [value % 1.0 for value in position]
        for previous in normalized:
            _require(not all(min(abs(a - b), 1 - abs(a - b)) <= PERIODIC_DUPLICATE_FRACTIONAL_TOLERANCE
                             for a, b in zip(current, previous, strict=True)), "duplicate_periodic_sites")
        normalized.append(current)


def _safe_formula(value):
    if type(value) is not str or len(value) > 4096:
        return None
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return None
    return value


def coordinate_features(actual_bytes, expected_sha256, source_formula, *, coordinate_format, geometry_scope):
    """Return full-cell volume/atom and conventional-mass density, or both missing.

    geometry_scope must be explicitly supplied from reviewed retained metadata;
    this parser cannot independently distinguish a vacuum slab from a bulk cell.
    A successful calculation is not structural identity, stability, permission,
    observed/computed scientific acceptance, or feature-time availability.
    """
    result = {
        "version": VERSION, "status": "unavailable", "feature_names": list(FEATURE_NAMES),
        "values": [None, None], "units": list(UNITS), "reason_codes": [],
        "provenance": {
            "coordinate_format": coordinate_format if type(coordinate_format) is str and coordinate_format in {JSON_FORMAT, POSCAR_FORMAT} else None,
            "artifact_sha256": None, "source_formula": _safe_formula(source_formula),
            "geometry_scope": "bulk_3d_no_vacuum" if geometry_scope == "bulk_3d_no_vacuum" else None,
            "source_sha256": {"ml_coordinate_features": hashlib.sha256(files("services").joinpath("ml_coordinate_features.py").read_bytes()).hexdigest()},
            "composition": None, "site_count": None, "cell_volume_angstrom3": None,
            "mass_basis": "local_standard_weight_or_conventional_mass_not_isotope_specific",
            "species_basis": "declared_coordinate_elements_not_potcar_attestation",
        },
        "scientific_acceptance": False, "ml_training_eligible": False,
    }
    try:
        _require(type(actual_bytes) is bytes and 0 < len(actual_bytes) <= MAX_BYTES, "coordinate_bytes_budget_or_type")
        _require(type(expected_sha256) is str and _HASH.fullmatch(expected_sha256), "invalid_coordinate_sha256")
        actual_hash = hashlib.sha256(actual_bytes).hexdigest()
        result["provenance"]["artifact_sha256"] = actual_hash
        _require(actual_hash == expected_sha256, "coordinate_artifact_hash_mismatch")
        _require(type(geometry_scope) is str and geometry_scope == "bulk_3d_no_vacuum", "reviewed_bulk_geometry_declaration_required")
        _require(type(coordinate_format) is str and coordinate_format in {JSON_FORMAT, POSCAR_FORMAT}, "unsupported_coordinate_format")
        _require(type(source_formula) is str, "unresolved_source_formula")
        composition = composition_features({"formula_raw": source_formula})
        result["provenance"]["composition"] = composition["provenance"]
        _require(composition["status"] == "computed", "unresolved_source_formula")
        try:
            text = actual_bytes.decode("utf-8", errors="strict")
        except UnicodeError:
            raise CoordinateFeatureError("invalid_coordinate_utf8") from None
        cell, sites = _json_coordinates(text) if coordinate_format == JSON_FORMAT else _poscar_coordinates(text)
        _check_sites(sites)
        counts = Counter(element for element, _ in sites)
        for element, fraction in zip(ELEMENTS, composition["values"][:len(ELEMENTS)], strict=True):
            _require(abs(counts.get(element, 0) / len(sites) - fraction) <= COMPOSITION_FRACTION_TOLERANCE,
                     "coordinate_source_composition_mismatch")
        volume = abs(_det(cell))
        mass = math.fsum(float(composition_parser._ATOMIC_MASS[element]) * counts[element] for element in sorted(counts))
        values = [volume / len(sites), mass * 1e24 / (AVOGADRO_PER_MOL * volume)]
        _require(all(math.isfinite(value) and value > 0 for value in values), "nonfinite_coordinate_features")
        result.update(status="computed", values=values)
        result["provenance"].update(site_count=len(sites), cell_volume_angstrom3=volume)
    except CoordinateFeatureError as exc:
        result["reason_codes"] = [str(exc)]
    except (ValueError, TypeError, ArithmeticError, RecursionError):
        result["reason_codes"] = ["coordinate_computation_failed"]
    return result
