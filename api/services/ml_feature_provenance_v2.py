"""Additional, fail-closed scientific feature gates for the v2 compiler.

The caller verifies the immutable capsule and independently pinned companion
first. These checks authenticate neither a scientist nor the truth/completeness
of a calculation. No source dates are inferred from a run's creation/status.
"""
from __future__ import annotations

import hashlib
import json
import math

from models.ml_task import require
from services.ml_composition import ELEMENTS, composition_features
from services.ml_dataset_builder import _claim_composition
from services.research_release_manifest import canonical, digest

INPUT_VERSION = "ml-computed-input/1.0.0"
OUTPUT_VERSION = "ml-computed-output/1.0.0"
STRUCTURE_VERSION = "ml-structure-context/1.0.0"


def data(index, table, identifier):
    return index.get((table, identifier), {}).get("data")


def _document(index, artifacts, identifier, version):
    artifact = data(index, "evidence_artifacts", identifier)
    require(artifact and artifact["kind"] == "run_manifest"
            and artifact["schema_version"] == version and artifact["hash_status"] == "verified",
            "computed manifest metadata unavailable")
    payload = artifacts.get(artifact["bytes_sha256"])
    require(type(payload) is bytes and len(payload) <= 1_048_576
            and hashlib.sha256(payload).hexdigest() == artifact["bytes_sha256"],
            "computed manifest bytes unavailable")
    try:
        document = json.loads(payload)
        require(type(document) is dict and canonical(document) == payload
                and digest(document) == artifact["record_sha256"], "computed manifest not canonical")
    except (UnicodeError, RecursionError, TypeError) as exc:
        raise ValueError("computed manifest invalid") from exc
    return document


def _references(raw, index, *, output=False):
    require(type(raw) is list and len(raw) <= 200, "computed reference limit")
    refs = []
    for item in raw:
        require(type(item) is dict and set(item) == {"table", "row_id", "row_sha256"},
                "computed reference shape")
        require(type(item["table"]) is str and item["table"] in (
            {"event_properties"} if output else {"material_claims", "event_properties"}), "computed reference table")
        require(type(item["row_id"]) is str, "computed reference identity")
        ref = (item["table"], item["row_id"])
        require(ref in index and item["row_sha256"] == index[ref]["row_sha256"], "computed reference pin")
        refs.append(ref)
    require(refs == sorted(set(refs)), "computed references must be sorted and unique")
    return refs


def computed_lineage(index, artifacts, property_ref):
    """Read actual closed run documents; never execute embedded artifact code.

    Exact input references extend (never replace) the SQL evidence DAG. Invalid
    manifests hold admission; resolvable references are still grouped elsewhere
    via their frozen foreign keys. A missing external dependency remains an
    operator/scientific review limitation, not a proven complete calculation.
    """
    prop = data(index, *property_ref)
    event = data(index, "research_events", prop["event_id"])
    run = data(index, "research_runs", event["producer_run_id"])
    failure = {"computed_run_manifest_unresolved"}
    result = {"dependencies": [], "reason_codes": [], "run_id": event["producer_run_id"],
              "input_manifest_id": run["input_manifest_id"] if run else None,
              "output_manifest_id": run["output_manifest_id"] if run else None}
    try:
        require(run, "computed run required")
        source = _document(index, artifacts, run["input_manifest_id"], INPUT_VERSION)
        # Preserve bounded resolvable relations for conservative grouping even
        # if a different run/structure/normal-state assertion later fails. A
        # bad reference is not granted authority and strict validation below
        # still holds the feature and all dependent quantities.
        declared = source.get("dependency_results")
        if type(declared) is list and len(declared) <= 200:
            retained = set()
            for item in declared:
                try:
                    retained.update(_references([item], index))
                except (ValueError, KeyError, TypeError):
                    pass
            result["dependencies"] = sorted(retained)
        require(run and run["status"] == "completed" and run["run_kind"] in {"dft", "dfpt"},
                "completed computed run required")
        require(run["parent_run_id"] is None, "computed parent run lineage unresolved")
        output = _document(index, artifacts, run["output_manifest_id"], OUTPUT_VERSION)
        require(set(source) == {"version", "run_id", "structure_id", "structure_row_sha256",
                               "normal_state", "target_data_used", "dependency_results"}, "computed input shape")
        require(set(output) == {"version", "run_id", "result_refs"}, "computed output shape")
        require(source["version"] == INPUT_VERSION and output["version"] == OUTPUT_VERSION
                and source["run_id"] == output["run_id"] == run["id"], "computed run binding")
        structure_ref = ("structure_records", event["structure_id"])
        require(structure_ref in index and source["structure_id"] == event["structure_id"]
                and source["structure_row_sha256"] == index[structure_ref]["row_sha256"], "computed structure binding")
        # Retain exact dependencies even when the declaration itself admits
        # target use. This prevents renaming a target from erasing its lineage.
        result["dependencies"] = _references(source["dependency_results"], index)
        require(property_ref in _references(output["result_refs"], index, output=True), "computed output result missing")
        require(source["normal_state"] is True and source["target_data_used"] is False,
                "normal-state non-target declaration required")
        failure.clear()
    except (ValueError, KeyError, TypeError):
        pass
    result["reason_codes"] = sorted(failure)
    return result


