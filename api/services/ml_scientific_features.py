"""Point-valued computed normal-state feature semantics, with no authority grant.

This pure layer checks actual supplied rows and an exact task-pinned protocol.
The v2 compiler separately verifies frozen bytes, source occurrence, chronology,
transitive target leakage and reviewed label-state applicability. A matching
declaration here does not authenticate those facts or permit model training.
"""

from __future__ import annotations

import hashlib
import math
from importlib.resources import files
from uuid import UUID

from models.ml_task_v2 import (
    protocol_sha256,
    validate_scientific_context,
    validate_selector,
)
from services.research_release_manifest import canonical

VERSION = "ml-scientific-features/1.0.0"
MAX_ROW_BYTES = 1_048_576
MAX_ABSOLUTE_VALUE = 1e12  # Representation safety bound, not a scientific cutoff.


def _source_hashes():
    return {
        "ml_scientific_features": hashlib.sha256(files("services").joinpath("ml_scientific_features.py").read_bytes()).hexdigest(),
        "ml_task_v2": hashlib.sha256(files("models").joinpath("ml_task_v2.py").read_bytes()).hexdigest(),
    }


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _finite(value):
    return type(value) in {int, float} and abs(value) <= MAX_ABSOLUTE_VALUE and math.isfinite(value)


def _material_key(value):
    # Legacy catalogue materials use String(100), unlike research row UUIDs.
    return type(value) is str and 0 < len(value) <= 100 and value.strip() == value and not any(
        ord(character) < 32 or ord(character) == 127 for character in value
    )


def protocol_data_template(property_key):
    """An intentionally incomplete template for retained numerical protocol data."""
    if property_key in {"formation_energy_per_atom", "energy_above_hull"}:
        return {"reference_ensemble": {
            "version": "ml-reference-ensemble/1.0.0",
            "kind": "elemental_references" if property_key == "formation_energy_per_atom" else "convex_hull_ensemble",
            "thermodynamic_potential": None, "pressure_gpa": None, "temperature_k": None,
            "energy_unit": "eV/atom", "entries": [],
        }}
    if property_key in {"electron_phonon_lambda", "omega_log", "phonon_min_frequency"}:
        result = {"q_sampling": {"version": "ml-q-sampling/1.0.0",
                  "coordinate_system": "fractional_reciprocal", "mode": None,
                  "grid": None, "offset": None, "points": None, "weights": None}}
        if property_key != "phonon_min_frequency":
            result["broadening_scheme"] = {"version": "ml-spectral-broadening/1.0.0",
                "method": None, "electronic_width_ev": None, "phonon_width_thz": None,
                "integration_rule": None, "frequency_grid_thz": []}
        return result
    if property_key in {"band_gap", "dos_at_fermi"}:
        return {}
    raise ValueError("unsupported_protocol_data_property")


def _assert(condition):
    if not condition:
        raise ValueError("invalid_retained_protocol_data")


