"""Tests use the actual pinned coordinate batches, not fabricated physical results."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "build_discovery_research_catalogue.py"
SPEC = importlib.util.spec_from_file_location("catalogue_builder", MODULE)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class CatalogueBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = BUILDER.build()

    def test_rebuild_is_deterministic_and_matches_retained_version(self):
        encoded = BUILDER.pretty(self.result)
        self.assertEqual(encoded, BUILDER.pretty(BUILDER.build()))
        self.assertEqual(encoded, (BUILDER.OUTPUT_DIR / (self.result["version"] + ".json")).read_bytes())

    def test_semantic_dedup_retains_distinct_cif_bytes(self):
        self.assertEqual(self.result["counts"], {"source_entries": 20, "coordinate_states": 19, "composition_groups": 8, "duplicate_occurrences": 1})
        shared = [s for s in self.result["states"] if len(s["occurrence_ids"]) == 2]
        self.assertEqual(len(shared), 1)
        self.assertEqual((shared[0]["formula"], shared[0]["strain_micro_percent"]), ("Mg7AlB16", 0))
        rows = [o for o in self.result["occurrences"] if o["state_id"] == shared[0]["id"]]
        self.assertNotEqual(rows[0]["cif_sha256"], rows[1]["cif_sha256"])

    def test_rejects_structural_replacement_despite_preserved_formula_counts(self):
        state = self.result["states"][0]
        occurrence = next(o for o in self.result["occurrences"] if o["id"] == state["primary_occurrence_id"])
        text = occurrence["cif_text"].replace("0.16665", "0.16666", 1)
        with self.assertRaises(ValueError):
            BUILDER.verify_cif(text, state["cell"], state["atoms"], self.result["sources"][0])

    def test_projection_retains_exact_original_downloads(self):
        manifest = json.loads(BUILDER.DEFAULT_MANIFEST.read_bytes())
        packages = {p["sha256"]: json.loads((BUILDER.INPUT_DIR / p["filename"]).read_bytes()) for p in manifest["batches"]}
        for occurrence in self.result["occurrences"]:
            index = int(occurrence["source_locator"].split("/")[-1])
            original = packages[occurrence["source_batch_sha256"]]["candidates"][index]
            self.assertEqual(occurrence["cif_text"], original["cif"])
            self.assertEqual(occurrence["legacy_candidate_id"], original["id"])

    def test_states_remain_unknown_unranked_and_unapproved(self):
        for state in self.result["states"]:
            self.assertTrue(all(v is None for v in state["conditions"].values()))
            self.assertEqual(state["status"], "unrelaxed")
            self.assertIsNone(state["score"])
            self.assertTrue(all(v == {"status": "unknown", "value": None} for v in state["physical_axes"].values()))

    def test_plain_decimal_canonical_numbers_match_cross_language_contract(self):
        self.assertEqual(BUILDER.canonical({"small": 1e-7, "zero": -0.0, "large": 1e21}), '{"large":1000000000000000000000,"small":0.0000001,"zero":0}')

    def test_rejects_changed_inputs_even_when_input_manifest_hash_is_updated(self):
        mutations = [
            lambda data: data["source_reference"]["lattice"]["a"].update(value=9),
            lambda data: data["boundary"].update(pressure_gpa=0),
            lambda data: data["boundary"].update(tc_calculated=True),
            lambda data: data["candidates"][0]["atoms"][0].update(element="Ca"),
            lambda data: data["candidates"][0].update(id="site-candidate:" + "0" * 64),
        ]
        original_manifest = json.loads(BUILDER.DEFAULT_MANIFEST.read_bytes())
        first = original_manifest["batches"][0]
        original_bytes = (BUILDER.INPUT_DIR / first["filename"]).read_bytes()
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                manifest = json.loads(json.dumps(original_manifest))
                manifest["batches"] = [manifest["batches"][0]]
                source = json.loads(original_bytes)
                mutate(source)
                updated = BUILDER.pretty(source)
                (folder / first["filename"]).write_bytes(updated)
                manifest["batches"][0]["sha256"] = BUILDER.digest(updated)
                path = folder / "inputs.json"
                path.write_bytes(BUILDER.pretty(manifest))
                with patch.object(BUILDER, "INPUT_DIR", folder), self.assertRaises(ValueError):
                    BUILDER.build(path)

    def test_rejects_duplicate_source_occurrences(self):
        manifest = json.loads(BUILDER.DEFAULT_MANIFEST.read_bytes())
        manifest["batches"].append(manifest["batches"][0])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inputs.json"
            path.write_bytes(BUILDER.pretty(manifest))
            with self.assertRaisesRegex(ValueError, "Duplicate source occurrence"):
                BUILDER.build(path)


if __name__ == "__main__":
    unittest.main()
