"""Pure scientific-scope/closure checks against the actual two public snapshots.

No fixture copies, database, remote sources, reviewer impersonation or canonical
material mutation are needed to verify this finite handoff.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from services import source_property_contract as contract

PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public" / "research-pilots"
FILES = (
    "materials-source-observations-2026-10-02.json",
    "materials-source-followup-2026-10-02.json",
)
PUBLIC_PINS = (
    "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
    "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
)
ORIGINAL_PINS = (
    "947e13d7947f27d9d291a3783ad262308babcec14c186de0e5fbf1c70b8a884f",
    "af823526b7c2764c75c116c2d42e48fde3746feac8e5d6635fecaa34f7a41615",
)


def resolve(document, pointer):
    """Independent JSON-pointer walk, including escaped property names."""
    current = document
    for token in pointer.removeprefix("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


class SourcePropertyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raws = [(PUBLIC / filename).read_bytes() for filename in FILES]
        cls.documents = [json.loads(raw) for raw in cls.raws]
        cls.batches = [contract.compile_public_snapshot(raw) for raw in cls.raws]
        cls.by_field = {obs["field_id"]: obs for batch in cls.batches for obs in batch.observations}

    def quantity(self, field_id, relative_path="/value"):
        obs = self.by_field[field_id]
        pointer = obs["source_json_pointer"] + relative_path
        return next(item for item in obs["values"]["quantities"] if item["json_pointer"] == pointer)

    def rejected(self, value, code=None):
        with self.assertRaises(contract.SourcePropertyContractError) as raised:
            contract.validate_observation(value)
        if code:
            self.assertEqual(str(raised.exception), code)

    def test_actual_files_are_two_exact_pinned_snapshots_without_resource_copies(self):
        self.assertEqual(tuple(hashlib.sha256(raw).hexdigest() for raw in self.raws), PUBLIC_PINS)
        self.assertEqual(
            tuple(batch.original_batch_sha256 for batch in self.batches), ORIGINAL_PINS
        )
        self.assertEqual(set(contract.SNAPSHOT_ENTRY_PINS), set(PUBLIC_PINS))
        self.assertEqual(len(contract.registry_inventory()), 49)
        self.assertEqual(len({obs["source_entry_id"] for obs in self.by_field.values()}), 49)
        for batch in self.batches:
            self.assertEqual(batch.registry_sha256, contract.REGISTRY_SHA256)
            self.assertEqual(batch.batch_id, "source-property-batch:" + batch.source_json_sha256)

    def test_49_tasks_are_46_source_expressions_and_three_unavailable_not_experiments(self):
        summaries = [batch.summary for batch in self.batches]
        self.assertEqual([s["source_task_count"] for s in summaries], [15, 34])
        self.assertEqual([s["source_expression_count"] for s in summaries], [15, 31])
        self.assertEqual([s["source_unavailable_count"] for s in summaries], [0, 3])
        for summary in summaries:
            self.assertIsNone(summary["independent_experiments"])
            self.assertIs(summary["counts_are_independent_experiments"], False)
            self.assertEqual(summary["canonical_promotions"], 0)
            self.assertIs(summary["scientific_acceptance"], False)

    def test_all_original_entries_and_every_typed_component_resolve_exactly(self):
        for document, batch in zip(self.documents, self.batches, strict=True):
            for obs in batch.observations:
                with self.subTest(entry=obs["source_entry_id"]):
                    original = resolve(document, obs["source_json_pointer"])
                    self.assertEqual(obs["source_entry"], original)
                    self.assertEqual(obs["entry_sha256"], contract.digest(original))
                    self.assertEqual(obs["subject"], original["source_subject"])
                    self.assertEqual(obs["window"], original["source_window"])
                    self.assertEqual(obs["source_role"], original["source_role"])
                    self.assertEqual(contract.validate_observation(obs), obs)
                    self.assertEqual(
                        set(obs["values"]),
                        {"kind", "quantities", "ranges", "statements", "sites", "operations"},
                    )
                    for item in obs["values"]["quantities"]:
                        self.assertEqual(item["quantity"], resolve(document, item["json_pointer"]))
                    for item in obs["values"]["ranges"]:
                        self.assertEqual(item["values"], resolve(document, item["json_pointer"]))
                    for item in obs["values"]["statements"] + obs["values"]["sites"]:
                        self.assertEqual(item["value"], resolve(document, item["json_pointer"]))

    def test_source_provenance_locators_hashes_are_preserved_without_collapsing_scopes(self):
        for document, batch in zip(self.documents, self.batches, strict=True):
            for obs in batch.observations:
                original = resolve(document, obs["source_json_pointer"])
                sources = [original["source"]] if "source" in original else original["sources"]
                locators = (
                    [original["field_locator"]]
                    if "field_locator" in original
                    else original["field_locators"]
                )
                self.assertEqual(
                    obs["provenance"], {"sources": sources, "field_locators": locators}
                )
                self.assertEqual(
                    contract.SNAPSHOT_ENTRY_PINS[batch.source_json_sha256][original["id"]],
                    obs["entry_sha256"],
                )

    def test_pending_flags_cannot_imply_human_review_sample_phase_or_canonical(self):
        for obs in self.by_field.values():
            self.assertEqual(obs["status"], "pending")
            self.assertIsNone(obs["display_context_material_id"])
            self.assertEqual(obs["authority"]["selected_result_association"], "unestablished")
            self.assertEqual(obs["authority"]["canonical_promotions"], 0)
            self.assertEqual(obs["authority"]["scope"], "source_preparation")
            for key in (
                "formal_human_review",
                "formal_scientific_review",
                "scientific_acceptance",
                "ml_training_approved",
                "database_changed",
                "sample_identity_established",
                "phase_identity_established",
            ):
                self.assertIs(obs["authority"][key], False)

    def test_negative_slope_and_competing_model_estimates_keep_distinct_roles(self):
        slope = self.by_field["pt:hc2_temperature_slope"]
        self.assertEqual(self.quantity(slope["field_id"])["quantity"]["value"], -2.8)
        self.assertEqual(self.quantity(slope["field_id"])["quantity"]["raw_value"], "-2.8")
        self.assertEqual(slope["source_role"], "source_curve_derived_slope")
        whh = self.by_field["pt:hc2_whh_orbital_zero_temperature"]
        linear = self.by_field["pt:hc2_linear_zero_temperature"]
        self.assertEqual(self.quantity(whh["field_id"])["quantity"]["value"], 45)
        self.assertEqual(self.quantity(linear["field_id"])["quantity"]["value"], 65)
        self.assertNotEqual(whh["window"], linear["window"])
        self.assertIsNone(slope["window"]["pressure"])
        self.assertEqual(slope["window"]["curve_criterion_raw"], "50% resistive transition")

    def test_cs_two_fit_windows_su_and_london_label_are_not_joined(self):
        ambient = self.by_field["cs_nb:ambient_fitted_tc"]
        table = self.by_field["cs_nb:zero_gpa_table_tc"]
        self.assertEqual(self.quantity(ambient["field_id"])["quantity"]["value"], 4.70)
        self.assertEqual(self.quantity(ambient["field_id"])["quantity"]["uncertainty"], 0.03)
        self.assertEqual(self.quantity(table["field_id"])["quantity"]["value"], 3.000)
        self.assertEqual(self.quantity(table["field_id"])["quantity"]["uncertainty"], 0.006)
        self.assertIsNone(ambient["window"]["pressure_gpa"])
        self.assertEqual(table["window"]["pressure"]["value"], 0)
        london = self.by_field["cs_nb:zero_gpa_table_penetration"]
        self.assertEqual(london["window"]["raw_row_label"], r"\lambda(T>0) (nm)")
        self.assertIsNone(london["window"]["measurement_temperature_k"])
        self.assertEqual(self.quantity(london["field_id"])["quantity"]["unit"], "nm")
        self.assertNotIn("lambda_eph", london["field_id"])
        self.assertEqual(
            self.quantity("cs_nb:zero_gpa_table_gap_1")["quantity"]["uncertainty"], 0.09
        )

    def test_cr_cif_sites_coordinates_occupancy_and_z_keep_implicit_unit_basis(self):
        sites = self.by_field["crb2_cif:listed_atomic_sites"]
        self.assertEqual(len(sites["values"]["sites"]), 2)
        boron = sites["values"]["sites"][0]["value"]
        self.assertEqual(
            [q["raw_value"] for q in boron["fractional_coordinates"]], ["0.3333", "0.6667", "0.5"]
        )
        self.assertEqual(boron["fractional_coordinates"][0]["value"], 0.3333)
        for index, coordinate in enumerate(boron["fractional_coordinates"]):
            self.assertIsNone(coordinate["raw_unit"])
            self.assertEqual(coordinate["unit"], "fractional")
            self.assertEqual(coordinate["unit_source_field"], "_atom_site_fract_" + "xyz"[index])
            self.assertEqual(coordinate["unit_basis"], "cif_fractional_coordinate_field")
        occupancy = boron["occupancy"]
        self.assertIsNone(occupancy["raw_unit"])
        self.assertEqual(occupancy["unit_source_field"], "_atom_site_occupancy")
        z = self.quantity("crb2_cif:cell_formula_units_z")["quantity"]
        self.assertIsNone(z["raw_unit"])
        self.assertEqual(z["unit_source_field"], "_cell_formula_units_Z")
        self.assertEqual(
            len(self.by_field["crb2_cif:declared_symmetry_operations"]["values"]["operations"]), 24
        )
        self.assertIsNone(sites["window"]["temperature_k"])
        self.assertIsNone(sites["window"]["pressure_gpa"])

    def test_fe_refined_site_su_and_source_temperature_do_not_establish_sample(self):
        obs = self.by_field["fese_cif:listed_atomic_sites"]
        fe, se = [item["value"] for item in obs["values"]["sites"]]
        self.assertEqual(fe["occupancy"]["raw_value"], "0.996(3)")
        self.assertEqual(fe["occupancy"]["uncertainty"], 0.003)
        self.assertEqual(se["fractional_coordinates"][2]["raw_value"], "0.26526(14)")
        self.assertEqual(se["fractional_coordinates"][2]["uncertainty"], 0.00014)
        self.assertEqual(obs["window"]["source_cell_temperature"]["value"], 295)
        self.assertEqual(
            len(self.by_field["fese_cif:declared_symmetry_operations"]["values"]["operations"]), 16
        )
        self.assertIs(obs["authority"]["sample_identity_established"], False)

    def test_lasm_fraction_guide_unit_and_curve_assignment_remain_unresolved(self):
        obs = self.by_field["lasm:meissner_measurement_method_and_conditions"]
        q = self.quantity(obs["field_id"], "/value/database_row155423_vols_raw")["quantity"]
        self.assertEqual(q["value"], 80)
        self.assertIsNone(q["raw_unit"])
        self.assertEqual(q["unit"], "%")
        self.assertIn("column102", q["unit_basis"])
        self.assertEqual(
            obs["source_entry"]["value"]["source80_exact_dc_or_ac_curve_assignment"],
            "unestablished",
        )
        self.assertIs(obs["window"]["paper_shielding_is_automatically_meissner"], False)
        preparation = self.by_field["lasm:source_anneal_temperature_options"]
        options = preparation["source_entry"]["value"]
        self.assertEqual([q["value"] for q in options["mdr_row155423_options"]], [800, 750])
        self.assertEqual(options["mdr_option_relationship"], "or")

    def test_printed_pt_unit_conflict_and_gamma_assumptions_are_not_repaired(self):
        conflict = self.quantity("pt_extra:specific_heat_jump_over_tc")["quantity"]
        self.assertEqual(conflict["raw_unit"], "mJ/mol K")
        self.assertIsNone(conflict["unit"])
        self.assertEqual(conflict["parse_status"], "unit_requires_review")
        gamma = self.by_field["pt_extra:electronic_specific_heat_coefficient_model"]
        self.assertEqual(gamma["source_role"], "source_BCS_assumption_derived_estimate")
        self.assertEqual(
            gamma["window"], {"bcs_ratio": 1.43, "assumed_superconducting_volume_percent": 100}
        )
        self.assertEqual(self.quantity(gamma["field_id"])["quantity"]["value"], 14)

    def test_order_temperature_tc_and_example_temperatures_have_separate_roles(self):
        tn = self.quantity("motm:reported_magnetic_order_and_temperature", "/value/tm_source_tn")
        tc = self.quantity("motm:tm_member_transition_criterion", "/value/source_tm_tc")
        self.assertEqual((tn["quantity"]["value"], tc["quantity"]["value"]), (17, 24))
        self.assertEqual(tn["component_role"], "source_order_transition_temperature")
        self.assertEqual(tc["component_role"], "source_superconducting_transition_temperature")
        self.assertIn(
            "χ′",
            self.by_field["motm:tm_member_transition_criterion"]["source_entry"]["value"][
                "source_criterion_raw"
            ],
        )
        optical = self.quantity(
            "bapb:optical_measurement_temperature_window", "/value/transient_drude_example"
        )
        self.assertEqual(optical["component_role"], "source_measurement_example")
        self.assertEqual(optical["quantity"]["value"], 100)

    def test_study_extents_are_not_per_tc_conditions_and_width_threshold_order_is_preserved(self):
        ysc = self.by_field["ysc:calculation_method_and_origin_statement"]
        extent = ysc["values"]["ranges"][0]
        self.assertEqual(extent["values"], [140, 250])
        self.assertEqual(extent["component_role"], "source_stability_extent")
        pressure = self.quantity(ysc["field_id"], "/source_window/tc_expression_pressure")
        self.assertEqual(pressure["quantity"]["value"], 140)
        study_pmax = self.quantity(
            "lasm:tc_applied_pressure_context", "/value/maximum_applied_pressure"
        )
        self.assertEqual(study_pmax["component_role"], "source_study_pressure_extent")
        thresholds = next(
            item
            for item in self.by_field["lasm:tc_applied_pressure_context"]["values"]["ranges"]
            if item["json_pointer"].endswith("/width_criterion_percent")
        )
        self.assertEqual(thresholds["values"], [90, 10])
        self.assertEqual(thresholds["component_role"], "source_curve_width_thresholds")

    def test_three_epc_fields_remain_explicit_unavailable_not_zero_or_no_reporting(self):
        for field in (
            "electron_phonon_lambda_source_value",
            "omega_log_source_value",
            "mu_star_source_parameter",
        ):
            obs = self.by_field["ysc:" + field]
            self.assertEqual(obs["profile"], "unavailable")
            self.assertIsNone(obs["source_entry"]["value"])
            self.assertEqual(obs["source_entry"]["inspection_status"], "source_unavailable")
            self.assertEqual(obs["values"]["quantities"], [])
            self.assertEqual(obs["values"]["statements"][0]["scalar_kind"], "null")
            self.assertEqual(obs["status"], "pending")

    def test_original_superscript_hall_density_stays_finite_and_not_flattened(self):
        q = self.quantity(
            "sn_in:hall_carrier_density_and_conditions", "/value/carrier_density_raw"
        )["quantity"]
        self.assertEqual(q["raw_value"], "8 × 10²⁰")
        self.assertEqual(q["value"], 8e20)
        self.assertEqual(q["unit"], "cm⁻³")
        self.assertIn("superscript", q["raw_display_basis"])

    def test_changed_entry_with_updated_hash_is_not_an_allowed_source(self):
        obs = copy.deepcopy(self.by_field["crb2_cif:listed_atomic_sites"])
        obs["source_entry"]["value"][0]["fractional_coordinates"][0].update(
            raw_value="0.25", value=0.25
        )
        obs["entry_sha256"] = contract.digest(obs["source_entry"])
        self.rejected(obs, "pinned_source_entry_required")

    def test_projection_role_pointer_unit_authority_and_association_mutations_are_refused(self):
        original = self.by_field["cs_nb:zero_gpa_table_penetration"]
        mutations = (
            lambda v: v["values"]["quantities"][0].update(component_role="electron_phonon_lambda"),
            lambda v: v["values"]["quantities"][0].update(json_pointer="/entries/6/value"),
            lambda v: v["values"]["quantities"][0]["quantity"].update(unit="dimensionless"),
            lambda v: v["authority"].update(formal_human_review=True),
            lambda v: v["authority"].update(scope="pending_ledger_runtime"),
            lambda v: v.update(display_context_material_id="invented-sample-link"),
            lambda v: v.update(status="accepted"),
            lambda v: v["provenance"]["sources"][0].update(
                source_url="https://unrelated.example/paper"
            ),
            lambda v: v["values"].update(generic_payload={"unknown_property": 1}),
        )
        for mutate in mutations:
            obs = copy.deepcopy(original)
            mutate(obs)
            self.rejected(obs)
        extent = copy.deepcopy(self.by_field["lasm:tc_applied_pressure_context"])
        extent["values"]["ranges"][0]["unit"] = "GPa"
        self.rejected(extent)

    def test_source_context_and_private_objects_cannot_be_smuggled_into_projection(self):
        for location in ("values", "window", "source_entry", "provenance"):
            obs = copy.deepcopy(self.by_field["pt:hc2_temperature_slope"])
            obs[location]["private_notes"] = "THIS_PRIVATE_CONTENT_MUST_NOT_APPEAR_IN_ERROR"
            with self.assertRaises(contract.SourcePropertyContractError) as caught:
                contract.validate_observation(obs)
            self.assertNotIn("PRIVATE_CONTENT", str(caught.exception))
        invalid_id = copy.deepcopy(self.by_field["pt:hc2_temperature_slope"])
        invalid_id["source_entry_id"] = {"unknown": "value"}
        self.rejected(invalid_id)

    def test_input_reformatting_and_new_batches_are_unsupported_not_silently_added(self):
        for document in self.documents:
            changed = copy.deepcopy(document)
            changed["entries"][0]["value"] = None
            with self.assertRaisesRegex(
                contract.SourcePropertyContractError, "unsupported_public_snapshot"
            ):
                contract.compile_public_snapshot(json.dumps(changed).encode())
        reordered = json.dumps(self.documents[0], sort_keys=True).encode()
        with self.assertRaisesRegex(
            contract.SourcePropertyContractError, "unsupported_public_snapshot"
        ):
            contract.compile_public_snapshot(reordered)

    def test_duplicate_nonfinite_deep_large_utf8_and_private_json_are_rejected(self):
        cases = (
            b'{"entries":[],"entries":[]}',
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":1e999}',
            b'{"value":9007199254740992}',
            b"[" * 1000 + b"0" + b"]" * 1000,
            b'{"value":"' + b"x" * 5000 + b'"}',
            b"x" * (contract.MAX_SOURCE_BYTES + 1),
            b'{"value":"\xff"}',
            b'{"value":"\\ud800"}',
            b'{"private_notes":"private"}',
            b'{"raw_record":{"value":1}}',
        )
        for raw in cases:
            with self.subTest(raw_length=len(raw)):
                with self.assertRaises(contract.SourcePropertyContractError):
                    contract.compile_public_snapshot(raw)

    def test_detached_outputs_and_object_key_reordering_preserve_valid_identity(self):
        obs = self.by_field["pt:hc2_temperature_slope"]
        reordered = json.loads(json.dumps(obs, sort_keys=True))
        self.assertEqual(contract.validate_observation(reordered), obs)
        detached = contract.validate_observation(obs)
        detached["window"]["pressure"] = "mutation"
        self.assertIsNone(obs["window"]["pressure"])
        inventory = contract.registry_inventory()
        inventory[obs["field_id"]] = "fake_profile"
        self.assertEqual(contract.registry_inventory()[obs["field_id"]], "quantity")
        self.assertEqual(contract.compile_public_snapshot(self.raws[0]).observations[0], obs)


if __name__ == "__main__":
    unittest.main()