def validate_protocol_data(protocol, settings, state, *, source_formula=None):
    """Check closed actual captured data behind every protocol-detail digest.

    This verifies declared numerical/reference contents, not that reference
    energies or q-sampling are scientifically converged or independently known.
    Full run manifests/source review remain a separate mandatory compiler gate.
    """
    key, details = protocol["property_key"], protocol["details"]
    data = settings.get("scientific_protocol_data")
    template = protocol_data_template(key)
    _assert(type(data) is dict and set(data) == set(template))
    for name, value in data.items():
        _assert(type(value) is dict and set(value) == set(template[name]))
        _assert(value["version"] == template[name]["version"])
        _assert(hashlib.sha256(canonical(value)).hexdigest() == details[name + "_sha256"])
    if "reference_ensemble" in data:
        from services.ml_composition import ELEMENTS, composition_features

        reference = data["reference_ensemble"]
        _assert(reference["kind"] == template["reference_ensemble"]["kind"]
                and reference["energy_unit"] == "eV/atom"
                and reference["thermodynamic_potential"] == details["thermodynamic_potential"])
        for field in ("pressure_gpa", "temperature_k"):
            _assert(_finite(reference[field]) and reference[field] >= 0
                    and _finite(state.get(field)) and reference[field] == state[field])
        entries = reference["entries"]
        _assert(type(entries) is list and 0 < len(entries) <= 128)
        names = set()
        covered_elements = set()
        for entry in entries:
            _assert(type(entry) is dict and set(entry) == {"reference_id", "formula", "energy_per_atom"})
            _assert(type(entry["reference_id"]) is str and 0 < len(entry["reference_id"]) <= 120
                    and entry["reference_id"] not in names)
            names.add(entry["reference_id"])
            _assert(type(entry["formula"]) is str and len(entry["formula"]) <= 200
                    and _finite(entry["energy_per_atom"]))
            composition = composition_features({"formula_raw": entry["formula"]})
            _assert(composition["status"] == "computed")
            covered_elements.update(element for element, fraction in zip(
                ELEMENTS, composition["values"][:len(ELEMENTS)], strict=True,
            ) if fraction > 0)
            if key == "formation_energy_per_atom":
                _assert(composition["values"][-3] == 1)
        source_composition = composition_features({"formula_raw": source_formula})
        _assert(type(source_formula) is str and source_composition["status"] == "computed")
        source_elements = {element for element, fraction in zip(
            ELEMENTS, source_composition["values"][:len(ELEMENTS)], strict=True,
        ) if fraction > 0}
        _assert(source_elements <= covered_elements)
    if "q_sampling" in data:
        q = data["q_sampling"]
        _assert(q["coordinate_system"] == "fractional_reciprocal" and type(q["mode"]) is str)
        if q["mode"] == "grid":
            _assert(type(q["grid"]) is list and len(q["grid"]) == 3
                    and all(type(value) is int and 1 <= value <= 512 for value in q["grid"]))
            _assert(type(q["offset"]) is list and len(q["offset"]) == 3
                    and all(_finite(value) and 0 <= value < 1 for value in q["offset"]))
            _assert(q["points"] is None and q["weights"] is None)
        elif q["mode"] == "explicit":
            points, weights = q["points"], q["weights"]
            _assert(q["grid"] is None and q["offset"] is None
                    and type(points) is list and 0 < len(points) <= 4096
                    and type(weights) is list and len(weights) == len(points))
            _assert(all(type(point) is list and len(point) == 3
                        and all(_finite(value) and 0 <= value < 1 for value in point) for point in points))
            _assert(len({tuple(point) for point in points}) == len(points))
            _assert(all(_finite(weight) and 0 < weight <= 1 for weight in weights)
                    and abs(math.fsum(weights) - 1) <= 1e-10)
        else:
            _assert(False)
    if "broadening_scheme" in data:
        broadening = data["broadening_scheme"]
        method = broadening["method"]
        _assert(type(method) is str and method in {"gaussian", "lorentzian", "tetrahedron"})
        for field in ("electronic_width_ev", "phonon_width_thz"):
            value = broadening[field]
            _assert(value is None if method == "tetrahedron" else _finite(value) and value > 0)
        _assert(type(broadening["integration_rule"]) is str
                and broadening["integration_rule"] in {"trapezoidal", "adaptive", "tetrahedron"})
        _assert((method == "tetrahedron") == (broadening["integration_rule"] == "tetrahedron"))
        grid = broadening["frequency_grid_thz"]
        _assert(type(grid) is list and 2 <= len(grid) <= 4096
                and all(_finite(value) and value > 0 for value in grid)
                and all(left < right for left, right in zip(grid, grid[1:], strict=False)))
    return data


def _row(value):
    if type(value) is not dict or not _uuid(value.get("id")):
        raise ValueError("invalid_feature_row")
    encoded = canonical(value)
    if len(encoded) > MAX_ROW_BYTES:
        raise ValueError("feature_row_budget")
    return {"id": value["id"], "row_sha256": hashlib.sha256(encoded).hexdigest()}


