"""Private-source replay tests; no model execution or invented scientific data.

The real integration test requires SCLIB_JARVIS_EXPANSION_PLAN and
SCLIB_JARVIS_EPC_ARCHIVE, plus the existing SCLIB_GEMMI_RUNTIME on Python3.9.
The small synthetic unit fixture is geometry only and never a property reading.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("jarvis_expansion", Path(__file__).resolve().parents[1] / "build_discovery_jarvis_expansion.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


class DependencyByteClosureTest(unittest.TestCase):
    def test_tampered_dependency_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dependency.py"
            raw = b"value = 7\n"
            path.write_bytes(b"raise AssertionError('unverified source was executed')\n")
            with self.assertRaisesRegex(ValueError, "file_hash"):
                B.module("fixture_not_main", path, B.digest(raw))

    def test_symlink_and_nonregular_dependencies_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.py"
            raw = b"value = 7\n"
            source.write_bytes(raw)
            symlink = root / "linked.py"
            symlink.symlink_to(source)
            fifo = root / "pipe.py"
            os.mkfifo(fifo)
            large = root / "large.py"
            with large.open("wb") as handle:
                handle.truncate(1024 * 1024 + 1)
            for path in [symlink, fifo, large]:
                with self.subTest(path=path.name), self.assertRaises((ValueError, OSError)):
                    B.module("fixture_not_main", path, B.digest(raw))

    def test_path_replacement_after_verified_read_cannot_change_executed_or_reported_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dependency.py"
            raw = b"value = 7\n"
            path.write_bytes(raw)
            original = B.read_file

            def replace_after_read(*args, **kwargs):
                verified = original(*args, **kwargs)
                path.write_bytes(b"raise AssertionError('second path read was executed')\n")
                return verified

            with mock.patch.object(B, "read_file", side_effect=replace_after_read), mock.patch.object(B.os, "open", wraps=os.open) as opened:
                module, captured = B.module("fixture_not_main", path, B.digest(raw))
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(module.value, 7)
            self.assertEqual(module.__file__, str(path))
            self.assertEqual(captured, raw)
            self.assertNotEqual(B.digest(captured), B.digest(path.read_bytes()))


def geometry():
    lattice = [[3., .4, .2], [0., 4., .3], [0., 0., 5.]]
    fractions = [[.13, .27, .41], [.63, .77, .91]]
    cell = B.cell_from_matrix(lattice)
    return {"lattice_mat": lattice, "coords": [B.row_times_matrix(f, lattice) for f in fractions],
            "elements": ["Ti", "N"], "cartesian": True, "props": ["", ""],
            "abc": [cell[k] for k in ["a", "b", "c"]], "angles": [cell[k] for k in ["alpha", "beta", "gamma"]]}


class GeometryContractTest(unittest.TestCase):
    def test_row_vector_inversion_preserves_skew_source_frame(self):
        source = geometry()
        frac = B.validate_atoms(source)
        self.assertTrue(B.periodic_close(frac[0], [.13, .27, .41], 1e-12))
        model = B.parent_model({"atoms": source, "fractions": frac})
        self.assertEqual(model["lattice_matrix_angstrom"], [[6., .8, .4], [0., 8., .6], [0., 0., 10.]])
        self.assertEqual(len(model["atoms"]), 16)
        first = model["atoms"][0]
        self.assertTrue(B.periodic_close(first["fractional"], [.065, .135, .205], 1e-12))
        reconstructed = B.row_times_matrix(first["fractional"], model["lattice_matrix_angstrom"])
        for a, b in zip(reconstructed, source["coords"][0]):
            self.assertAlmostEqual(a, b, places=12)

    def test_source_disorder_wrong_flag_singular_and_periodic_overlap_rejected(self):
        mutations = [lambda x: x.update(cartesian=False), lambda x: x.update(occupancy=[1, .5]),
                     lambda x: x["props"].__setitem__(0, "partial occupancy"),
                     lambda x: x["lattice_mat"].__setitem__(2, [0., 0., 0.]),
                     lambda x: x["coords"].__setitem__(1, list(x["coords"][0])),
                     lambda x: x["abc"].__setitem__(0, 30.),
                     lambda x: x["coords"][0].__setitem__(0, float("nan"))]
        for change in mutations:
            value = geometry()
            change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                B.validate_atoms(value)

    def test_distinct_species_at_same_periodic_site_are_rejected(self):
        value = geometry()
        value["coords"][1] = [a+b for a, b in zip(value["coords"][0], value["lattice_mat"][0])]
        with self.assertRaisesRegex(ValueError, "duplicate_source"):
            B.validate_atoms(value)

    def test_unique_site_edit_conserves_exact_integer_counts_and_vacancy(self):
        source = geometry()
        model = B.parent_model({"atoms": source, "fractions": B.validate_atoms(source)})
        edits = [{"target_id": model["atoms"][0]["id"], "kind": "substitution", "element": "Zr", "original_element": "Ti"},
                 {"target_id": model["atoms"][1]["id"], "kind": "vacancy", "element": None, "original_element": "N"}]
        result = B.edited_model(model, edits)
        self.assertEqual(B.C.composition(result), {"N": 7, "Ti": 7, "Zr": 1})
        self.assertEqual(result[0]["fractional"], model["atoms"][0]["fractional"])
        self.assertEqual(model["atoms"][0]["element"], "Ti")
        for invalid in [edits + [edits[0]], [{**edits[0], "original_element": "Mo"}], [{**edits[0], "element": "Ti"}]]:
            with self.assertRaises(ValueError):
                B.edited_model(model, invalid)
        model["atoms"][0]["occupancy"] = 0
        with self.assertRaisesRegex(ValueError, "occupancy"):
            B.edited_model(model, [])

    def test_fractional_boundary_normalization_preserves_reviewed_image(self):
        source = geometry()
        parent = {"atoms": source, "fractions": [[-1e-17, 0, 0], [.5, .5, .5]]}
        model = B.parent_model(parent)
        self.assertEqual(model["atoms"][0]["fractional"], [.5, 0, 0])
        image1 = next(a for a in model["atoms"] if a["id"] == "jarvis-atom-0-cell-1-0-0")
        self.assertEqual(image1["fractional"], [0, 0, 0])

    def test_private_new_output_rejects_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            output = root / "new"
            B.write_new(output, {"a.json": b"first"})
            self.assertEqual((output / "a.json").stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "output_exists"):
                B.write_new(output, {"a.json": b"second"})
            self.assertEqual((output / "a.json").read_bytes(), b"first")

    def test_json_duplicates_nonfinite_and_wrong_raw_pin_rejected(self):
        for raw in [b'{"x":1,"x":2}', b'{"x":NaN}']:
            with self.assertRaises(ValueError):
                B.decode(raw)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "raw"
            p.write_bytes(b"source")
            with self.assertRaisesRegex(ValueError, "file_hash"):
                B.read_file(p, "0"*64)


@unittest.skipUnless(os.environ.get("SCLIB_JARVIS_EXPANSION_PLAN") and os.environ.get("SCLIB_JARVIS_EPC_ARCHIVE"),
                     "Real reviewed JARVIS inputs are explicit private artifacts, not CI fixtures")
class RealSourceIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("SCLIB_GEMMI_RUNTIME"):
            sys.path.insert(0, os.environ["SCLIB_GEMMI_RUNTIME"])
        import gemmi
        cls.gemmi = gemmi
        cls.plan = Path(os.environ["SCLIB_JARVIS_EXPANSION_PLAN"])
        cls.archive = Path(os.environ["SCLIB_JARVIS_EPC_ARCHIVE"])
        cls.loaded = B.load_sources(cls.plan, cls.archive)

    def test_real_117_states_replay_validate_and_do_not_inherit_provider_properties(self):
        artifacts, manifest = B.assemble(self.loaded, self.gemmi)
        original_read = Path.read_bytes

        def no_dependency_reopen(path):
            self.assertNotIn(path, {B.ROOT / name for name in B.GENERATOR_SOURCE_PINS})
            return original_read(path)

        with mock.patch.object(Path, "read_bytes", no_dependency_reopen):
            replay, _ = B.assemble(self.loaded, self.gemmi)
        self.assertEqual(artifacts, replay)
        self.assertEqual(manifest["counts"]["roles"], {"proposal": 33, "exploratory_control": 72, "baseline_control": 12})
        self.assertEqual(manifest["counts"]["states"], 117)
        self.assertEqual(manifest["counts"]["proposal_composition_groups_excluding_baselines"], 33)
        self.assertEqual(manifest["counts"]["confirmed_novel_groups"], 0)
        self.assertEqual(manifest["validation"]["pymatgen"], "not_run")
        self.assertEqual(manifest["generator_sources"], [{"path": name, "sha256": B.digest(raw)}
            for name, raw in B.GENERATOR_SOURCE_BYTES.items()])
        self.assertEqual(manifest["dependency_loading"], "fixed_sha256_verified_single_fd_bytes_compiled")
        studies = json.loads(artifacts["original-study-index.json"])
        self.assertEqual(len(studies), 12)
        self.assertEqual(studies[0]["raw_provider_fields"]["press"], "0 GPa")
        states = [state for name, raw in artifacts.items() if name.startswith("states/") for state in json.loads(raw)]
        for state in states:
            self.assertTrue(all(v is None for v in state["conditions"].values()))
            self.assertIsNone(state["score"])
            self.assertIsNone(state["high_potential"])
            self.assertFalse(state["formal_scientific_release"])
            self.assertNotIn("Tc", state)
            self.assertNotIn("stability", state)
            self.assertEqual(state["source_provider"], "JARVIS-DFT")
            self.assertTrue(all(v == {"status": "unknown", "value": None} for v in state["physical_axes"].values()))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "batch"
            B.write_new(output, artifacts)
            _, _, inputs = B.R.load_bundle(output, B.digest(artifacts["batch-manifest.json"]))
            self.assertEqual(len(inputs), 117)

    def test_real_recipe_classification_counts_coordinates_and_conditions_cannot_drift(self):
        edits = [lambda x: x.update(count_toward_additional_candidate_ideas=False),
                 lambda x: x.update(role="known_alloy_family_followup_reference"),
                 lambda x: x["planned_conditions"].update(target_pressure_gpa=0),
                 lambda x: x.update(score=1000),
                 lambda x: x["planned_composition"].update(Zr=100),
                 lambda x: x["edits"].__setitem__(1, copy.deepcopy(x["edits"][0])),
                 lambda x: x["edits"][0].update(source_element="Mg"),
                 lambda x: x["edits"][0].update(source_atom_index_zero_based=999),
                 lambda x: x["edits"][0]["planned_supercell_fractional"].__setitem__(0, .123)]
        for edit in edits:
            loaded = copy.deepcopy(self.loaded)
            edit(loaded["plan"]["ideas"][0])
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                B.reviewed_recipes(loaded)

    def test_real_known_followup_cannot_be_promoted_and_control_cannot_become_proposal(self):
        loaded = copy.deepcopy(self.loaded)
        known = next(x for x in loaded["plan"]["ideas"] if not x["count_toward_additional_candidate_ideas"])
        known.update(count_toward_additional_candidate_ideas=True, role="unscored_joint_modification_planning_idea")
        with self.assertRaisesRegex(ValueError, "classification_drift"):
            B.reviewed_recipes(loaded)
        loaded = copy.deepcopy(self.loaded)
        loaded["plan"]["controls"][0]["role"] = "proposal"
        with self.assertRaisesRegex(ValueError, "control_classification"):
            B.reviewed_recipes(loaded)

    def test_real_prior_composition_or_mdr_hit_blocks(self):
        loaded = copy.deepcopy(self.loaded)
        row = next(x for x in loaded["audit"]["entries"] if x["role"] == "proposal")
        row["frozen_capture_exact_composition_rows"] = 1
        with self.assertRaisesRegex(ValueError, "frozen_identity"):
            B.reviewed_recipes(loaded)
        loaded = copy.deepcopy(self.loaded)
        row = copy.deepcopy(next(x for x in loaded["audit"]["entries"] if x["role"] == "proposal"))
        row.update(id="existing-reference", role="reference")
        loaded["audit"]["entries"].append(row)
        with self.assertRaisesRegex(ValueError, "global_proposal"):
            B.reviewed_recipes(loaded)

    def test_actual_reviewed_files_and_original_archive_cannot_be_re_pinned(self):
        required = ["manifest.final.json", "expansion-plan.reviewed.json", "identity-results.json", "identity-input.json"]
        required += ["parents/" + p["plan"]["jid"] + ".atoms.source.json" for p in self.loaded["parents"].values()]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in required:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(B.read_file(self.plan / name))
            for name in ["manifest.final.json", "expansion-plan.reviewed.json", required[-1]]:
                path = root / name
                original = B.read_file(path)
                path.write_bytes(original + b" ")
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "file_hash"):
                    B.load_sources(root, self.archive)
                path.write_bytes(original)
            wrong_archive = root / "changed.zip"
            wrong_archive.write_bytes(B.read_file(self.archive) + b"changed")
            with self.assertRaisesRegex(ValueError, "file_hash"):
                B.load_sources(root, wrong_archive)

    def test_real_cif_species_occupancy_coordinate_or_lattice_tamper_rejected(self):
        artifacts, manifest = B.assemble(self.loaded, self.gemmi)
        entry = manifest["inputs"][0]
        compute = json.loads(artifacts[entry["path"]])
        text = artifacts[entry["cif"]["path"]].decode()
        for changed in [text.replace("_symmetry_Int_Tables_number 1", "_symmetry_Int_Tables_number 2"),
                        text.replace("S1 ", "S1 Xe ", 1),
                        text.replace("_cell_length_a ", "_cell_length_a 99 #", 1)]:
            with self.assertRaises((ValueError, RuntimeError)):
                B.verify_cif(changed, compute, self.gemmi)
        changed = copy.deepcopy(compute)
        changed["fractional_coordinates"][0][0] += .03
        with self.assertRaisesRegex(ValueError, "gemmi_species"):
            B.verify_cif(text, changed, self.gemmi)


if __name__ == "__main__":
    unittest.main()
