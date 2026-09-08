"""Complete-byte QE text force-constant preflight, not a run/ML approval.

The conventions are from pinned QEF/q-e matdyn.f90 readfc and latgen.f90.
Coordinates are read from the retained header, never inferred from a formula.
Only the ibrav=0/2 coordinate representations are implemented. Neither a
periodic coordinate JSON nor a complete matrix attests physical dimensionality,
absence of vacuum, convergence, pressure, temperature, producer or treatment.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from decimal import Decimal

from services.ml_composition import ELEMENTS, composition_features

VERSION = "qe-force-constants-import/1.0.0"
MAX_BYTES = 8 * 1024 * 1024
MAX_PHYSICAL_LINES = 120_000
MAX_ATOMS = 64
MAX_GRID_AXIS = 128
MAX_GRID_POINTS = 4096
MAX_ENTRIES = 100_000
BOHR_TO_ANGSTROM = 0.529177210903
REFERENCE_COMMIT = "770a0b2d12928a67048e2f3da8d10d057e52179e"
COORDINATE_FORMAT = "sclib-coordinate/1.0.0"
_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?"
_NUMBER_RE = re.compile(_NUMBER)
_INT_RE = re.compile(r"[+-]?[0-9]{1,8}")
_HASH_RE = re.compile(r"[0-9a-f]{64}")


class ForceConstantsImportError(ValueError):
    """Only static reason codes, never raw data or paths."""


def _require(condition, code):
    if not condition:
        raise ForceConstantsImportError(code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _number(raw):
    _require(len(raw) <= 64 and _NUMBER_RE.fullmatch(raw), "invalid_force_constant_number")
    parts = re.split("[eEdD]", raw)
    _require(len(parts) == 1 or len(parts[1].lstrip("+-")) <= 4, "numeric_exponent_limit_exceeded")
    value = float(raw.replace("D", "e").replace("d", "e"))
    _require(math.isfinite(value), "nonfinite_force_constant_number")
    _require(value != 0 or Decimal(raw.replace("D", "e").replace("d", "e")) == 0,
             "force_constant_numeric_underflow")
    return value


class _Reader:
    """Bounded physical lines; no per-character byte-offset table."""

    def __init__(self, payload):
        count = payload.count(b"\n") + payload.count(b"\r") - payload.count(b"\r\n")
        if not payload.endswith((b"\r", b"\n")):
            count += 1
        _require(count <= MAX_PHYSICAL_LINES, "force_constant_physical_line_limit")
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeError:
            raise ForceConstantsImportError("invalid_force_constant_utf8") from None
        _require(not any(char in text for char in ("\x85", "\u2028", "\u2029")),
                 "unsupported_unicode_line_separator")
        _require(not any(ord(char) < 32 and char not in "\t\r\n" for char in text),
                 "unsupported_force_constant_control_character")
        self.lines = []
        offset = 0
        for index, line in enumerate(text.splitlines(keepends=True), 1):
            raw = line.rstrip("\r\n")
            _require(len(raw) <= 4096, "force_constant_line_limit")
            if raw.strip():
                self.lines.append((index, offset, raw))
            offset += len(line.encode("utf-8"))
        self.cursor = 0

    def take(self):
        _require(self.cursor < len(self.lines), "incomplete_force_constant_file")
        line = self.lines[self.cursor]
        self.cursor += 1
        return line

    @staticmethod
    def locator(line, start=0, end=None):
        number, offset, text = line
        end = len(text) if end is None else end
        return {"line": number, "start_byte": offset + len(text[:start].encode("utf-8")),
                "end_byte": offset + len(text[:end].encode("utf-8"))}

    def numeric(self, count, *, integer_prefix=0, widths=None):
        line = self.take()
        text = line[2]
        matches = list(re.finditer(r"\S+", text))
        parts = [(match.group(), match.start(), match.end()) for match in matches]
        # QE uses fixed-format headers/positions; allow adjacent filled fields
        # without inventing separators. Ordinary list-directed files also work.
        if widths and len(text) == sum(widths):
            parts = []
            offset = 0
            for width in widths:
                field = text[offset:offset + width]
                raw = field.strip()
                begin = offset + len(field) - len(field.lstrip())
                parts.append((raw, begin, begin + len(raw)))
                offset += width
        _require(len(parts) == count, "invalid_force_constant_numeric_record")
        result = []
        for index, (raw, start, end) in enumerate(parts):
            if index < integer_prefix:
                _require(_INT_RE.fullmatch(raw), "invalid_force_constant_index")
                value = int(raw)
            else:
                value = _number(raw)
            result.append({"raw_text": raw, "value": value,
                           "locator": self.locator(line, start, end)})
        return result, line


def _det(cell):
    a, b, c = cell
    return (a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def _coordinates(header, source_formula):
    reasons = []
    if header["ibrav"] not in {0, 2}:
        reasons.append("unsupported_ibrav_coordinate_convention")
    if any(species["element"] is None for species in header["species"]):
        reasons.append("unresolved_force_constant_species")
    composition = composition_features({"formula_raw": source_formula})
    if composition["status"] != "computed":
        reasons.append("unresolved_source_formula")
    elif not any(species["element"] is None for species in header["species"]):
        counts = Counter(header["species"][site["type_index"] - 1]["element"] for site in header["sites"])
        fractions = composition["values"][:len(ELEMENTS)]
        if any(abs(counts.get(element, 0) / header["nat"] - fraction) > 1e-10
               for element, fraction in zip(ELEMENTS, fractions, strict=True)):
            reasons.append("force_constant_source_formula_mismatch")
    if reasons:
        return None, reasons, composition["provenance"]
    celldm = [number["value"] for number in header["celldm"]]
    alat = celldm[0]
    if header["ibrav"] == 2:
        _require(alat > 0, "invalid_force_constant_alat")
        cell_bohr = [[-alat / 2, 0.0, alat / 2],
                     [0.0, alat / 2, alat / 2], [-alat / 2, alat / 2, 0.0]]
    else:
        matrix = [[number["value"] for number in row] for row in header["explicit_cell"]]
        _require(alat >= 0, "invalid_force_constant_alat")
        if alat > 0:
            cell_bohr = [[value * alat for value in row] for row in matrix]
        else:
            cell_bohr = matrix
            alat = math.sqrt(math.fsum(value * value for value in matrix[0]))
            _require(math.isfinite(alat) and alat > 0, "invalid_force_constant_alat")
    cell = [[value * BOHR_TO_ANGSTROM for value in row] for row in cell_bohr]
    _require(all(math.isfinite(value) and abs(value) <= 10000 for row in cell for value in row),
             "force_constant_cell_magnitude_limit")
    determinant = _det(cell)
    norms = math.prod(math.sqrt(math.fsum(value * value for value in row)) for row in cell)
    _require(math.isfinite(determinant) and math.isfinite(norms) and determinant > max(1e-12, norms * 1e-12),
             "invalid_or_left_handed_force_constant_cell")
    sites = []
    for site in header["sites"]:
        cartesian = [value["value"] * alat * BOHR_TO_ANGSTROM for value in site["cartesian_tau"]]
        _require(all(math.isfinite(value) and abs(value) <= 1e6 for value in cartesian),
                 "force_constant_position_magnitude_limit")
        fractional = [_det([cartesian if j == i else cell[j] for j in range(3)]) / determinant for i in range(3)]
        _require(all(math.isfinite(value) and abs(value) <= 1e6 for value in fractional),
                 "force_constant_fractional_magnitude_limit")
        for earlier in sites:
            _require(any(abs((first - second) - round(first - second)) > 1e-8
                         for first, second in zip(fractional, earlier["fractional"], strict=True)),
                     "duplicate_periodic_force_constant_site")
        sites.append({"element": header["species"][site["type_index"] - 1]["element"],
                      "fractional": fractional, "occupancy": 1})
    return {"version": COORDINATE_FORMAT, "boundary_conditions": "bulk_3d_periodic",
            "cell_angstrom": cell, "sites": sites}, [], composition["provenance"]


def parse_force_constants(*, payload: bytes, expected_sha256: str, source_formula: str) -> dict:
    """Validate every declared matrix entry and derive only supported coordinates."""
    _require(type(payload) is bytes and 0 < len(payload) <= MAX_BYTES,
             "force_constant_payload_size_or_type")
    _require(type(expected_sha256) is str and _HASH_RE.fullmatch(expected_sha256),
             "invalid_force_constant_sha256")
    actual_sha = hashlib.sha256(payload).hexdigest()
    _require(actual_sha == expected_sha256, "force_constant_sha256_mismatch")
    _require(type(source_formula) is str and 0 < len(source_formula) <= 4096,
             "invalid_force_constant_source_formula")
    try:
        source_formula.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ForceConstantsImportError("invalid_force_constant_source_formula") from None
    reader = _Reader(payload)
    numbers, line = reader.numeric(9, integer_prefix=3, widths=[3, 5, 4, *([11] * 6)])
    ntyp, nat, ibrav = [value["value"] for value in numbers[:3]]
    _require(1 <= ntyp <= nat <= MAX_ATOMS and -99 <= ibrav <= 99,
             "force_constant_structure_count_limit")
    header = {"ntyp": ntyp, "nat": nat, "ibrav": ibrav,
              "locator": reader.locator(line), "celldm": numbers[3:], "explicit_cell": [],
              "species": [], "sites": []}
    if ibrav == 0:
        for _ in range(3):
            values, _ = reader.numeric(3)
            header["explicit_cell"].append(values)
    for expected in range(1, ntyp + 1):
        line = reader.take()
        match = re.fullmatch(r"\s*([0-9]{1,3})\s+(['\"])([^'\"\r\n]{1,32})\2\s+(" + _NUMBER + r")\s*", line[2])
        _require(match is not None, "invalid_force_constant_species_record")
        _require(int(match.group(1)) == expected, "force_constant_species_index_mismatch")
        label = match.group(3).strip()
        mass = _number(match.group(4))
        _require(mass > 0, "invalid_force_constant_species_mass")
        header["species"].append({"index": expected, "raw_label": match.group(3),
                                  "element": label if label in ELEMENTS else None,
                                  "mass_raw_text": match.group(4), "mass_native": mass,
                                  "mass_unit_basis": "native_rydberg_atomic_mass_units_unconverted",
                                  "locator": reader.locator(line)})
    for expected in range(1, nat + 1):
        values, line = reader.numeric(5, integer_prefix=2, widths=[5, 5, 18, 18, 18])
        atom_index, type_index = [value["value"] for value in values[:2]]
        _require(atom_index == expected and 1 <= type_index <= ntyp, "force_constant_site_index_mismatch")
        header["sites"].append({"index": atom_index, "type_index": type_index,
                                "cartesian_tau": values[2:], "unit_basis": "cartesian_in_alat",
                                "locator": reader.locator(line)})
    _require({site["type_index"] for site in header["sites"]} == set(range(1, ntyp + 1)),
             "unused_force_constant_species")
    line = reader.take()
    flags = line[2].split()
    _require(len(flags) in {1, 2} and flags[0].lower() in {"t", "f", ".true.", ".false."},
             "invalid_force_constant_electrostatic_flag")
    has_born = flags[0].lower() in {"t", ".true."}
    alpha = _number(flags[1]) if len(flags) == 2 else None
    electrostatics = {"has_born_charges": has_born, "alpha_raw_text": flags[1] if len(flags) == 2 else None,
                      "alpha": alpha, "locator": reader.locator(line), "dielectric": [], "born_charges": []}
    if has_born:
        for _ in range(3):
            values, _ = reader.numeric(3)
            electrostatics["dielectric"].append(values)
        for expected in range(1, nat + 1):
            values, _ = reader.numeric(1, integer_prefix=1)
            _require(values[0]["value"] == expected, "force_constant_born_index_mismatch")
            matrix = []
            for _ in range(3):
                values, _ = reader.numeric(3)
                matrix.append(values)
            electrostatics["born_charges"].append({"atom_index": expected, "matrix": matrix})
    header["electrostatics"] = electrostatics
    values, _ = reader.numeric(3, integer_prefix=3)
    grid = [value["value"] for value in values]
    grid_points = math.prod(grid)
    blocks = 9 * nat * nat
    expected_entries = blocks * grid_points
    _require(all(1 <= axis <= MAX_GRID_AXIS for axis in grid) and grid_points <= MAX_GRID_POINTS
             and expected_entries <= MAX_ENTRIES, "force_constant_matrix_inventory_limit")
    # Every block and lattice address must appear once, in the actual native
    # traversal order. Merely reading the right count would accept duplicates.
    first_line = reader.lines[reader.cursor] if reader.cursor < len(reader.lines) else None
    inventory_hash = hashlib.sha256(b"qe-fc-inventory/1.0.0\n")
    column_count = None
    entries = 0
    negatives = 0
    for i in range(1, 4):
        for j in range(1, 4):
            for na in range(1, nat + 1):
                for nb in range(1, nat + 1):
                    values, line = reader.numeric(4, integer_prefix=4)
                    block = [i, j, na, nb]
                    _require([value["value"] for value in values] == block,
                             "force_constant_block_index_mismatch")
                    for m3 in range(1, grid[2] + 1):
                        for m2 in range(1, grid[1] + 1):
                            for m1 in range(1, grid[0] + 1):
                                # Determine the supported short-range-only or
                                # short+long-range layout from the first row.
                                _require(reader.cursor < len(reader.lines), "incomplete_force_constant_file")
                                fields = len(reader.lines[reader.cursor][2].split())
                                _require(fields in {4, 5}, "unsupported_force_constant_matrix_layout")
                                if column_count is None:
                                    column_count = fields
                                _require(fields == column_count, "inconsistent_force_constant_matrix_layout")
                                values, line = reader.numeric(fields, integer_prefix=3)
                                address = [m1, m2, m3]
                                _require([value["value"] for value in values[:3]] == address,
                                         "force_constant_lattice_index_mismatch")
                                inventory_hash.update(_canonical([*block, *address, *[value["raw_text"] for value in values[3:]]]) + b"\n")
                                negatives += sum(value["value"] < 0 for value in values[3:])
                                entries += 1
    _require(reader.cursor == len(reader.lines), "unexpected_force_constant_trailing_records")
    _require(entries == expected_entries, "incomplete_force_constant_matrix_inventory")
    coordinates, reasons, composition = _coordinates(header, source_formula)
    if column_count == 5:
        reasons.append("long_range_force_constant_context_unresolved")
        coordinates = None
    coordinate_sha = hashlib.sha256(_canonical(coordinates)).hexdigest() if coordinates is not None else None
    return {
        "version": VERSION, "status": "quarantined" if reasons else "parsed", "reason_codes": reasons,
        "source_sha256": actual_sha, "source_formula": source_formula,
        "coordinates": coordinates, "coordinate_sha256": coordinate_sha, "coordinate_format": COORDINATE_FORMAT,
        "header": header,
        "inventory": {"grid": grid, "block_count": blocks, "entry_count": entries,
                      "expected_entry_count": expected_entries, "coverage_complete": True,
                      "layout": "short_and_long_range" if column_count == 5 else "short_range_only",
                      "negative_value_count": negatives, "matrix_inventory_sha256": inventory_hash.hexdigest(),
                      "inventory_hash_version": "qe-fc-inventory/1.0.0",
                      "force_constant_unit_basis": "native_values_preserved_without_unit_conversion",
                      "data_locator": {"line": first_line[0], "start_byte": first_line[1],
                                       "end_byte": reader.locator(line)["end_byte"]}},
        "normalization": {"bohr_to_angstrom": BOHR_TO_ANGSTROM,
                          "coordinate_basis": "periodic_representation_not_bulk_no_vacuum_attestation",
                          "formula_comparison": "atomic_fractions_not_material_identity", "composition": composition},
        "format_reference": {"repository": "QEF/q-e", "commit": REFERENCE_COMMIT, "producer_version": None},
        "limitations": ["no_bulk_or_no_vacuum_review", "no_pressure_or_temperature_inference",
                        "no_execution_convergence_or_cost_attestation", "no_harmonic_or_anharmonic_treatment_inference",
                        "no_force_constant_to_frequency_recomputation", "no_mass_override_or_isotope_attestation"],
        "authority": {"scientific_accepted": False, "ml_training_approved": False, "execution_attested": False},
    }
