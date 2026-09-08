"""Deterministic composition-only features, not a claim of material identity.

No Tc, pressure, sample state, reported outcome, or cached descriptor is used
as a feature. Exact means this parser accounts for the formula, not scientific
acceptance. Isotope/variable/site resolution and reviewed identity stay upstream.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from importlib.resources import files

from services._composition import formula_enrichment as parser

VERSION = "ml-composition/1.0.0"
ELEMENTS = tuple(sorted(parser._ATOMIC_MASS))
FEATURE_NAMES = tuple("atomic_fraction_" + element for element in ELEMENTS) + (
    "n_elements", "atoms_per_formula", "molar_mass_g_mol",
)
MAX_RAW_FORMULA_LENGTH = 4096  # Admission bound, not a replacement grammar.
MAX_SOURCE_RECORDS = 1000
MAX_RECORDS_JSON_BYTES = 1_048_576
_SOURCE_SHA256 = {
    name: hashlib.sha256(
        files("services._composition").joinpath(name + ".py").read_bytes()
    ).hexdigest()
    for name in ("formula_enrichment", "formula_validator")
}


def _invalid_json(*_args):
    raise ValueError("invalid_source_records")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_source_records")
        result[key] = value
    return result


def _bounded_formula(value):
    if value is not None and (
        type(value) is not str or len(value) > MAX_RAW_FORMULA_LENGTH
    ):
        raise ValueError("invalid_formula_input")
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("invalid_formula_input") from None
    return value


def _parser_input(material: dict) -> tuple[str, dict]:
    if type(material) is not dict:
        raise ValueError("invalid_material_input")
    # Inspect only fields used by the audited identity guard, never labels.
    selected = {}
    for key in ("formula_raw", "formula", "formula_normalized"):
        selected[key] = _bounded_formula(material.get(key))
    raw = selected["formula_raw"] or selected["formula"] or selected["formula_normalized"] or ""
    records = material.get("records")
    if records is None:
        records = []
    if isinstance(records, str):
        try:
            if len(records.encode("utf-8")) > MAX_RECORDS_JSON_BYTES:
                raise ValueError("invalid_source_records")
            records = json.loads(
                records, object_pairs_hook=_unique_object, parse_constant=_invalid_json,
            )
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError("invalid_source_records") from None
    if type(records) is not list or len(records) > MAX_SOURCE_RECORDS:
        raise ValueError("invalid_source_records")
    selected_records = []
    for record in records:
        if type(record) is not dict:
            raise ValueError("invalid_source_records")
        extraction = record.get("raw_extraction")
        if extraction is None:
            extraction = {}
        if type(extraction) is not dict:
            raise ValueError("invalid_source_records")
        selected_records.append({
            "formula_raw": _bounded_formula(record.get("formula_raw")),
            "formula": _bounded_formula(record.get("formula")),
            "raw_extraction": {
                key: _bounded_formula(extraction.get(key))
                for key in ("formula_raw", "formula")
            },
        })
    selected["records"] = selected_records
    return raw, selected


def composition_features(material: dict) -> dict:
    """Return the fixed 121-column descriptor or an all-missing inventory.

    Mass uses the parser's local standard-weight/conventional-mass table, not
    isotope-specific masses. Integer counts reduce by their greatest common
    divisor; fractional site occupancies retain the parser's formula-unit scale.
    Input hashes are the audited parser's NFC-tagged hashes, not raw-file hashes.
    Own packaged source hashes identify the implementation, not external review.
    """
    raw = None
    try:
        raw, parser_input = _parser_input(material)
        # Match the audited parser's ordinary Decimal context without inheriting
        # unrelated caller changes to process/thread-local precision or traps.
        with localcontext(Context(
            prec=28, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
            capitals=1, clamp=0, traps=[InvalidOperation, DivisionByZero, Overflow],
        )):
            descriptor = parser.enrich_material_composition(parser_input)
    except (ValueError, ArithmeticError, RecursionError) as exc:
        # No raw formula, source record, target, or arbitrary exception is logged.
        code = str(exc) if str(exc) in {
            "invalid_material_input", "invalid_formula_input", "invalid_source_records",
        } else "composition_computation_failed"
        if type(material) is dict:
            candidate = material.get("formula_raw") or material.get("formula") or material.get("formula_normalized")
            if type(candidate) is str and len(candidate) <= MAX_RAW_FORMULA_LENGTH:
                try:
                    candidate.encode("utf-8", errors="strict")
                    raw = candidate
                except UnicodeError:
                    pass
        descriptor = parser._empty_result(raw)
        descriptor["errors"] = [code]
    values = [None] * len(FEATURE_NAMES)
    status = descriptor["composition_status"]
    reasons = list(descriptor["errors"])
    if status == "exact":
        candidate_values = [
            descriptor["atomic_fractions"].get(element, 0.0) for element in ELEMENTS
        ] + [descriptor[key] for key in ("n_elements", "n_atoms_fu", "molar_mass_g_mol")]
        if all(type(value) in (int, float) and math.isfinite(value) for value in candidate_values):
            values = [float(value) for value in candidate_values]
        else:
            status = "invalid"
            reasons = ["nonfinite_composition_feature"]
    elif not reasons:
        reasons = ["composition_" + status + "_requires_resolution"]
    return {
        "version": VERSION,
        "status": "computed" if status == "exact" else "unavailable",
        "formula_raw": raw,
        "composition_status": status,
        "feature_names": list(FEATURE_NAMES),
        "values": values,
        "reason_codes": reasons,
        "provenance": {
            "parser_name": descriptor["parser_name"],
            "parser_version": descriptor["parser_version"],
            "input_hash": descriptor["input_hash"],
            "source_sha256": dict(_SOURCE_SHA256),
            "formula_unit_basis": "parser_reduced_integer_or_preserved_fractional",
        },
    }
