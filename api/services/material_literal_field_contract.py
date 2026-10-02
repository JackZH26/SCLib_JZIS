"""Closed original-text fields; a raw literal is not a scientific quantity.

These identifiers and roles are versioned independently of the frozen parsed
numeric source-expression registry. Qualifiers are pending declarations, not
reviewed interpretation of the retained text.
"""

from __future__ import annotations

from services.research_release_manifest import digest

VERSION = "material-literal-field/1.0.0"
PROFILE = VERSION
FIELD_ROLES = (
    "reported_property",
    "study_extent",
    "measurement_limit",
    "reported_order_transition",
)
FIELDS = {
    "hc1_source_value": "reported_property",
    "gap_energy_source_value": "reported_property",
    "gap_ratio_source_value": "reported_property",
    "electronic_specific_heat_coefficient_source_value": "reported_property",
    "debye_temperature_source_value": "reported_property",
    "isotope_effect_exponent": "reported_property",
    "dtc_dp_source_value": "reported_property",
    "maximum_applied_pressure_source_value": "study_extent",
    "meissner_fraction_percent": "reported_property",
    "transition_width_source_value": "reported_property",
    "minimum_temperature_k": "measurement_limit",
    "t_cdw_k": "reported_order_transition",
    "t_afm_k": "reported_order_transition",
    "t_sdw_k": "reported_order_transition",
}
QUALIFIERS = (
    "cited_negative_or_qualified_context",
    "model_or_calculation_context",
    "fit_or_estimate_context",
    "inference_or_unmeasured_context",
)
REGISTRY_SHA256 = digest(
    {"version": VERSION, "fields": FIELDS, "roles": list(FIELD_ROLES)}
)
