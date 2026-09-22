"""Pure v2 semantics regressions; run via the disposable API test launcher."""

import copy
import hashlib
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

from models.ml_task import default_task
from models.ml_task_v2 import (
    CONTEXT_VERSION,
    STRUCTURE_FEATURES,
    UNITS,
    default_task_v2,
    protocol_sha256,
    protocol_template,
    selector_for,
    validate_protocol,
    validate_scientific_context,
    validate_selector,
    validate_task_v2,
)
from services.ml_scientific_features import (
    protocol_data_template,
    validate_protocol_data,
)
from services.ml_scientific_features import (
    validate_property_feature as _validate_property_feature,
)
from services.research_release_manifest import canonical


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def uid(number):
    return str(UUID(int=number))


def validate_property_feature(*args, source_formula="MgB2"):
    """Tests supply an explicit synthetic claim-bound formula, never a target."""
    return _validate_property_feature(*args, source_formula=source_formula)


def feature_case(key="band_gap"):
    """Explicit synthetic declarations, never externally reviewed measurements."""
    data = protocol_data_template(key)
    if "reference_ensemble" in data:
        data["reference_ensemble"].update(
            thermodynamic_potential="energy", pressure_gpa=0.0, temperature_k=0.0,
            entries=[{"reference_id": "synthetic-Mg", "formula": "Mg", "energy_per_atom": -1.0},
                     {"reference_id": "synthetic-B", "formula": "B2", "energy_per_atom": -2.0}],
        )
    if "q_sampling" in data:
        data["q_sampling"].update(mode="grid", grid=[4, 4, 4], offset=[0.0, 0.0, 0.0])
    if "broadening_scheme" in data:
        data["broadening_scheme"].update(method="gaussian", electronic_width_ev=0.01,
            phonon_width_thz=0.1, integration_rule="trapezoidal", frequency_grid_thz=[0.01, 1.0, 10.0])
    settings = {"functional": "synthetic-PBE", "scientific_protocol_data": data}
    protocol = protocol_template(key)
    protocol.update(method_name="synthetic-code", code_version="synthetic/1",
                    settings_schema_version="synthetic-settings/1", settings_sha256=digest(settings))
    if key in {"formation_energy_per_atom", "energy_above_hull"}:
        protocol["details"].update(thermodynamic_potential="energy", nuclear_treatment="static_lattice")
    elif key == "band_gap":
        protocol["details"].update(spin_treatment="non_spin_polarized", occupation_treatment="zero_temperature")
    elif key == "dos_at_fermi":
        protocol["details"].update(broadening_method="gaussian", broadening_ev=0.01)
    else:
        protocol["details"]["nuclear_treatment"] = "harmonic"
    for name, value in data.items():
        protocol["details"][name + "_sha256"] = digest(value)
    selector = selector_for(protocol)
    prop = {"id": uid(1), "event_id": uid(2), "property_key": key, "registry_version": "rv2/1",
            "component_key": "bulk", "relation": "exact", "value": 1.5, "lower": None,
            "upper": None, "unit": UNITS[key], "uncertainty": {}, "raw": {}}
    event = {"id": uid(2), "material_id": uid(8), "state_id": uid(3), "structure_id": uid(5),
             "event_type": "calculation", "knowledge_origin": "Computed", "producer_run_id": uid(4),
             "review_status": "approved", "validity_status": "accepted", "decision_artifact_id": uid(6)}
    state = {"id": uid(3), "material_id": uid(8), "resolution": "resolved",
             "pressure_status": "explicit_ambient", "pressure_gpa": 0.0,
             "temperature_role": "simulation", "temperature_k": 0.0}
    run = {"id": uid(4), "run_kind": protocol["method_kind"], "status": "completed",
           "code_version": protocol["code_version"], "settings_schema_version": protocol["settings_schema_version"],
           "settings": settings, "input_manifest_id": uid(10), "output_manifest_id": uid(11)}
    structure = {"id": uid(5), "material_id": uid(8), "structure_kind": "coordinates",
                 "coordinate_artifact_kind": "structure", "artifact_id": uid(9)}
    context = {"version": CONTEXT_VERSION, "normal_state": True, "target_derived": False, "protocol": protocol}
    return [prop, event, state, run, structure, selector, context]