def validate_property_feature(property, event, state, run, structure, selector, scientific_context, *, source_formula=None):
    """Return one exact feature or explicit missingness; never infer a proxy.

    Bad task selectors raise ValueError before row selection. Bad evidence yields
    an unavailable result, with no raw source text or arbitrary exception output.
    The caller must independently verify run manifests and context review bytes.
    There is deliberately no target-value argument or learned transformation.
    source_formula is the compiler's exact claim-bound formula, not a catalogue
    guess. It is required for stability-reference coverage and DOS formula-unit
    semantics; a parsed basis does not independently prove reported DOS scaling.
    """
    validate_selector(selector)
    result = {
        "version": VERSION, "status": "unavailable", "feature_key": selector["feature_key"],
        "property_key": selector["property_key"], "value": None, "unit": selector["unit"],
        "reason_codes": [],
        "provenance": {"implementation_sha256": _source_hashes(),
                       "protocol_sha256": selector["protocol_sha256"],
                       "scientific_context_sha256": None, "bindings": {},
                       "source_formula": None, "source_composition": None,
                       "normalization_scope": "reviewed_declaration_not_independently_recomputed"},
        "scientific_acceptance": False, "ml_training_eligible": False,
    }
    reasons = result["reason_codes"]
    try:
        result["provenance"]["bindings"] = {
            name: _row(value) for name, value in (
                ("property", property), ("event", event), ("state", state),
                ("run", run), ("structure", structure),
            )
        }
    except (ValueError, TypeError, OverflowError, RecursionError):
        reasons.append("invalid_or_unbounded_feature_rows")
        return result
    try:
        validate_scientific_context(scientific_context)
        context_bytes = canonical(scientific_context)
        if len(context_bytes) > MAX_ROW_BYTES:
            raise ValueError("context_budget")
        protocol = scientific_context["protocol"]
        result["provenance"]["scientific_context_sha256"] = hashlib.sha256(context_bytes).hexdigest()
    except (ValueError, TypeError, OverflowError, RecursionError):
        reasons.append("invalid_or_unresolved_scientific_context")
        return result
    if protocol_sha256(protocol) != selector["protocol_sha256"]:
        reasons.append("protocol_pin_mismatch")
    if protocol["property_key"] != selector["property_key"] or protocol["semantics_profile"] != selector["semantics_profile"]:
        reasons.append("protocol_property_mismatch")
    if source_formula is not None or selector["property_key"] in {
        "formation_energy_per_atom", "energy_above_hull", "dos_at_fermi",
    }:
        from services.ml_composition import composition_features

        source_composition = composition_features({"formula_raw": source_formula})
        if type(source_formula) is not str or source_composition["status"] != "computed":
            reasons.append("property_source_formula_unresolved")
        else:
            result["provenance"]["source_formula"] = source_formula
            result["provenance"]["source_composition"] = source_composition["provenance"]
    if any(property.get(field) != selector[field] for field in (
        "property_key", "registry_version", "component_key", "unit",
    )):
        reasons.append("actual_property_selector_mismatch")
    if property.get("event_id") != event["id"]:
        reasons.append("property_event_mismatch")
    value = property.get("value")
    if property.get("relation") != "exact" or not _finite(value) or any(
        property.get(field) is not None for field in ("lower", "upper")
    ):
        reasons.append("exact_finite_property_required")
    elif selector["property_key"] not in {"formation_energy_per_atom", "phonon_min_frequency"} and value < 0:
        reasons.append("invalid_property_sign")
    elif selector["property_key"] == "omega_log" and value == 0:
        reasons.append("undefined_logarithmic_frequency")
    if event.get("event_type") != "calculation" or event.get("knowledge_origin") != "Computed":
        reasons.append("computed_calculation_required")
    if event.get("review_status") != "approved" or event.get("validity_status") != "accepted" or not _uuid(event.get("decision_artifact_id")):
        reasons.append("declared_event_review_required")
    if event.get("state_id") != state["id"] or event.get("material_id") != state.get("material_id") or not _material_key(state.get("material_id")):
        reasons.append("input_state_material_mismatch")
    pressure, temperature = state.get("pressure_gpa"), state.get("temperature_k")
    if type(state.get("resolution")) is not str or state["resolution"] not in {"resolved", "source_scoped"}:
        reasons.append("input_state_unresolved")
    if type(state.get("pressure_status")) is not str or state["pressure_status"] not in {"reported", "explicit_ambient"} or not _finite(pressure) or pressure < 0:
        reasons.append("input_pressure_unresolved")
    elif state.get("pressure_status") == "explicit_ambient" and pressure != 0:
        reasons.append("input_pressure_contradiction")
    if type(state.get("temperature_role")) is not str or state["temperature_role"] not in {"simulation", "measurement"} or not _finite(temperature) or temperature < 0:
        reasons.append("input_temperature_unresolved")
    if structure.get("id") != event.get("structure_id") or structure.get("material_id") != event.get("material_id"):
        reasons.append("input_structure_material_mismatch")
    if structure.get("structure_kind") != "coordinates" or structure.get("coordinate_artifact_kind") != "structure" or not _uuid(structure.get("artifact_id")):
        reasons.append("actual_coordinate_structure_required")
    if event.get("producer_run_id") != run["id"] or run.get("status") != "completed" or run.get("run_kind") != protocol["method_kind"]:
        reasons.append("completed_exact_producer_run_required")
    if not all(_uuid(run.get(key)) for key in ("input_manifest_id", "output_manifest_id")):
        reasons.append("producer_manifests_required")
    settings = run.get("settings")
    if type(settings) is not dict or run.get("code_version") != protocol["code_version"] or run.get("settings_schema_version") != protocol["settings_schema_version"]:
        reasons.append("producer_protocol_metadata_mismatch")
    elif hashlib.sha256(canonical(settings)).hexdigest() != protocol["settings_sha256"]:
        reasons.append("producer_settings_hash_mismatch")
    if type(settings) is dict:
        try:
            validate_protocol_data(protocol, settings, state, source_formula=source_formula)
        except (ValueError, TypeError, ArithmeticError, RecursionError):
            reasons.append("retained_protocol_data_unresolved_or_mismatched")
    if not reasons:
        result["status"] = "admitted"
        result["value"] = float(value)
    return result
