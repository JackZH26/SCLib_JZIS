"""Conservative, versioned units; unsupported conventions remain unresolved."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import math

from ingestion.extract.scientific_values import parse_scientific_value
from . import NORMALIZER_VERSION

VERSION = "materials-properties/3.0"
# Reuse the established scientific parser for its exact SI conversions.
PARSER_FIELDS = {
    "tc": "tc_kelvin",
    "upper_critical_field": "hc2_tesla",
    "lower_critical_field": "hc2_tesla",
    "gap_energy": "rho_s_mev",
    "electron_phonon_lambda": "lambda_eph",
    "omega_log": "omega_log_k",
    "coulomb_mu_star": "mu_star",
    "penetration_depth": "lambda_london_nm",
    "coherence_length": "xi_gl_nm",
    "superfluid_stiffness": "rho_s_mev",
    "transition_temperature_structural": "temperature_k",
    "transition_temperature_magnetic": "temperature_k",
    "lattice_a": "lattice_a",
    "lattice_b": "lattice_b",
    "lattice_c": "lattice_c",
    "lattice_alpha": "lattice_alpha",
    "lattice_beta": "lattice_beta",
    "lattice_gamma": "lattice_gamma",
    "film_thickness": "layer_thickness_nm",
    "strain": "doping_level",
}
CONDITION_FIELDS = {
    **{
        f"{role}_pressure": "pressure_gpa"
        for role in ("measurement", "synthesis", "calculation", "structural")
    },
    **{
        f"{role}_temperature": "temperature_k"
        for role in ("measurement", "synthesis", "calculation")
    },
    "minimum_test_temperature": "temperature_k",
    "temperature_scan_range": "temperature_k",
    "pressure_scan_range": "pressure_gpa",
    "magnetic_field": "magnetic_field_t",
    "magnetic_field_scan_range": "magnetic_field_t",
    "maximum_test_field": "magnetic_field_t",
    "film_thickness": "layer_thickness_nm",
    "doping_fraction": "doping_level",
    "strain": "doping_level",
    "twist_angle": "lattice_alpha",
}
# No conversion between angular/ordinary frequency, H/B, or denominator bases.
UNITS = {
    "critical_current_density": (
        "A/cm2",
        {"A/cm2": 1, "A/cm^2": 1, "A/cm²": 1, "A/m2": 1e-4, "MA/cm2": 1e6},
    ),
    "resistivity": ("ohm*m", {"ohm*m": 1, "Ω m": 1, "μΩ cm": 1e-8, "microohm cm": 1e-8}),
    "carrier_density": ("1/cm3", {"1/cm3": 1, "cm^-3": 1, "cm⁻³": 1, "m^-3": 1e-6}),
    "superfluid_density": ("1/cm3", {"1/cm3": 1, "cm^-3": 1, "cm⁻³": 1, "m^-3": 1e-6}),
    "unit_cell_volume": ("angstrom3", {"angstrom3": 1, "Å³": 1, "Å^3": 1, "nm3": 1000}),
    "band_gap": ("eV", {"eV": 1, "meV": 0.001}),
    "dos_at_fermi": ("states/eV/formula_unit", {"states/eV/formula_unit": 1}),
    "formation_energy_per_atom": ("eV/atom", {"eV/atom": 1, "meV/atom": 0.001}),
    "energy_above_hull": ("eV/atom", {"eV/atom": 1, "meV/atom": 0.001}),
    "phonon_min_frequency": ("THz", {"THz": 1, "GHz": 0.001}),
}
TEXT_KEYS = {
    "pairing_symmetry",
    "composition_family",
    "structure_motif",
    "electronic_class",
    "mechanism_report",
    "space_group",
    "phase_label",
    "sample_form",
    "substrate",
    "preparation_method",
    "pressure_medium",
    "competing_order",
    "unconventional_report",
    "ambient_sc_report",
}


def normalize_quantity(key: str, quantity: dict, *, condition=False, qualifiers=None) -> dict:
    """Normalize shape without inferring missing units or physical conventions."""
    raw = deepcopy(quantity)
    unit = quantity.get("raw_unit")
    result = {
        "version": NORMALIZER_VERSION,
        "raw": raw,
        "status": "unresolved",
        "relation": quantity["relation"],
        "value": None,
        "lower": None,
        "upper": None,
        "unit": None,
        "reason": "unit_not_reported",
    }
    # Named lambda/mu* are dimensionless by definition; dimensional quantities
    # never inherit an unreported unit from a column or material family.
    if unit is None and not condition and key in {"electron_phonon_lambda", "coulomb_mu_star"}:
        unit = "1"
        result["unit_basis"] = "dimensionless_property_definition"
    if unit is None:
        return result
    field = (CONDITION_FIELDS if condition else PARSER_FIELDS).get(key)
    if key == "omega_log" and unit not in {"K", "k", "kelvin", "Kelvin", "mK"}:
        return {**result, "reason": "frequency_convention_requires_review"}
    if (
        key in {"upper_critical_field", "lower_critical_field"}
        and (qualifiers or {}).get("field_quantity_raw") == "H"
    ):
        return {**result, "reason": "H_to_B_conversion_requires_review"}
    numbers = [quantity[k] for k in ("value", "lower", "upper") if quantity[k] is not None]
    if not numbers:
        return {**result, "reason": "no_numeric_value"}
    factor = None
    if field:
        # Parse numerical values using the shared parser; raw text is kept independently.
        parsed = [parse_scientific_value(n, field, raw_unit=unit) for n in numbers]
        if any(p["status"] != "parsed" for p in parsed):
            return {**result, "reason": "unsupported_unit_or_value"}
        canonical_unit = parsed[0]["unit"]
        converted = iter(p["value"] for p in parsed)
    elif key in UNITS:
        canonical_unit, spellings = UNITS[key]
        factor = spellings.get(unit)
        if factor is None:
            return {**result, "reason": "unsupported_unit_or_basis"}
        converted = iter(float(Decimal(str(n)) * Decimal(str(factor))) for n in numbers)
    else:
        return {**result, "reason": "unregistered_quantity"}
    for part in ("value", "lower", "upper"):
        if quantity[part] is not None:
            result[part] = next(converted)
    if any(
        result[part] is not None and not math.isfinite(result[part])
        for part in ("value", "lower", "upper")
    ):
        return {
            **result,
            "status": "unresolved",
            "value": None,
            "lower": None,
            "upper": None,
            "reason": "unit_conversion_nonfinite",
        }
    result.update(status="normalized", unit=canonical_unit, reason=None)
    return result