@pytest.mark.parametrize("key", sorted(UNITS))
def test_each_seven_exact_computed_profile_is_bound_and_deterministic(key):
    args = feature_case(key)
    before = copy.deepcopy(args)
    first = validate_property_feature(*args)
    assert args == before
    assert first == validate_property_feature(*args)
    assert first["status"] == "admitted", first
    assert first["value"] == 1.5 and first["unit"] == UNITS[key]
    assert first["reason_codes"] == []
    assert first["scientific_acceptance"] is first["ml_training_eligible"] is False
    assert first["provenance"]["scientific_context_sha256"] == digest(args[-1])
    assert first["provenance"]["protocol_sha256"] == protocol_sha256(args[-1]["protocol"])
    for name, row in zip(("property", "event", "state", "run", "structure"), args[:5], strict=True):
        assert first["provenance"]["bindings"][name] == {"id": row["id"], "row_sha256": digest(row)}
    assert all(len(value) == 64 for value in first["provenance"]["implementation_sha256"].values())


@pytest.mark.parametrize("key", sorted(UNITS))
def test_protocol_templates_are_explicitly_unready_not_science_defaults(key):
    with pytest.raises(ValueError):
        validate_protocol(protocol_template(key))


def test_nested_v1_task_unmodified_and_sorted_selector_inventory():
    task = default_task_v2()
    assert task["label_task"] == default_task()
    task["physical_features"] = [feature_case(key)[-2] for key in sorted(UNITS)]
    task["structure_features"] = list(STRUCTURE_FEATURES)
    before = copy.deepcopy(task)
    assert validate_task_v2(task) == before == task
    task["label_task"]["feature_budget"] = "composition_conditions"
    assert validate_task_v2(task)["label_task"]["feature_budget"] == "composition_conditions"


@pytest.mark.parametrize("update", [
    {"version": "ml-task/1.0.0"}, {"task_id": True}, {"task_id": "../secret"},
    {"scientific_acceptance": True}, {"state_policy": "same_formula"},
    {"cohort_policy": "resplit_each_subset"}, {"information_regime": "retrospective"},
    {"missingness": "zero"}, {"physical_features": {}}, {"structure_features": ["space_group"]},
    {"structure_features": ["volume_per_atom_a3"]}, {"structure_features": True},
])
def test_task_unknown_fields_modes_and_partial_structure_budgets_fail_closed(update):
    task = default_task_v2()
    task.update(update)
    with pytest.raises(ValueError):
        validate_task_v2(task)


@pytest.mark.parametrize("feature", ["tc_kelvin", "superfluid_stiffness", "rps_score", "Tc", "xi_nm", "gap_from_tc"])
def test_target_superconducting_response_and_priority_aliases_are_not_physical_features(feature):
    selector = feature_case()[-2]
    selector["property_key"] = selector["feature_key"] = feature
    with pytest.raises(ValueError):
        validate_selector(selector)


@pytest.mark.parametrize("field,value", [
    ("feature_key", "renamed_tc"), ("knowledge_origin", "Observed"), ("knowledge_origin", "AI-Proposed"),
    ("unit", "meV"), ("registry_version", "rv2/2"), ("component_key", True),
    ("component_key", "sigma_band"),
    ("protocol_sha256", "A" * 64), ("protocol_sha256", None), ("semantics_profile", "universal"),
])
def test_selector_strict_closed_types_units_origins_and_profiles(field, value):
    selector = feature_case()[-2]
    selector[field] = value
    with pytest.raises(ValueError):
        validate_selector(selector)


def test_duplicate_unsorted_and_oversized_selectors_are_not_silently_deduplicated():
    task = default_task_v2()
    first, second = feature_case("band_gap")[-2], feature_case("omega_log")[-2]
    for selectors in ([first, first], [second, first], [first] * 8):
        task["physical_features"] = selectors
        with pytest.raises(ValueError):
            validate_task_v2(task)


@pytest.mark.parametrize("field,value", [("normal_state", 1), ("target_derived", 0),
    ("normal_state", False), ("target_derived", True), ("unknown", "field")])
def test_review_context_requires_strict_declarations_without_granting_authority(field, value):
    args = feature_case()
    args[-1][field] = value
    with pytest.raises(ValueError):
        validate_scientific_context(args[-1])
    result = validate_property_feature(*args)
    assert result["status"] == "unavailable"
    assert result["value"] is None


