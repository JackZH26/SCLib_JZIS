"""Closed v2 feature task; the composition-only v1 contract stays unchanged.

The seven initial profiles describe computed normal-state quantities, not
experimental proxies, superconducting responses, or universal mechanisms.
Protocol declarations and hashes are reproducibility inputs, never authority.
"""

from __future__ import annotations

import hashlib
import re

from models.ml_task import MlTaskError, default_task, require, validate_task
from services.research_release_manifest import canonical

VERSION = "ml-task/2.0.0"
PROTOCOL_VERSION = "ml-physical-protocol/1.0.0"
CONTEXT_VERSION = "ml-scientific-context/1.0.0"
REGISTRY_VERSION = "rv2/1"
HASH = re.compile(r"^[0-9a-f]{64}$")
UNITS = {
    "formation_energy_per_atom": "eV/atom",
    "energy_above_hull": "eV/atom",
    "band_gap": "eV",
    "dos_at_fermi": "states/eV/formula_unit",
    "electron_phonon_lambda": "1",
    "omega_log": "K",
    "phonon_min_frequency": "THz",
}
STRUCTURE_FEATURES = ("volume_per_atom_a3", "density_g_cm3")
DEFINITIONS = {
    "formation_energy_per_atom": "normal_state_formation_potential_difference",
    "energy_above_hull": "normal_state_convex_hull_potential_difference",
    "band_gap": "normal_state_fundamental_one_electron_gap",
    "dos_at_fermi": "normal_state_total_density_of_states_at_fermi_energy",
    "electron_phonon_lambda": "isotropic_alpha2f_inverse_frequency_integral",
    "omega_log": "isotropic_alpha2f_logarithmic_frequency_average",
    "phonon_min_frequency": "minimum_signed_phonon_frequency_on_declared_q_sampling",
}
NORMALIZATIONS = {
    "formation_energy_per_atom": "per_atom", "energy_above_hull": "per_atom",
    "band_gap": "energy_difference", "dos_at_fermi": "per_source_formula_unit",
    "electron_phonon_lambda": "dimensionless",
    "omega_log": "hbar_angular_frequency_over_boltzmann_constant",
    "phonon_min_frequency": "signed_cycles_per_second_in_terahertz",
}
DFPT = {"electron_phonon_lambda", "omega_log", "phonon_min_frequency"}
SELECTOR_FIELDS = {
    "feature_key", "property_key", "registry_version", "component_key", "unit",
    "knowledge_origin", "semantics_profile", "protocol_sha256",
}


def _object(value, keys, code):
    require(type(value) is dict and set(value) == set(keys), code)


def _text(value, maximum=120):
    return type(value) is str and 0 < len(value) <= maximum and value.strip() == value and not any(
        ord(character) < 32 or ord(character) == 127 for character in value
    )


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def semantics_profile(property_key):
    require(type(property_key) is str and property_key in UNITS, "unsupported_physical_property")
    return f"ml-normal-state/{property_key}/1.0.0"


def _details_template(key):
    if key in {"formation_energy_per_atom", "energy_above_hull"}:
        return {"thermodynamic_potential": None, "reference_ensemble_sha256": None,
                "nuclear_treatment": None}
    if key == "band_gap":
        return {"spin_treatment": None, "occupation_treatment": None}
    if key == "dos_at_fermi":
        return {"spin_normalization": "sum_of_all_spin_channels", "energy_reference": "fermi_energy",
                "formula_unit_basis": "source_formula_reduced_integer_or_preserved_fractional",
                "broadening_method": None, "broadening_ev": None}
    if key in {"electron_phonon_lambda", "omega_log"}:
        return {"coupling_model": "isotropic_migdal_eliashberg", "spectral_basis": "full_alpha2f",
                "nuclear_treatment": None, "q_sampling_sha256": None,
                "broadening_scheme_sha256": None}
    return {"frequency_convention": "signed_real_positive_imaginary_negative",
            "minimum_scope": "declared_q_sampling", "q_sampling_sha256": None,
            "nuclear_treatment": None}


def protocol_template(property_key):
    """Return an intentionally invalid draft: method, settings and treatment need filling.

    A caller cannot acquire a valid selector from these unknown placeholders.
    References/q-sampling are exact retained protocol-artifact digests, not names.
    """
    return {
        "version": PROTOCOL_VERSION, "property_key": property_key,
        "semantics_profile": semantics_profile(property_key),
        "method_kind": "dfpt" if property_key in DFPT else "dft",
        "method_name": None, "code_version": None, "settings_schema_version": None,
        "settings_sha256": None, "definition": DEFINITIONS[property_key],
        "normalization": NORMALIZATIONS[property_key], "details": _details_template(property_key),
    }