def _number(value):
    return type(value) in {int, float} and abs(value) <= 1e12 and math.isfinite(value)


def applicability_reasons(index, label, input_row, applicability, *, structure_context=None):
    """Explicit exact identity or a narrowly reviewed normal-state surrogate.

    Equality of a formula or pressure is never a positive state match. A bridge
    must pin both contexts in the companion, explicitly declare its scope, and
    pass hard contradictions here. Unknown phase/field/pressure is not zero.
    """
    failures = set()
    claim, label_event, label_state = label.result_data, label.event_data, label.state_data
    if not label_event or not label_state:
        return ["feature_label_state_unresolved"]
    kind = input_row["input_kind"]
    if kind == "property":
        prop = data(index, "event_properties", input_row["input_property_id"])
        event = data(index, "research_events", prop["event_id"])
        state = data(index, "material_states", event["state_id"])
        feature_material, feature_structure = event["material_id"], event["structure_id"]
        pressure, field = state["pressure_gpa"], state["conditions"].get("magnetic_field_t")
        phase = state["conditions"].get("phase")
        if state["resolution"] not in {"resolved", "source_scoped"}:
            failures.add("feature_state_unresolved")
        if state["sample_id"] and label.sample_id and state["sample_id"] != label.sample_id:
            failures.add("feature_sample_conflict")
        same = state["id"] == label.state_id
        if applicability["mode"] == "normal_state_surrogate" and state["temperature_role"] != "simulation":
            failures.add("surrogate_requires_simulation_state")
    else:
        structure = data(index, "structure_records", input_row["input_structure_id"])
        feature_material, feature_structure = structure["material_id"], structure["id"]
        context = structure_context or {}
        pressure, field, phase = context.get("pressure_gpa"), context.get("magnetic_field_t"), context.get("phase")
        state = None
        same = feature_structure == label.structure_id and label.structure_id is not None
    if feature_material != label.material_id:
        failures.add("feature_material_conflict")
    label_conditions = label_state["conditions"]
    if pressure is not None and label_state["pressure_gpa"] is not None and pressure != label_state["pressure_gpa"]:
        failures.add("feature_pressure_conflict")
    if field is not None and claim["magnetic_field_t"] is not None and field != claim["magnetic_field_t"]:
        failures.add("feature_magnetic_field_conflict")
    label_phase = label_conditions.get("phase")
    if phase is not None and label_phase is not None and phase != label_phase:
        failures.add("feature_phase_conflict")
    if applicability["mode"] == "exact":
        if not same:
            failures.add("exact_feature_state_or_structure_mismatch")
    else:
        if not (_number(pressure) and _number(label_state["pressure_gpa"])
                and pressure == label_state["pressure_gpa"] and label_state["pressure_status"] in {"explicit_ambient", "reported"}
                and (state is None or state["pressure_status"] in {"explicit_ambient", "reported"})):
            failures.add("surrogate_requires_equal_explicit_pressure")
        if not (_number(field) and _number(claim["magnetic_field_t"]) and field == claim["magnetic_field_t"]):
            failures.add("surrogate_requires_equal_explicit_field")
        if not (type(phase) is str and phase.strip() and type(label_phase) is str and phase == label_phase):
            failures.add("surrogate_requires_equal_explicit_phase")
        # Optimized and observed structures may differ; both must actually be
        # captured/pinned. A formula-only hypothetical structure is not a bridge.
        if not (feature_structure and label.structure_id
                and data(index, "structure_records", feature_structure)
                and data(index, "structure_records", label.structure_id)):
            failures.add("surrogate_requires_both_structural_contexts")
    # The catalogue cannot replace the separately source-reviewed claim formula.
    claim_descriptor = _claim_composition(claim["raw_record"])
    catalog_descriptor = composition_features(data(index, "materials", feature_material) or {})
    if not (claim_descriptor["status"] == catalog_descriptor["status"] == "computed"
            and claim_descriptor["values"][:len(ELEMENTS)] == catalog_descriptor["values"][:len(ELEMENTS)]):
        failures.add("feature_composition_unresolved_or_conflict")
    return sorted(failures)


def validate_structure_context(context):
    keys = {"version", "coordinate_format", "geometry_scope", "source_formula", "normal_state_verified", "target_derived",
            "phase", "magnetic_field_t", "pressure_gpa"}
    require(type(context) is dict and set(context) == keys and context["version"] == STRUCTURE_VERSION,
            "structure context shape")
    require(type(context["coordinate_format"]) is str
            and context["coordinate_format"] in {"vasp-poscar/1.0.0", "sclib-coordinate/1.0.0"}
            and context["geometry_scope"] == "bulk_3d_no_vacuum"
            and context["normal_state_verified"] is True and context["target_derived"] is False, "structure context scope")
    require(type(context["source_formula"]) is str and 0 < len(context["source_formula"]) <= 512
            and type(context["phase"]) is str and bool(context["phase"].strip()) and len(context["phase"]) <= 200,
            "structure context identity")
    require(all(_number(context[key]) and 0 <= context[key] <= 1e9
                for key in ("pressure_gpa", "magnetic_field_t")), "structure context conditions")
    return context