@pytest.mark.parametrize("index,field,value,reason", [
    (0, "unit", "meV", "actual_property_selector_mismatch"),
    (0, "property_key", "rps_score", "actual_property_selector_mismatch"),
    (0, "event_id", uid(99), "property_event_mismatch"),
    (0, "relation", "lt", "exact_finite_property_required"),
    (0, "lower", 0.1, "exact_finite_property_required"),
    (0, "value", True, "exact_finite_property_required"),
    (0, "value", 10**1000, "exact_finite_property_required"),
    (0, "value", -1, "invalid_property_sign"),
    (1, "knowledge_origin", "Observed", "computed_calculation_required"),
    (1, "event_type", "priority_assessment", "computed_calculation_required"),
    (1, "review_status", "pending", "declared_event_review_required"),
    (1, "validity_status", "retracted", "declared_event_review_required"),
    (1, "decision_artifact_id", None, "declared_event_review_required"),
    (1, "state_id", uid(99), "input_state_material_mismatch"),
    (1, "material_id", uid(99), "input_state_material_mismatch"),
    (2, "resolution", "unresolved", "input_state_unresolved"),
    (2, "resolution", {}, "input_state_unresolved"),
    (2, "pressure_status", "not_reported", "input_pressure_unresolved"),
    (2, "pressure_status", [], "input_pressure_unresolved"),
    (2, "pressure_gpa", None, "input_pressure_unresolved"),
    (2, "pressure_gpa", 1.0, "input_pressure_contradiction"),
    (2, "temperature_k", None, "input_temperature_unresolved"),
    (2, "temperature_role", "synthesis", "input_temperature_unresolved"),
    (2, "temperature_role", {}, "input_temperature_unresolved"),
    (3, "status", "failed", "completed_exact_producer_run_required"),
    (3, "run_kind", "ml_prediction", "completed_exact_producer_run_required"),
    (3, "output_manifest_id", None, "producer_manifests_required"),
    (3, "code_version", "different/2", "producer_protocol_metadata_mismatch"),
    (3, "settings", {}, "producer_settings_hash_mismatch"),
    (4, "structure_kind", "prototype", "actual_coordinate_structure_required"),
    (4, "material_id", uid(99), "input_structure_material_mismatch"),
])
def test_typed_actual_rows_not_field_alias_or_declared_context_control_admission(index, field, value, reason):
    args = feature_case()
    args[index][field] = value
    result = validate_property_feature(*args)
    assert result["status"] == "unavailable" and result["value"] is None
    assert reason in result["reason_codes"]


@pytest.mark.parametrize("bad", [None, [], True, {}, {"id": "not-uuid"}, {"id": uid(1), "x": float("nan")}])
@pytest.mark.parametrize("index", range(5))
def test_malformed_rows_never_raise_or_leak_partial_values(index, bad):
    args = feature_case()
    args[index] = bad
    result = validate_property_feature(*args)
    assert result["status"] == "unavailable" and result["value"] is None
    assert result["reason_codes"] == ["invalid_or_unbounded_feature_rows"]


@pytest.mark.parametrize("key", ["formation_energy_per_atom", "phonon_min_frequency"])
def test_signed_energy_and_imaginary_phonon_frequency_are_not_replaced_with_zero(key):
    args = feature_case(key)
    args[0]["value"] = -2.5
    result = validate_property_feature(*args)
    assert result["status"] == "admitted" and result["value"] == -2.5


def test_zero_logarithmic_frequency_is_undefined_and_protocol_changes_do_not_pool():
    args = feature_case("omega_log")
    args[0]["value"] = 0
    assert "undefined_logarithmic_frequency" in validate_property_feature(*args)["reason_codes"]
    args = feature_case()
    args[-1]["protocol"]["details"]["spin_treatment"] = "spin_orbit"
    assert "protocol_pin_mismatch" in validate_property_feature(*args)["reason_codes"]


def test_real_catalogue_string_material_ids_are_not_misread_as_research_uuids():
    args = feature_case()
    for index in (1, 2, 4):
        args[index]["material_id"] = "ml-task:synthetic-MgB2"
    assert validate_property_feature(*args)["status"] == "admitted"


@pytest.mark.parametrize("key", ["formation_energy_per_atom", "energy_above_hull", "electron_phonon_lambda", "omega_log", "phonon_min_frequency"])
def test_hash_only_reference_or_spectral_metadata_is_not_retained_protocol_data(key):
    args = feature_case(key)
    args[3]["settings"]["scientific_protocol_data"] = {}
    # Even repinning settings cannot bypass missing actual typed reference data.
    args[-1]["protocol"]["settings_sha256"] = digest(args[3]["settings"])
    args[-2] = selector_for(args[-1]["protocol"])
    result = validate_property_feature(*args)
    assert "retained_protocol_data_unresolved_or_mismatched" in result["reason_codes"]