def validate_protocol(protocol):
    canonical(protocol)
    _object(protocol, protocol_template("band_gap"), "invalid_protocol_fields")
    key = protocol["property_key"]
    expected = protocol_template(key)
    for field in ("version", "semantics_profile", "method_kind", "definition", "normalization"):
        require(protocol[field] == expected[field] and type(protocol[field]) is str,
                "unsupported_protocol_semantics")
    require(all(_text(protocol[field]) for field in ("method_name", "code_version", "settings_schema_version"))
            and _hash(protocol["settings_sha256"]), "incomplete_protocol_method")
    details = protocol["details"]
    _object(details, expected["details"], "invalid_protocol_details")
    if key in {"formation_energy_per_atom", "energy_above_hull"}:
        require(type(details["thermodynamic_potential"]) is str
                and details["thermodynamic_potential"] in {"energy", "enthalpy"}
                and type(details["nuclear_treatment"]) is str
                and details["nuclear_treatment"] in {"static_lattice", "zero_point_energy"}
                and _hash(details["reference_ensemble_sha256"]), "invalid_stability_reference")
    elif key == "band_gap":
        require(type(details["spin_treatment"]) is str and details["spin_treatment"] in {
            "non_spin_polarized", "collinear_spin_polarized", "spin_orbit",
        } and type(details["occupation_treatment"]) is str and details["occupation_treatment"] in {
            "zero_temperature", "finite_smearing_extrapolated",
        }, "invalid_gap_definition")
    elif key == "dos_at_fermi":
        require(all(details[field] == expected["details"][field] for field in (
            "spin_normalization", "energy_reference", "formula_unit_basis",
        )), "invalid_dos_normalization")
        method, width = details["broadening_method"], details["broadening_ev"]
        require(type(method) is str and method in {"gaussian", "lorentzian", "tetrahedron"},
                "invalid_dos_broadening")
        require(width is None if method == "tetrahedron" else type(width) in {int, float} and 0 < width <= 100,
                "invalid_dos_broadening")
    else:
        require(type(details["nuclear_treatment"]) is str
                and details["nuclear_treatment"] in {"harmonic", "anharmonic"}
                and _hash(details["q_sampling_sha256"]), "invalid_phonon_treatment")
        if key in {"electron_phonon_lambda", "omega_log"}:
            require(details["coupling_model"] == "isotropic_migdal_eliashberg"
                    and details["spectral_basis"] == "full_alpha2f"
                    and _hash(details["broadening_scheme_sha256"]), "invalid_epc_definition")
        else:
            require(details["frequency_convention"] == "signed_real_positive_imaginary_negative"
                    and details["minimum_scope"] == "declared_q_sampling", "invalid_phonon_definition")
    return protocol


def protocol_sha256(protocol):
    return hashlib.sha256(canonical(validate_protocol(protocol))).hexdigest()


def validate_selector(selector):
    canonical(selector)
    _object(selector, SELECTOR_FIELDS, "invalid_physical_selector_fields")
    key = selector["property_key"]
    require(type(key) is str and key in UNITS, "unsupported_physical_property")
    # An input feature key is a selector, not evidence that its leaf has that type.
    # Canonical keys avoid target/score aliases, including innocently renamed inputs.
    require(selector["feature_key"] == key, "noncanonical_physical_feature_key")
    require(selector["registry_version"] == REGISTRY_VERSION and selector["unit"] == UNITS[key]
            and selector["knowledge_origin"] == "Computed"
            and selector["semantics_profile"] == semantics_profile(key), "unsupported_physical_selector")
    require(type(selector["component_key"]) is str and selector["component_key"] == "bulk"
            and _hash(selector["protocol_sha256"]), "invalid_physical_selector_binding")
    return selector


def selector_for(protocol, *, component_key="bulk"):
    key = validate_protocol(protocol)["property_key"]
    return validate_selector({
        "feature_key": key, "property_key": key, "registry_version": REGISTRY_VERSION,
        "component_key": component_key, "unit": UNITS[key], "knowledge_origin": "Computed",
        "semantics_profile": semantics_profile(key), "protocol_sha256": protocol_sha256(protocol),
    })


def validate_scientific_context(context):
    canonical(context)
    _object(context, {"version", "normal_state", "target_derived", "protocol"},
            "invalid_scientific_context_fields")
    require(context["version"] == CONTEXT_VERSION and context["normal_state"] is True
            and context["target_derived"] is False, "normal_state_context_required")
    validate_protocol(context["protocol"])
    return context


def default_task_v2(*, cutoff="2026-01-01T00:00:00Z"):
    """Explicit draft, with no physical/structure selection or authority implied."""
    return {
        "version": VERSION, "task_id": "observed-tc-nested-features-v2",
        "label_task": default_task(cutoff=cutoff), "physical_features": [], "structure_features": [],
        "state_policy": "exact_or_reviewed_normal_state_surrogate",
        "cohort_policy": "fixed_base_split_nested_intersections",
        "information_regime": "pre_outcome_normal_state",
        "missingness": "preserve_then_train_only",
    }


def validate_task_v2(task):
    canonical(task)
    expected = default_task_v2()
    _object(task, expected, "invalid_v2_task_fields")
    for key in ("version", "state_policy", "cohort_policy", "information_regime", "missingness"):
        require(type(task[key]) is str and task[key] == expected[key], "unsupported_v2_task_policy")
    require(type(task["task_id"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", task["task_id"]),
            "invalid_v2_task_id")
    validate_task(task["label_task"])
    selectors = task["physical_features"]
    require(type(selectors) is list and len(selectors) <= len(UNITS), "physical_selector_budget")
    keys = [validate_selector(item)["feature_key"] for item in selectors]
    require(keys == sorted(set(keys)), "physical_selectors_must_be_sorted_unique")
    require(type(task["structure_features"]) is list and task["structure_features"] in (
        [], list(STRUCTURE_FEATURES),
    ), "unsupported_structure_features")
    return task


__all__ = [
    "MlTaskError", "default_task_v2", "validate_task_v2", "protocol_template", "validate_protocol",
    "protocol_sha256", "selector_for", "validate_selector", "validate_scientific_context",
]
