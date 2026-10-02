"""Closed, pending source-property projections from two inspected public snapshots.

This mapper preserves source expressions, conditional windows and provenance.
It does not validate physics, establish samples/phases, or write canonical data.
The registry holds only identifiers, hashes, paths and typed roles; the original
public documents are supplied by an authorized caller, never fetched here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass

MAPPER_VERSION = "source-property-contract/1.0.0"
MAX_SOURCE_BYTES = 1_048_576
MAX_DEPTH = 24
MAX_NODES = 50_000
MAX_CONTAINER_ITEMS = 128
MAX_STRING_BYTES = 4096
_SAFE_INTEGER = 9_007_199_254_740_991

# Immutable metadata rows: entry ID, public snapshot SHA, index, canonical entry
# SHA, qualified field, profile, source role. No manuscript text is embedded.
_ENTRY_ROWS = (
    (
        "source-only:pt:hc2_temperature_slope",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        0,
        "abe7928c52e7de1e3d1a3a890e88eeef34df8440f890e3896a274c17e0aa0889",
        "pt:hc2_temperature_slope",
        "quantity",
        "source_curve_derived_slope",
    ),
    (
        "source-only:pt:hc2_whh_orbital_zero_temperature",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        1,
        "9b602a1b1d4415961adc43a5c983375904952b335e6948fdbaafca4c5ed9e35a",
        "pt:hc2_whh_orbital_zero_temperature",
        "quantity",
        "source_reported_model_estimate",
    ),
    (
        "source-only:pt:hc2_linear_zero_temperature",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        2,
        "96dd47dcc41710e02e13fbd0520d7ab813c2343caa4a06778a10c218b7195cbe",
        "pt:hc2_linear_zero_temperature",
        "quantity",
        "source_reported_model_estimate",
    ),
    (
        "source-only:pt:hc2_resistive_criterion",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        3,
        "f2a48633412a4900b6eaa43c0d4977c463c4c4d56c5252b6a27accdeb87c0fba",
        "pt:hc2_resistive_criterion",
        "quantity",
        "curve_definition",
    ),
    (
        "source-only:pt:hc2_measurement_window",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        4,
        "5d45a635a6c1c13adb4cb1618027fa86e383362baf1e792d65c062033d349a82",
        "pt:hc2_measurement_window",
        "source_statement",
        "source_condition_expression",
    ),
    (
        "source-only:cs_nb:ambient_fitted_tc",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        5,
        "98b1c659307fcd55089dca24754cf89b55f3ad6a8a106801506db423300c974b",
        "cs_nb:ambient_fitted_tc",
        "quantity",
        "source_reported_fit",
    ),
    (
        "source-only:cs_nb:ambient_fitted_penetration",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        6,
        "95284a6ae4cd7b5d2a0c76c46c8ebb5e07bdc25bb45776bd00eac411e481b5e5",
        "cs_nb:ambient_fitted_penetration",
        "quantity",
        "source_reported_fit",
    ),
    (
        "source-only:cs_nb:ambient_fitted_gap",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        7,
        "d70e2f0dfee6ce8d40551b529e7b2c1bf0a757afff380cbdfd671f5ced5011ad",
        "cs_nb:ambient_fitted_gap",
        "quantity",
        "source_reported_fit",
    ),
    (
        "source-only:cs_nb:zero_gpa_table_tc",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        8,
        "9775ce26ee874f1bda7ecdbc1f31ae7f94fc8fe86752469ae1648b08d506e7ff",
        "cs_nb:zero_gpa_table_tc",
        "quantity",
        "source_reported_fit_table",
    ),
    (
        "source-only:cs_nb:zero_gpa_table_penetration",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        9,
        "cd6a1b6d56ae18a508ad8cd520011ca63dace4a8e6182dacb58594bbf8be7252",
        "cs_nb:zero_gpa_table_penetration",
        "quantity",
        "source_reported_fit_table",
    ),
    (
        "source-only:cs_nb:zero_gpa_table_gap_1",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        10,
        "d3868ad9d91119a1355e705480532599ba18f631262cef2f52dc18fd63b22f8f",
        "cs_nb:zero_gpa_table_gap_1",
        "quantity",
        "source_reported_fit_table",
    ),
    (
        "source-only:crb2_cif:listed_atomic_sites",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        11,
        "8475d78ae3bdf9a41dc9bb928cfaef5e43d2b7399342ab61e384826f47cca198",
        "crb2_cif:listed_atomic_sites",
        "cif_atomic_sites",
        "listed_CIF_source_metadata",
    ),
    (
        "source-only:crb2_cif:declared_symmetry_operations",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        12,
        "917fca6227980dfa641ed51d3fb25a1526bfd0d45fed0bcafce1bea6df938c0e",
        "crb2_cif:declared_symmetry_operations",
        "cif_declared_operations",
        "listed_CIF_source_metadata",
    ),
    (
        "source-only:crb2_cif:reported_hall_symbol",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        13,
        "b1ea61c55f0a51210840889e4108e19989001687b6f4a69c21b0f85323c7b391",
        "crb2_cif:reported_hall_symbol",
        "source_statement",
        "listed_CIF_source_metadata",
    ),
    (
        "source-only:crb2_cif:cell_formula_units_z",
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        14,
        "14376d96ee54060b1d6d513ca386e802520a9cdb89b054e6eff5f7f5f64e456c",
        "crb2_cif:cell_formula_units_z",
        "quantity",
        "listed_CIF_source_metadata",
    ),
    (
        "source-only-r2:ysc:calculation_method_and_origin_statement",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        0,
        "6407e123283f3afcfc0a48348f86fc438962df092ecd5641ae1cee3911c5881f",
        "ysc:calculation_method_and_origin_statement",
        "source_statement",
        "source_reported_prediction_method",
    ),
    (
        "source-only-r2:ysc:electron_phonon_lambda_source_value",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        1,
        "3c0d9e7d223c962ef1588bbed50cbe6250ea0edf4dcd44cea881b44cf84908af",
        "ysc:electron_phonon_lambda_source_value",
        "unavailable",
        "unresolved_numeric_source_setting",
    ),
    (
        "source-only-r2:ysc:omega_log_source_value",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        2,
        "d72562cec829303c568167f85baeca15ac22357a54f194b2b23bf78417f6de74",
        "ysc:omega_log_source_value",
        "unavailable",
        "unresolved_numeric_source_setting",
    ),
    (
        "source-only-r2:ysc:mu_star_source_parameter",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        3,
        "8162253b05590c83dffa1e0257771a6e52274ad2b76ff9c6ebcbe7813c69301a",
        "ysc:mu_star_source_parameter",
        "unavailable",
        "unresolved_numeric_source_setting",
    ),
    (
        "source-only-r2:lasm:source_preparation_description",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        4,
        "1de53aa4d7ec42a25922a1eba90f3dcbd6b7f018b52186cbe92bd859edf54869",
        "lasm:source_preparation_description",
        "preparation",
        "database_source_preparation_comment",
    ),
    (
        "source-only-r2:lasm:source_anneal_temperature_options",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        5,
        "d4c4be363161ce78c3fa56b13afabba1549504e1bb04b5ac272ece493acb3232",
        "lasm:source_anneal_temperature_options",
        "preparation",
        "source_preparation_options_and_series_recommendation",
    ),
    (
        "source-only-r2:lasm:susceptibility_transition_definition",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        6,
        "ac4a5bd80dc229e3018c80db1b73bbbd4101106a07ec39cb17f7e8a639dcab46",
        "lasm:susceptibility_transition_definition",
        "quantity_context",
        "source_method_definition_separate_database_values",
    ),
    (
        "source-only-r2:lasm:tc_applied_pressure_context",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        7,
        "189143a8b2c74c7c0a0d79e1fe5ad4da34dab74fa2b4e4f23c0372d18cc3dd63",
        "lasm:tc_applied_pressure_context",
        "quantity_context",
        "separate_source_pressure_experiment_context",
    ),
    (
        "source-only-r2:lasm:meissner_measurement_method_and_conditions",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        8,
        "f2272725eb53d426ffa6ccaaf9c74e4ce1ed3fa375d17b598ef425342d35bea8",
        "lasm:meissner_measurement_method_and_conditions",
        "quantity_context",
        "database_fraction_and_related_primary_method_context",
    ),
    (
        "source-only-r2:sn_in:source_composition_and_local_x_definition",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        9,
        "f33c351f7b076080eca1936104f2f6d4da0a284237384d7ac11258668cae242f",
        "sn_in:source_composition_and_local_x_definition",
        "quantity_context",
        "source_local_composition_definition",
    ),
    (
        "source-only-r2:sn_in:hall_carrier_density_and_conditions",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        10,
        "c3bb296855bb07b328b340b929348953094cf1adafb1f7f6fcd307346eac9732",
        "sn_in:hall_carrier_density_and_conditions",
        "quantity_context",
        "source_hall_derived_carrier_density",
    ),
    (
        "source-only-r2:sn_in:sample_measurement_context",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        11,
        "e5e1385b891350dd431fb0dcf3a884aaac542f17f37028bb045506fe1268cc31",
        "sn_in:sample_measurement_context",
        "quantity_context",
        "source_sample_and_probe_metadata",
    ),
    (
        "source-only-r2:sn_in:reported_gap_or_pairing_source_claim",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        12,
        "fe00ae8a71f82d272e06b8b58aa44a6eebcc7ebb58f9b7ef20b2452200975100",
        "sn_in:reported_gap_or_pairing_source_claim",
        "quantity_context",
        "source_probe_interpretation_and_theoretical_pairing_claim",
    ),
    (
        "source-only-r2:sr_ni:source_local_Ni_composition_definition",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        13,
        "76f3d7fd95f098050d7f0b7591c3387c9b21acc5e228dce92a0ede3441039b06",
        "sr_ni:source_local_Ni_composition_definition",
        "quantity_context",
        "source_local_nominal_composition",
    ),
    (
        "source-only-r2:sr_ni:source_transition_criterion",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        14,
        "07a0352d2f9573cf67933288162d6e481911fe04baea1f8178abedeea802810a",
        "sr_ni:source_transition_criterion",
        "quantity_context",
        "source_curve_definition",
    ),
    (
        "source-only-r2:sr_ni:hc2_curve_slope_and_model",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        15,
        "910aa7c9b6b4028d770d10287db580dcd728919fdc7f5f2a1bf6ff8911d40c9d",
        "sr_ni:hc2_curve_slope_and_model",
        "quantity_context",
        "source_curve_derived_slope_and_model_extrapolation",
    ),
    (
        "source-only-r2:sr_ni:sample_anneal_conditions",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        16,
        "eaccca721d946570a47fc7af3e406ef22645c90c5be621c445ac369750612678",
        "sr_ni:sample_anneal_conditions",
        "preparation",
        "source_series_protocol_separate_from_individual_sample",
    ),
    (
        "source-only-r2:bapb:source_local_composition_definition",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        17,
        "9619dcb74b6184b8effd705cf56c50f110ac08cdbfd749bf46cc7a4a191e6da8",
        "bapb:source_local_composition_definition",
        "quantity_context",
        "source_local_composition_and_probe_statement",
    ),
    (
        "source-only-r2:bapb:reported_short_range_order_claim",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        18,
        "f67b149bc844353404f8b93dc5c425d14ef2b2d382599f232802c7828650c426",
        "bapb:reported_short_range_order_claim",
        "quantity_context",
        "source_optical_interpretation_claim",
    ),
    (
        "source-only-r2:bapb:optical_measurement_temperature_window",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        19,
        "243a668fd5f9747b61a54add40e4b8aaaaef23db4d8705a5f7dd9f0184a58f79",
        "bapb:optical_measurement_temperature_window",
        "quantity_context",
        "source_figure_measurement_conditions",
    ),
    (
        "source-only-r2:bapb:optical_probe_method",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        20,
        "12b8330318d81010051e684013060c8eb0d6519f7d2bb7fac2b71694af800867",
        "bapb:optical_probe_method",
        "quantity_context",
        "source_optical_probe_and_analysis_conditions",
    ),
    (
        "source-only-r2:motm:source_rare_earth_member_definition",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        21,
        "79e6e92702e02631e33a48fe7011648a0cf3a9d64d6abee2647af231436e4022",
        "motm:source_rare_earth_member_definition",
        "source_statement",
        "source_explicit_member_definition",
    ),
    (
        "source-only-r2:motm:reported_magnetic_order_and_temperature",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        22,
        "d46f225b45438a606167ad1f657cf08b745a529d4e303ce7a68eb0c8874c1b64",
        "motm:reported_magnetic_order_and_temperature",
        "quantity_context",
        "source_member_specific_magnetic_order_report",
    ),
    (
        "source-only-r2:motm:magnetic_probe_method",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        23,
        "169a76d0dfc2db081b031cd8735c8db68cf35569876f70a80780d378718129a9",
        "motm:magnetic_probe_method",
        "quantity_context",
        "source_study_probe_with_member_context",
    ),
    (
        "source-only-r2:motm:tm_member_transition_criterion",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        24,
        "8d074dc585c4aec36225b6cf9310c5739019bbfe3fd7c0ec126f051f18bbd45d",
        "motm:tm_member_transition_criterion",
        "quantity_context",
        "source_member_specific_ac_susceptibility_transition_report",
    ),
    (
        "source-only-r2:fese_cif:listed_atomic_sites",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        25,
        "3300d58562a1d0c6e8db8b107744fe94e25b68222702040fe228b3ece9368935",
        "fese_cif:listed_atomic_sites",
        "cif_atomic_sites",
        "source_reported_refined_atomic_sites",
    ),
    (
        "source-only-r2:fese_cif:declared_symmetry_operations",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        26,
        "a4dbd346ee73072b089ae5290b6992c76b12d7b0991a7948703459b13cdbefc2",
        "fese_cif:declared_symmetry_operations",
        "cif_declared_operations",
        "source_declared_symmetry_operations",
    ),
    (
        "source-only-r2:fese_cif:reported_hall_symbol",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        27,
        "d5b5cff07612d8b6c55f56c514969f2822036313ca7804f0f643e164f6b02a4d",
        "fese_cif:reported_hall_symbol",
        "source_statement",
        "source_reported_symmetry_label",
    ),
    (
        "source-only-r2:fese_cif:cell_formula_units_z",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        28,
        "a013e2b1103ceae670091c103e25b0eb7fe025c4afe11b80e9b956ae195a79c4",
        "fese_cif:cell_formula_units_z",
        "quantity",
        "source_cell_formula_units",
    ),
    (
        "source-only-r2:pt_extra:source_preparation_and_specific_heat_method",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        29,
        "310f601d683658493043b8c00d049b4e46e3b862849a3e6fc88cf8ba50a2f781",
        "pt_extra:source_preparation_and_specific_heat_method",
        "preparation",
        "source_preparation_and_measurement_method",
    ),
    (
        "source-only-r2:pt_extra:source_heating_program",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        30,
        "65c4a9e14690881f68de4e3c27d630c4d616086802eb70a103b457442f12833b",
        "pt_extra:source_heating_program",
        "preparation",
        "source_growth_conditions",
    ),
    (
        "source-only-r2:pt_extra:specific_heat_jump_over_tc",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        31,
        "644c54c483a5703d133285eba356560969e209e79979b0941d204b1b8c5ad01a",
        "pt_extra:specific_heat_jump_over_tc",
        "quantity",
        "source_isoentropic_construction_result",
    ),
    (
        "source-only-r2:pt_extra:specific_heat_analysis_context",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        32,
        "3f2fc3ba1874f8bcee9bbc75e16bc471df30d03e06b90fa3c5105cac9668aca8",
        "pt_extra:specific_heat_analysis_context",
        "quantity_context",
        "source_analysis_definition_and_assumptions",
    ),
    (
        "source-only-r2:pt_extra:electronic_specific_heat_coefficient_model",
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        33,
        "a8b6a0c239daf4455bce22183d9967dd5c8f8ef12c6085c44120875511a73493",
        "pt_extra:electronic_specific_heat_coefficient_model",
        "quantity",
        "source_BCS_assumption_derived_estimate",
    ),
)

_BATCHES = {
    "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e": {
        "version": "materials-source-observations/1.0.0",
        "original_batch_sha256": "947e13d7947f27d9d291a3783ad262308babcec14c186de0e5fbf1c70b8a884f",
        "entry_count": 15,
        "source_expression_count": 15,
    },
    "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8": {
        "version": "materials-source-followup/1.0.0",
        "original_batch_sha256": "af823526b7c2764c75c116c2d42e48fde3746feac8e5d6635fecaa34f7a41615",
        "entry_count": 34,
        "source_expression_count": 31,
    },
}

_COMPONENT_ROLES = {
    "pt:hc2_temperature_slope": {"/value": "source_curve_derived_slope"},
    "pt:hc2_whh_orbital_zero_temperature": {"/value": "source_reported_model_estimate"},
    "pt:hc2_linear_zero_temperature": {"/value": "source_reported_model_estimate"},
    "pt:hc2_resistive_criterion": {"/value": "curve_definition"},
    "pt:hc2_measurement_window": {},
    "cs_nb:ambient_fitted_tc": {"/value": "source_reported_fit"},
    "cs_nb:ambient_fitted_penetration": {"/value": "source_reported_fit"},
    "cs_nb:ambient_fitted_gap": {"/value": "source_reported_fit"},
    "cs_nb:zero_gpa_table_tc": {
        "/value": "source_reported_fit_table",
        "/source_window/pressure": "source_window_condition",
    },
    "cs_nb:zero_gpa_table_penetration": {
        "/value": "source_reported_fit_table",
        "/source_window/pressure": "source_window_condition",
    },
    "cs_nb:zero_gpa_table_gap_1": {
        "/value": "source_reported_fit_table",
        "/source_window/pressure": "source_window_condition",
    },
    "crb2_cif:listed_atomic_sites": {
        "/value/0/fractional_coordinates/0": "declared_CIF_fractional_coordinate",
        "/value/0/fractional_coordinates/1": "declared_CIF_fractional_coordinate",
        "/value/0/fractional_coordinates/2": "declared_CIF_fractional_coordinate",
        "/value/0/occupancy": "declared_CIF_occupancy",
        "/value/1/fractional_coordinates/0": "declared_CIF_fractional_coordinate",
        "/value/1/fractional_coordinates/1": "declared_CIF_fractional_coordinate",
        "/value/1/fractional_coordinates/2": "declared_CIF_fractional_coordinate",
        "/value/1/occupancy": "declared_CIF_occupancy",
    },
    "crb2_cif:declared_symmetry_operations": {},
    "crb2_cif:reported_hall_symbol": {},
    "crb2_cif:cell_formula_units_z": {"/value": "listed_CIF_source_metadata"},
    "ysc:calculation_method_and_origin_statement": {
        "/source_window/tc_expression_pressure": "source_window_condition",
        "/source_window/tc_expression": "source_window_condition",
        "/source_window/stability_pressure_range_gpa": "source_stability_extent",
    },
    "ysc:electron_phonon_lambda_source_value": {},
    "ysc:omega_log_source_value": {},
    "ysc:mu_star_source_parameter": {},
    "lasm:source_preparation_description": {},
    "lasm:source_anneal_temperature_options": {
        "/value/mdr_row155423_options/0": "source_preparation_option",
        "/value/mdr_row155423_options/1": "source_preparation_option",
        "/value/primary_series_recommendation": "source_series_preparation_recommendation",
    },
    "lasm:susceptibility_transition_definition": {
        "/value/mdr_tcsus_values/0/quantity": "source_value_component",
        "/value/mdr_tcsus_values/1/quantity": "source_value_component",
    },
    "lasm:tc_applied_pressure_context": {
        "/value/maximum_applied_pressure": "source_study_pressure_extent",
        "/value/resistance_temperature_extent_k": "source_study_temperature_extent",
        "/value/width_criterion_percent": "source_curve_width_thresholds",
        "/source_subject/source_x": "source_subject_parameter",
    },
    "lasm:meissner_measurement_method_and_conditions": {
        "/value/database_row155423_vols_raw": "source_value_component",
        "/value/source_evaluation_temperature": "source_value_component",
        "/value/dc_zfc_fc_field": "source_value_component",
    },
    "sn_in:source_composition_and_local_x_definition": {
        "/value/local_x": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "sn_in:hall_carrier_density_and_conditions": {
        "/value/carrier_density_raw": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "sn_in:sample_measurement_context": {
        "/value/ac_excitation": "source_value_component",
        "/value/hc2_source_value": "source_value_component",
        "/value/hc2_temperature": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "sn_in:reported_gap_or_pairing_source_claim": {
        "/value/spectroscopic_dip_energy_scale": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "sr_ni:source_local_Ni_composition_definition": {
        "/value/local_nominal_x": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "sr_ni:source_transition_criterion": {
        "/value/fraction": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "sr_ni:hc2_curve_slope_and_model": {
        "/value/hc2_slope": "source_value_component",
        "/value/linear_extrapolated_hc2_zero_k": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "sr_ni:sample_anneal_conditions": {
        "/value/cited_source_series_protocol/temperature": "cited_series_preparation_protocol",
        "/value/cited_source_series_protocol/duration": "cited_series_preparation_protocol",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "bapb:source_local_composition_definition": {
        "/value/source_local_x": "source_value_component",
        "/value/source_tc": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "bapb:reported_short_range_order_claim": {
        "/value/interpreted_crossover_temperature": "source_interpretive_crossover",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "bapb:optical_measurement_temperature_window": {
        "/value/equilibrium_optical_example": "source_measurement_example",
        "/value/transient_drude_example": "source_measurement_example",
        "/value/interpretive_crossover": "source_interpretive_crossover",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "bapb:optical_probe_method": {
        "/value/equilibrium_frequency_extent_thz": "source_probe_frequency_extent",
        "/value/transient_probe_frequency_extent_thz": "source_probe_frequency_extent",
        "/value/doped_sample_pump_frequency": "source_value_component",
        "/value/pulse_duration_extent_fs": "source_pulse_duration_extent",
        "/value/fluence": "source_value_component",
        "/source_subject/source_local_x": "source_subject_parameter",
    },
    "motm:source_rare_earth_member_definition": {},
    "motm:reported_magnetic_order_and_temperature": {
        "/value/tm_source_tn": "source_order_transition_temperature"
    },
    "motm:magnetic_probe_method": {
        "/value/study_temperature_extent_k": "source_study_temperature_extent"
    },
    "motm:tm_member_transition_criterion": {
        "/value/source_tm_tc": "source_superconducting_transition_temperature"
    },
    "fese_cif:listed_atomic_sites": {
        "/value/0/fractional_coordinates/0": "declared_CIF_fractional_coordinate",
        "/value/0/fractional_coordinates/1": "declared_CIF_fractional_coordinate",
        "/value/0/fractional_coordinates/2": "declared_CIF_fractional_coordinate",
        "/value/0/occupancy": "declared_CIF_occupancy",
        "/value/0/u_iso": "source_refined_isotropic_displacement",
        "/value/1/fractional_coordinates/0": "declared_CIF_fractional_coordinate",
        "/value/1/fractional_coordinates/1": "declared_CIF_fractional_coordinate",
        "/value/1/fractional_coordinates/2": "declared_CIF_fractional_coordinate",
        "/value/1/occupancy": "declared_CIF_occupancy",
        "/value/1/u_iso": "source_refined_isotropic_displacement",
        "/source_window/source_cell_temperature": "source_window_condition",
    },
    "fese_cif:declared_symmetry_operations": {
        "/source_window/source_cell_temperature": "source_window_condition"
    },
    "fese_cif:reported_hall_symbol": {
        "/source_window/source_cell_temperature": "source_window_condition"
    },
    "fese_cif:cell_formula_units_z": {
        "/value": "source_cell_formula_units",
        "/source_window/source_cell_temperature": "source_window_condition",
    },
    "pt_extra:source_preparation_and_specific_heat_method": {},
    "pt_extra:source_heating_program": {
        "/value/peak_heating_temperature": "source_value_component"
    },
    "pt_extra:specific_heat_jump_over_tc": {
        "/value": "source_isoentropic_construction_result",
        "/source_window/source_analysis_temperature": "source_window_condition",
        "/source_window/comparison_field": "source_window_condition",
    },
    "pt_extra:specific_heat_analysis_context": {
        "/value/comparison_field": "source_value_component",
        "/value/bcs_ratio_assumption": "source_model_assumption",
        "/value/superconducting_volume_assumption": "source_model_assumption",
    },
    "pt_extra:electronic_specific_heat_coefficient_model": {
        "/value": "source_BCS_assumption_derived_estimate"
    },
}

_RANGE_UNITS = {
    "ysc:calculation_method_and_origin_statement": {
        "/source_window/stability_pressure_range_gpa": "GPa"
    },
    "lasm:tc_applied_pressure_context": {
        "/value/resistance_temperature_extent_k": "K",
        "/value/width_criterion_percent": "%",
    },
    "bapb:optical_probe_method": {
        "/value/equilibrium_frequency_extent_thz": "THz",
        "/value/transient_probe_frequency_extent_thz": "THz",
        "/value/pulse_duration_extent_fs": "fs",
    },
    "motm:magnetic_probe_method": {"/value/study_temperature_extent_k": "K"},
}


class SourcePropertyContractError(ValueError):
    """Static failure code; received source text is never echoed."""


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise SourcePropertyContractError(code)


def _bounded(value: object) -> None:
    """Reject non-JSON, excessive depth/size, nonfinite and private objects."""
    stack = [(value, 0)]
    count = 0
    forbidden = {
        "private_notes",
        "raw_record",
        "source_excerpt",
        "evidence_text",
        "private_context",
    }
    while stack:
        current, depth = stack.pop()
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, "json_bounds_exceeded")
        kind = type(current)
        if kind is dict:
            _require(len(current) <= MAX_CONTAINER_ITEMS, "json_bounds_exceeded")
            for key, child in current.items():
                _require(type(key) is str and key not in forbidden, "closed_json_required")
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif kind is list:
            _require(len(current) <= MAX_CONTAINER_ITEMS, "json_bounds_exceeded")
            stack.extend((child, depth + 1) for child in current)
        elif kind is str:
            try:
                encoded = current.encode("utf-8", errors="strict")
            except UnicodeError:
                raise SourcePropertyContractError("valid_utf8_required") from None
            _require(len(encoded) <= MAX_STRING_BYTES, "json_bounds_exceeded")
            _require(not any(ord(char) < 32 for char in current), "closed_json_required")
        elif kind is int:
            _require(abs(current) <= _SAFE_INTEGER, "safe_integer_required")
        elif kind is float:
            _require(math.isfinite(current), "finite_number_required")
        else:
            _require(current is None or kind is bool, "closed_json_required")


def canonical(value: object) -> bytes:
    """Canonical UTF-8 JSON used for entry/registry/projection identities."""
    _bounded(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


_BY_ID = {row[0]: row for row in _ENTRY_ROWS}
_FIELD_PROFILES = {row[4]: row[5] for row in _ENTRY_ROWS}
FIELD_PROFILES = dict(_FIELD_PROFILES)
COMPONENT_ROLES = copy.deepcopy(_COMPONENT_ROLES)
RANGE_UNITS = copy.deepcopy(_RANGE_UNITS)
SNAPSHOT_ENTRY_PINS = {
    pin: {row[0]: row[3] for row in _ENTRY_ROWS if row[1] == pin} for pin in _BATCHES
}
REGISTRY_SHA256 = digest(
    {
        "mapper_version": MAPPER_VERSION,
        "entries": [list(row) for row in _ENTRY_ROWS],
        "batches": _BATCHES,
        "component_roles": _COMPONENT_ROLES,
        "range_units": _RANGE_UNITS,
    }
)


def registry_inventory() -> dict[str, str]:
    """Detached inventory for the independently enforced SQL field/profile guard."""
    return dict(_FIELD_PROFILES)


@dataclass(frozen=True)
class PreparedBatch:
    source_json_sha256: str
    original_batch_sha256: str
    batch_id: str
    registry_sha256: str
    summary: dict
    observations: list[dict]


_AUTHORITY = {
    "formal_human_review": False,
    "formal_scientific_review": False,
    "scientific_acceptance": False,
    "ml_training_approved": False,
    "database_changed": False,
    "sample_identity_established": False,
    "phase_identity_established": False,
    "selected_result_association": "unestablished",
    "canonical_promotions": 0,
}
_OBSERVATION_KEYS = {
    "source_entry_id",
    "source_json_pointer",
    "entry_sha256",
    "field_id",
    "profile",
    "subject",
    "window",
    "source_role",
    "provenance",
    "values",
    "source_entry",
    "status",
    "authority",
    "display_context_material_id",
}
_QUANTITY_BASE_KEYS = {
    "raw_value",
    "value",
    "raw_unit",
    "unit",
    "approximate",
    "raw_uncertainty",
    "uncertainty",
    "uncertainty_interpretation",
    "uncertainty_normalization",
}
_QUANTITY_OPTIONAL_KEYS = {
    "unit_basis",
    "unit_source_field",
    "parse_status",
    "unit_review_reason",
}
_HALL_KEYS = {"raw_value", "value", "raw_unit", "unit", "uncertainty", "raw_display_basis"}


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _quantity(value: dict) -> None:
    keys = set(value)
    if keys == _HALL_KEYS:
        _require(type(value["raw_display_basis"]) is str, "closed_quantity_required")
    else:
        _require(
            _QUANTITY_BASE_KEYS <= keys <= _QUANTITY_BASE_KEYS | _QUANTITY_OPTIONAL_KEYS,
            "closed_quantity_required",
        )
        _require(type(value["approximate"]) is bool, "closed_quantity_required")
        for key in ("raw_uncertainty", "uncertainty_normalization"):
            _require(value[key] is None or type(value[key]) is str, "closed_quantity_required")
        _require(type(value["uncertainty_interpretation"]) is str, "closed_quantity_required")
        for key in keys & _QUANTITY_OPTIONAL_KEYS:
            _require(type(value[key]) is str, "closed_quantity_required")
    _require(
        type(value["raw_value"]) is str and bool(value["raw_value"]), "closed_quantity_required"
    )
    _require(_finite_number(value["value"]), "finite_quantity_required")
    _require(
        value["raw_unit"] is None or type(value["raw_unit"]) is str, "closed_quantity_required"
    )
    _require(value["unit"] is None or type(value["unit"]) is str, "closed_quantity_required")
    _require(
        value["uncertainty"] is None
        or (_finite_number(value["uncertainty"]) and value["uncertainty"] >= 0),
        "closed_quantity_required",
    )
    if value["unit"] is None:
        _require(
            value.get("parse_status") == "unit_requires_review", "unresolved_unit_status_required"
        )
    if value["raw_unit"] is None:
        _require(type(value.get("unit_basis")) is str, "unit_basis_required")


def _authority(value: dict) -> None:
    for key, expected in _AUTHORITY.items():
        _require(
            key in value and type(value[key]) is type(expected) and value[key] == expected,
            "pending_authority_required",
        )
    _require(
        value.get("public_release_completed_at_preparation") is False,
        "preparation_boundary_required",
    )


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def _project_values(entry: dict, row: tuple) -> dict:
    """Finite typed components retain exact pointers; no cross-entry joins."""
    field_id, profile = row[4:6]
    prefix = f"/entries/{row[2]}"
    values = {
        "kind": profile,
        "quantities": [],
        "ranges": [],
        "statements": [],
        "sites": [],
        "operations": [],
    }
    seen_components = set()

    def walk(current: object, path: str) -> None:
        if type(current) is dict:
            if {"raw_value", "value", "unit"} <= set(current):
                _quantity(current)
                role = _COMPONENT_ROLES[field_id].get(path)
                _require(role is not None, "registered_component_required")
                values["quantities"].append(
                    {
                        "json_pointer": prefix + path,
                        "component_role": role,
                        "quantity": copy.deepcopy(current),
                    }
                )
                seen_components.add(path)
            else:
                for key in sorted(current):
                    walk(current[key], path + "/" + _escape(key))
        elif type(current) is list:
            if path in _RANGE_UNITS.get(field_id, {}):
                _require(
                    bool(current) and all(_finite_number(item) for item in current),
                    "registered_numeric_extent_required",
                )
                values["ranges"].append(
                    {
                        "json_pointer": prefix + path,
                        "component_role": _COMPONENT_ROLES[field_id][path],
                        "unit": _RANGE_UNITS[field_id][path],
                        "values": copy.deepcopy(current),
                    }
                )
                seen_components.add(path)
            else:
                for index, child in enumerate(current):
                    walk(child, path + "/" + str(index))
        else:
            kind = {
                str: "text",
                bool: "boolean",
                int: "number",
                float: "number",
                type(None): "null",
            }.get(type(current))
            _require(kind is not None, "closed_scalar_required")
            values["statements"].append(
                {"json_pointer": prefix + path, "scalar_kind": kind, "value": current}
            )

    # Context/subject quantities remain typed but are never promoted to the
    # property's value (e.g. stability Pmax, nominal x, example T or assumptions).
    for key in ("value", "source_window", "source_subject"):
        walk(entry[key], "/" + key)
    _require(seen_components == set(_COMPONENT_ROLES[field_id]), "registered_components_required")
    if profile == "cif_atomic_sites":
        _require(type(entry["value"]) is list and len(entry["value"]) == 2, "listed_sites_required")
        cr_keys = {
            "label",
            "element",
            "fractional_coordinates",
            "occupancy",
            "physical_source_line",
            "source_line_sha256",
        }
        fe_keys = {
            "label",
            "element",
            "fractional_coordinates",
            "occupancy",
            "source_multiplicity_raw",
            "u_iso",
            "source_line",
        }
        for index, site in enumerate(entry["value"]):
            _require(
                type(site) is dict
                and set(site) in (cr_keys, fe_keys)
                and len(site["fractional_coordinates"]) == 3,
                "closed_listed_site_required",
            )
            values["sites"].append(
                {"json_pointer": prefix + f"/value/{index}", "value": copy.deepcopy(site)}
            )
    elif profile == "cif_declared_operations":
        operations = (
            entry["value"] if type(entry["value"]) is list else entry["value"]["operations_raw"]
        )
        expected_count = 24 if field_id.startswith("crb2_cif:") else 16
        _require(
            type(operations) is list
            and len(operations) == expected_count
            and all(type(item) is str for item in operations),
            "declared_operations_required",
        )
        values["operations"] = copy.deepcopy(operations)
    return values


def _map_entry(entry: dict, row: tuple) -> dict:
    _require(type(entry) is dict and digest(entry) == row[3], "pinned_source_entry_required")
    _require(
        entry.get("id") == row[0]
        and f"{entry.get('source_group')}:{entry.get('field')}" == row[4]
        and entry.get("source_role") == row[6],
        "registered_field_required",
    )
    _authority(entry)
    _require(
        entry.get("association_status") == "unestablished", "unestablished_association_required"
    )
    if row[5] == "unavailable":
        _require(
            entry["value"] is None and entry.get("inspection_status") == "source_unavailable",
            "unavailable_source_required",
        )
    sources = [entry["source"]] if "source" in entry else entry["sources"]
    locators = [entry["field_locator"]] if "field_locator" in entry else entry["field_locators"]
    _require(
        type(sources) is list and bool(sources) and type(locators) is list,
        "source_provenance_required",
    )
    return {
        "source_entry_id": row[0],
        "source_json_pointer": f"/entries/{row[2]}",
        "entry_sha256": row[3],
        "field_id": row[4],
        "profile": row[5],
        "subject": copy.deepcopy(entry["source_subject"]),
        "window": copy.deepcopy(entry["source_window"]),
        "source_role": row[6],
        "provenance": {
            "sources": copy.deepcopy(sources),
            "field_locators": copy.deepcopy(locators),
        },
        "values": _project_values(entry, row),
        "source_entry": copy.deepcopy(entry),
        "status": "pending",
        "authority": {**_AUTHORITY, "scope": "source_preparation"},
        "display_context_material_id": None,
    }


def validate_observation(projection: dict) -> dict:
    """Recompile against the immutable entry pin, including every typed role."""
    _bounded(projection)
    _require(
        type(projection) is dict and set(projection) == _OBSERVATION_KEYS,
        "closed_observation_required",
    )
    _require(type(projection["source_entry_id"]) is str, "registered_source_entry_required")
    row = _BY_ID.get(projection.get("source_entry_id"))
    _require(row is not None, "unsupported_source_entry")
    expected = _map_entry(projection["source_entry"], row)
    _require(canonical(expected) == canonical(projection), "exact_projection_required")
    return copy.deepcopy(expected)


def _duplicate_checked(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _nonfinite_constant(_value: str) -> None:
    raise SourcePropertyContractError("finite_number_required")


def _decode(raw_bytes: bytes) -> dict:
    _require(
        type(raw_bytes) is bytes and 0 < len(raw_bytes) <= MAX_SOURCE_BYTES,
        "bounded_source_bytes_required",
    )
    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeError:
        raise SourcePropertyContractError("valid_utf8_required") from None
    # Bound nesting before json.loads, including payloads too deep to parse.
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            _require(depth <= MAX_DEPTH, "json_bounds_exceeded")
        elif char in "]}":
            depth -= 1
            _require(depth >= 0, "invalid_json")
    try:
        value = json.loads(
            text, object_pairs_hook=_duplicate_checked, parse_constant=_nonfinite_constant
        )
    except SourcePropertyContractError:
        raise
    except (ValueError, RecursionError):
        raise SourcePropertyContractError("invalid_json") from None
    _bounded(value)
    _require(type(value) is dict, "closed_snapshot_required")
    return value


def compile_public_snapshot(raw_bytes: bytes) -> PreparedBatch:
    """Map one of two exact bounded public snapshots; unknown batches fail closed."""
    document = _decode(raw_bytes)
    pin = hashlib.sha256(raw_bytes).hexdigest()
    batch = _BATCHES.get(pin)
    _require(batch is not None, "unsupported_public_snapshot")
    _require(
        document.get("version") == batch["version"]
        and document.get("original_batch_sha256") == batch["original_batch_sha256"],
        "snapshot_identity_required",
    )
    _authority(document)
    entries = document.get("entries")
    _require(
        type(entries) is list and len(entries) == batch["entry_count"], "snapshot_count_required"
    )
    observations = []
    for index, entry in enumerate(entries):
        _require(type(entry) is dict and type(entry.get("id")) is str, "source_entry_required")
        row = _BY_ID.get(entry["id"])
        _require(
            row is not None and row[1] == pin and row[2] == index,
            "snapshot_entry_identity_required",
        )
        observations.append(_map_entry(entry, row))
    expression_count = sum(obs["source_entry"]["value"] is not None for obs in observations)
    _require(expression_count == batch["source_expression_count"], "snapshot_count_required")
    summary = {
        "source_task_count": len(observations),
        "source_expression_count": expression_count,
        "source_unavailable_count": len(observations) - expression_count,
        "source_group_count": len({obs["source_entry"]["source_group"] for obs in observations}),
        "quantity_component_count": sum(len(obs["values"]["quantities"]) for obs in observations),
        "quantity_component_scope": "includes source value, repeated subject and conditional context",
        "independent_experiments": None,
        "counts_are_independent_experiments": False,
        "canonical_promotions": 0,
        "scientific_acceptance": False,
        "selected_result_association": "unestablished",
        "status": "pending",
    }
    return PreparedBatch(
        source_json_sha256=pin,
        original_batch_sha256=batch["original_batch_sha256"],
        batch_id="source-property-batch:" + pin,
        registry_sha256=REGISTRY_SHA256,
        summary=summary,
        observations=observations,
    )