def test_reference_numeric_state_binding_and_actual_reference_data_types():
    args = feature_case("formation_energy_per_atom")
    protocol, settings, state = args[-1]["protocol"], args[3]["settings"], args[2]
    state["pressure_gpa"] = 0  # SQL JSON int/float representation is not physical drift.
    assert validate_protocol_data(protocol, settings, state, source_formula="MgB2")
    for mutation in ({"pressure_gpa": 1}, {"entries": [{"synthetic": True}]},
                     {"entries": [{"reference_id": "alloy", "formula": "MgB2", "energy_per_atom": -1}]}):
        changed = copy.deepcopy(settings)
        changed["scientific_protocol_data"]["reference_ensemble"].update(mutation)
        candidate = copy.deepcopy(protocol)
        candidate["details"]["reference_ensemble_sha256"] = digest(changed["scientific_protocol_data"]["reference_ensemble"])
        with pytest.raises(ValueError):
            validate_protocol_data(candidate, changed, state, source_formula="MgB2")


def test_explicit_weighted_q_sampling_is_supported_without_claiming_full_bz_coverage():
    args = feature_case("phonon_min_frequency")
    data = args[3]["settings"]["scientific_protocol_data"]
    data["q_sampling"].update(mode="explicit", grid=None, offset=None,
                             points=[[0, 0, 0], [0.5, 0.5, 0.5]], weights=[0.25, 0.75])
    protocol = args[-1]["protocol"]
    protocol["details"]["q_sampling_sha256"] = digest(data["q_sampling"])
    protocol["settings_sha256"] = digest(args[3]["settings"])
    args[-2] = selector_for(protocol)
    assert validate_property_feature(*args)["status"] == "admitted"
    data["q_sampling"]["weights"] = [0.5, 0.75]
    protocol["details"]["q_sampling_sha256"] = digest(data["q_sampling"])
    with pytest.raises(ValueError):
        validate_protocol_data(protocol, args[3]["settings"], args[2])


@pytest.mark.parametrize("key", ["formation_energy_per_atom", "energy_above_hull", "dos_at_fermi"])
def test_formula_basis_must_be_supplied_not_inferred_from_catalogue_or_method(key):
    args = feature_case(key)
    result = _validate_property_feature(*args)
    assert result["status"] == "unavailable"
    assert "property_source_formula_unresolved" in result["reason_codes"]


def test_stability_ensemble_must_cover_actual_claim_elements_but_may_be_global():
    args = feature_case("formation_energy_per_atom")
    assert validate_property_feature(*args, source_formula="Nb")["status"] == "unavailable"
    settings, protocol = args[3]["settings"], args[-1]["protocol"]
    reference = settings["scientific_protocol_data"]["reference_ensemble"]
    reference["entries"].append({"reference_id": "synthetic-Nb", "formula": "Nb", "energy_per_atom": -3})
    protocol["details"]["reference_ensemble_sha256"] = digest(reference)
    protocol["settings_sha256"] = digest(settings)
    args[-2] = selector_for(protocol)
    result = validate_property_feature(*args, source_formula="Nb")
    assert result["status"] == "admitted"
    assert result["provenance"]["source_formula"] == "Nb"
    assert result["provenance"]["normalization_scope"] == "reviewed_declaration_not_independently_recomputed"
    assert validate_property_feature(*args, source_formula="MgB2")["status"] == "admitted"


def test_pure_functions_do_not_connect_to_database_network_or_start_subprocesses():
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run([sys.executable, "-c", """
import sys
def forbid_io(event, args):
    if event in {'socket.connect', 'socket.connect_ex', 'subprocess.Popen', 'os.system'}:
        raise AssertionError('unexpected external I/O')
sys.addaudithook(forbid_io)
from models.ml_task_v2 import default_task_v2, validate_task_v2
from services.ml_scientific_features import validate_property_feature
from services.ml_coordinate_features import coordinate_features
validate_task_v2(default_task_v2())
from models.db import get_engine, get_session_factory
assert get_engine.cache_info().currsize == 0
assert get_session_factory.cache_info().currsize == 0
# Existing models.__init__ imports ORM definitions; importing is not a query.
# Its schema registrations may also transitively load provider definitions.
assert not any(name == 'ingestion' or name.startswith('ingestion.') for name in sys.modules)
"""], cwd=root / "api", capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
