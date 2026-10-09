"""Source/replay and authority tests; no model training or physical calculations.

Set SCLIB_GEMMI_RUNTIME to an existing Python-compatible Gemmi installation for
the independent CIF tests. SCLIB_FRONTEND_RUNTIME additionally enables actual
TypeScript generator replay; neither test installs dependencies.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("ht_builder", Path(__file__).resolve().parents[1] / "build_discovery_high_throughput_batch.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


def fixture():
    batch = json.loads((B.ROOT / "docs/data/discovery-research-catalogue/sclib-combined-6e52be02d9dd.json").read_bytes())
    candidate = next(c for c in batch["candidates"] if c["strain_percent"] == 0 and len(c["edits"]) == 1)
    batch["candidates"] = [candidate]
    ref = batch["source_reference"]
    edits = [{"target_id": e["target"]["id"], "kind": e["operation"]["kind"], "element": e["operation"]["element"]} for e in candidate["edits"]]
    recipe = {"id": "retained-mgb2-test", "reference_id": ref["id"], "source_cif_sha256": ref["source"]["file_sha256"],
        "repeats": batch["baseline"]["repeats"], "role": "proposal", "route_id": "retained-model-regression",
        "strategy": "high_bandwidth", "edits": edits, "strain_percent": 0,
        "rationale": "Replay an actual retained coordinate model; no physical property is inherited.",
        "evidence": [{"url": ref["source"]["cif_url"], "scope": "Exact source coordinates only; no property inheritance."}]}
    batch["requested"] = {"referenceId": ref["id"], "repeats": recipe["repeats"], "strain": "0", "sites":
        [{"targetId": e["target_id"], "replacements": e["element"] if e["kind"] == "substitution" else "",
          "vacancy": e["kind"] == "vacancy", "unchanged": False} for e in edits]}
    payload = {"version": "discovery-site-candidates/1.0.0", "source_sha256": ref["source"]["file_sha256"], **batch["baseline"]}
    result = {"recipe_id": recipe["id"], "batch": batch, "parent_payload_json": json.dumps(payload, separators=(",", ":"))}
    return recipe, result


class RecipeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.refs = B.read_snapshot()
        cls.recipe, cls.result = fixture()

    def document(self, recipes=None):
        return {"schema_version": "discovery-high-throughput-recipes/1.0.0", "version": "bounded-test-v1",
                "source_snapshot_sha256": B.digest(self.raw), "recipes": recipes or [copy.deepcopy(self.recipe)]}

    def validate(self, document):
        return B.validate_recipes(document, self.refs, B.digest(self.raw))

    def test_rejects_unprovided_scientific_claim_and_changed_source(self):
        for key, value in [("score", 0.95), ("pressure_gpa", 0), ("source_cif_sha256", "0"*64),
                           ("reference_id", "invented-rocksalt")]:
            document = self.document()
            document["recipes"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(document)

    def test_exact_fractional_source_values_are_not_idealized(self):
        model = B.parent_model(self.refs["cod-1510641"], [2,2,2])
        self.assertEqual(model["atoms"][0]["fractional"], [0.16665, 0.33335, 0.25])
        self.assertNotEqual(model["atoms"][0]["fractional"][0], 1/6)

    def test_partial_occupancy_is_not_rounded(self):
        with self.assertRaisesRegex(ValueError, "occupancy"):
            B.parent_model(self.refs["cod-4002152"], [2,2,2])
        self.assertEqual(len(B.parent_model(self.refs["cod-9006864"], [2,2,2])["atoms"]), 40)

    def test_bounds_and_duplicate_targets_rejected_before_generator(self):
        for edit in [lambda r:r.update(repeats=[4,4,4]), lambda r:r.update(strain_percent=float("nan")),
                     lambda r:r["edits"].append(copy.deepcopy(r["edits"][0])), lambda r:r.update(role="published")]:
            doc = self.document()
            edit(doc["recipes"][0])
            with self.assertRaises(ValueError):
                self.validate(doc)
        with self.assertRaises(ValueError):
            self.validate(self.document([copy.deepcopy(self.recipe) for _ in range(201)]))

    def test_baseline_and_strain_cannot_masquerade_as_proposals(self):
        for role, strain, edits in [("proposal", 2, []), ("baseline_control", 0, self.recipe["edits"]),
                                   ("strain_control", 0, [])]:
            doc = self.document()
            doc["recipes"][0].update(role=role, strain_percent=strain, edits=edits)
            with self.assertRaises(ValueError):
                self.validate(doc)

    def test_output_refuses_reuse_without_modifying_old_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new"
            B.write_new(output, {"a.json": b"retained"})
            with self.assertRaises(ValueError):
                B.write_new(output, {"a.json": b"changed"})
            self.assertEqual((output/"a.json").read_bytes(), b"retained")
            self.assertEqual((output/"a.json").stat().st_mode & 0o777, 0o600)


class IndependentCifTest(RecipeContractTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if os.environ.get("SCLIB_GEMMI_RUNTIME"):
            sys.path.insert(0, os.environ["SCLIB_GEMMI_RUNTIME"])
        try:
            import gemmi
        except ImportError:
            raise unittest.SkipTest("Independent CIF tests require an existing Gemmi runtime")
        cls.gemmi = gemmi

    def test_actual_retained_cif_replays_and_output_is_deterministic(self):
        first, manifest = B.assemble(self.document(), [self.result], self.refs, B.digest(self.raw), self.gemmi)
        second, _ = B.assemble(self.document(), [self.result], self.refs, B.digest(self.raw), self.gemmi)
        self.assertEqual(first, second)
        item = manifest["inputs"][0]
        compute = json.loads(first[item["path"]])
        self.assertEqual(B.digest(first[item["cif"]["path"]]), compute["structure_sha256"])
        self.assertEqual(compute["structure_sha256"], item["cif"]["sha256"])
        self.assertTrue(all(v is None for v in compute["conditions"].values()))
        self.assertEqual(manifest["counts"]["scientifically_qualified_high_potential_groups"], 0)
        self.assertFalse(manifest["authority"]["execution_performed"])

    def test_changed_structure_occupancy_cell_request_or_lineage_rejected(self):
        mutations = [
            lambda r:r["batch"]["candidates"][0]["atoms"][0].update(occupancy=0.5),
            lambda r:r["batch"]["candidates"][0]["atoms"][0]["fractional"].__setitem__(0,0.234),
            lambda r:r["batch"]["candidates"][0]["cell"].update(a=19),
            lambda r:r["batch"]["requested"].update(strain="2"),
            lambda r:r["batch"]["boundary"].update(pressure_gpa=0),
            lambda r:r["batch"]["candidates"][0].update(id="combined-candidate:"+"0"*64),
            lambda r:r["batch"]["baseline"]["atoms"][0].update(occupancy=0.5),
            lambda r:r.update(parent_payload_json=r["parent_payload_json"].replace("Mg", "Ca",1)),
        ]
        for mutate in mutations:
            result = copy.deepcopy(self.result)
            mutate(result)
            with self.assertRaises(ValueError):
                B.assemble(self.document(), [result], self.refs, B.digest(self.raw), self.gemmi)

    def test_controls_do_not_count_toward_proposal_groups(self):
        doc = self.document()
        doc["recipes"][0]["role"] = "exploratory_control"
        _, manifest = B.assemble(doc, [self.result], self.refs, B.digest(self.raw), self.gemmi)
        self.assertEqual(manifest["counts"]["proposal_composition_groups_excluding_baselines"], 0)
        self.assertEqual(manifest["counts"]["roles"], {"exploratory_control": 1})

    def test_same_coordinate_state_is_not_counted_twice_under_new_recipe_name(self):
        second = copy.deepcopy(self.recipe)
        second["id"] = "renamed-duplicate"
        result = copy.deepcopy(self.result)
        result["recipe_id"] = second["id"]
        with self.assertRaisesRegex(ValueError, "Duplicate exact"):
            B.assemble(self.document([self.recipe, second]), [self.result, result], self.refs, B.digest(self.raw), self.gemmi)

    @unittest.skipUnless(os.environ.get("SCLIB_FRONTEND_RUNTIME"), "Actual TS replay uses an existing trusted runtime")
    def test_private_harness_replays_actual_source_without_frontend_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            generated = B.run_generators([self.recipe], Path(os.environ["SCLIB_FRONTEND_RUNTIME"]), Path(folder))
        artifacts, manifest = B.assemble(self.document(), generated, self.refs, B.digest(self.raw), self.gemmi)
        self.assertEqual(len(manifest["inputs"]), 1)
        self.assertIn(self.result["batch"]["candidates"][0]["cif"].encode(), artifacts.values())


if __name__ == "__main__":
    unittest.main()
