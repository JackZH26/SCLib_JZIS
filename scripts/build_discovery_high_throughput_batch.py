"""Build bounded, source-pinned research proposals and CHGNet structure inputs.

This offline adapter invokes the existing TypeScript coordinate generators in a
private temporary Vitest harness. It never computes energies, promotes proposals,
installs dependencies, or writes frontend/public assets. Use Python with the
already available Gemmi runtime; every output CIF is independently parsed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("catalogue", ROOT / "scripts/build_discovery_research_catalogue.py")
catalogue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalogue)
require, digest, pretty, identity = catalogue.require, catalogue.digest, catalogue.pretty, catalogue.identity
SNAPSHOT = ROOT / "frontend/public/research-pilots/discovery-structure-coordinates-2026-10-05.json"
ROLES = {"proposal", "baseline_control", "exploratory_control", "ordering_variant", "strain_control"}
STRATEGIES = {"high_bandwidth", "high_carrier_density", "geometry_construction"}
RECIPE_KEYS = {"id", "reference_id", "source_cif_sha256", "repeats", "role", "route_id", "strategy",
               "edits", "strain_percent", "rationale", "evidence"}
MAX_STATES = 200
GENERATOR_FILES = ["frontend/lib/discovery-site-candidates.ts", "frontend/lib/discovery-combined-candidates.ts",
                   "frontend/lib/discovery-structures.ts", "scripts/build_discovery_research_catalogue.py"]

# The harness lives outside both source trees; imports resolve only into this checkout.
HARNESS = r'''
import fs from "node:fs";
import { webcrypto } from "node:crypto";
import { generateCombinedCandidates } from "@/lib/discovery-combined-candidates";
import { supercellModel, coordinateSha256, SITE_CANDIDATE_VERSION } from "@/lib/discovery-site-candidates";
Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
test("replay explicit bounded recipes through retained coordinate generators", async () => {
  const recipes = JSON.parse(fs.readFileSync(process.env.SCLIB_HT_REQUEST!, "utf8"));
  const results = [];
  for (const recipe of recipes) {
    if (recipe.role === "baseline_control") {
      const model = supercellModel(recipe.reference_id, recipe.repeats);
      const payload = { version: SITE_CANDIDATE_VERSION, source_sha256: model.reference.source.file_sha256,
        repeats: model.repeats, cell: model.cell, atoms: model.atoms };
      results.push({ recipe_id: recipe.id, baseline: model, parent_payload_json: JSON.stringify(payload), parent_id: `supercell:${await coordinateSha256(JSON.stringify(payload))}` });
    } else {
      const sites = recipe.edits.length ? recipe.edits.map(edit => ({ targetId: edit.target_id,
        replacements: edit.kind === "substitution" ? edit.element : "", vacancy: edit.kind === "vacancy", unchanged: false }))
        : [{ targetId: supercellModel(recipe.reference_id, recipe.repeats).atoms[0].id, replacements: "", vacancy: false, unchanged: true }];
      const batch = await generateCombinedCandidates({ referenceId: recipe.reference_id, repeats: recipe.repeats,
        sites, strain: String(recipe.strain_percent) });
      if (batch.candidates.length !== 1) throw new Error("Every explicit recipe must produce exactly one state");
      const payload = { version: SITE_CANDIDATE_VERSION, source_sha256: batch.source_reference.source.file_sha256,
        repeats: batch.baseline.repeats, cell: batch.baseline.cell, atoms: batch.baseline.atoms };
      results.push({ recipe_id: recipe.id, parent_payload_json: JSON.stringify(payload), batch });
    }
  }
  fs.writeFileSync(process.env.SCLIB_HT_GENERATED!, JSON.stringify(results) + "\n", { mode: 0o600 });
}, 120000);
'''


def closed(value, keys, label):
    require(isinstance(value, dict) and set(value) == set(keys), label + " fields")


def safe_id(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", value)


def read_snapshot():
    raw = SNAPSHOT.read_bytes()
    declared = re.search(r'structureCoordinatesSha256 = "([0-9a-f]{64})"',
                         (ROOT / "frontend/lib/discovery-structures.ts").read_text())
    require(declared and digest(raw) == declared[1], "Trusted source snapshot pin mismatch")
    return raw, {item["id"]: item for item in json.loads(raw)["references"]}


def ordered_reference(ref):
    for site in ref["sites"]:
        occ = site["occupancy"]
        require(occ["value"] == 1 and ((occ["raw"] is None and occ.get("basis") == "cif_dictionary_default")
                or isinstance(occ["raw"], str) and re.fullmatch(r"1(?:\.0*)?", occ["raw"])), "Ordered source occupancy required")
    require(not ref.get("host_context", {}).get("coincident_site_pairs"), "Coincident source sites")


def parent_model(ref, repeats):
    """Independent replay of the existing translation order, without idealization."""
    ordered_reference(ref)
    atoms = []
    for i in range(repeats[0]):
        for j in range(repeats[1]):
            for k in range(repeats[2]):
                for index, site in enumerate(ref["display_unit_cell_sites"]):
                    atoms.append({"id": f"image-{index}-cell-{i}-{j}-{k}", "label": f"S{len(atoms)+1}",
                        "element": site["element"], "fractional": [catalogue.number((f+t)/n)
                            for f, t, n in zip(site["fractional"], [i,j,k], repeats)],
                        "occupancy": 1, "source_site_label": site["source_site_label"]})
    require(0 < len(atoms) <= 96, "Supercell atom bound")
    cell = {key: catalogue.number(ref["lattice"][key]["value"] * (repeats[n] if n < 3 else 1))
            for n, key in enumerate(catalogue.CELL_KEYS)}
    return {"repeats": repeats, "cell": cell, "atoms": atoms}


def validate_recipes(document, references, snapshot_sha):
    closed(document, {"schema_version", "version", "source_snapshot_sha256", "recipes"}, "Recipe document")
    require(document["schema_version"] == "discovery-high-throughput-recipes/1.0.0", "Recipe schema")
    require(safe_id(document["version"]), "Recipe version")
    require(document["source_snapshot_sha256"] == snapshot_sha, "Recipe snapshot pin")
    recipes = document["recipes"]
    require(isinstance(recipes, list) and 0 < len(recipes) <= MAX_STATES, "Recipe count bound")
    ids = set()
    for recipe in recipes:
        closed(recipe, RECIPE_KEYS, "Recipe")
        require(safe_id(recipe["id"]) and recipe["id"] not in ids, "Duplicate or unsafe recipe ID")
        ids.add(recipe["id"])
        require(recipe["reference_id"] in references, "Uncaptured source")
        ref = references[recipe["reference_id"]]
        require(recipe["source_cif_sha256"] == ref["source"]["file_sha256"], "Recipe source CIF pin")
        repeats = recipe["repeats"]
        require(isinstance(repeats, list) and len(repeats) == 3 and all(type(x) is int and 1 <= x <= 4 for x in repeats), "Repeat bounds")
        model = parent_model(ref, repeats)
        atoms = {a["id"]: a for a in model["atoms"]}
        require(recipe["role"] in ROLES and recipe["strategy"] in STRATEGIES and safe_id(recipe["route_id"]), "Role/strategy/route")
        require(isinstance(recipe["rationale"], str) and 20 <= len(recipe["rationale"]) <= 2000, "Explicit rationale required")
        require(isinstance(recipe["evidence"], list) and 1 <= len(recipe["evidence"]) <= 8, "Evidence scope required")
        for evidence in recipe["evidence"]:
            closed(evidence, {"url", "scope"}, "Evidence")
            require(isinstance(evidence["url"], str) and re.fullmatch(r"https://[^\s]{1,500}", evidence["url"]), "Evidence URL")
            require(isinstance(evidence["scope"], str) and 10 <= len(evidence["scope"]) <= 1000, "Evidence scope")
        edits = recipe["edits"]
        require(isinstance(edits, list) and len(edits) <= 3, "At most three explicit edits")
        targets = set()
        for edit in edits:
            closed(edit, {"target_id", "kind", "element"}, "Edit")
            require(edit["target_id"] in atoms and edit["target_id"] not in targets, "Invalid or duplicate target")
            targets.add(edit["target_id"])
            require(edit["kind"] in {"vacancy", "substitution"}, "Edit kind")
            require(edit["element"] is None if edit["kind"] == "vacancy" else edit["element"] in catalogue.ELEMENTS
                    and edit["element"] != atoms[edit["target_id"]]["element"], "Edit element")
        strain = recipe["strain_percent"]
        require(type(strain) in {int, float} and math.isfinite(strain) and abs(strain) <= 10
                and Decimal(str(strain))*1000000 == (Decimal(str(strain))*1000000).to_integral_value(), "Strain grid")
        if recipe["role"] == "baseline_control":
            require(not edits and strain == 0, "Baseline must be unchanged")
        elif recipe["role"] == "strain_control":
            require(not edits and strain != 0, "Strain control must only change lattice")
        else:
            require(edits and strain == 0, "Site recipes use zero strain; strain controls are separate")
    return recipes


def run_generators(recipes, runtime, temporary):
    runtime = runtime.resolve()
    executable = runtime / "node_modules/.bin/vitest"
    require(executable.is_file(), "Existing trusted Vitest runtime not found; no dependency installation is performed")
    request, generated = temporary / "request.json", temporary / "generated.json"
    request.write_bytes(pretty(recipes))
    test = temporary / "replay.test.ts"
    test.write_text(HARNESS)
    config = temporary / "vitest.config.mjs"
    config.write_text("export default " + json.dumps({"root": str(temporary), "resolve": {"alias": {"@": str(ROOT / "frontend")}},
        "test": {"globals": True, "environment": "node", "include": [str(test)], "fileParallelism": False}}) + ";\n")
    env = {**os.environ, "SCLIB_HT_REQUEST": str(request), "SCLIB_HT_GENERATED": str(generated)}
    result = subprocess.run([str(executable), "run", "--config", str(config)], cwd=temporary, env=env,
                            capture_output=True, text=True, timeout=180)
    require(result.returncode == 0, "Existing generator replay failed:\n" + result.stdout[-5000:] + result.stderr[-5000:])
    raw = generated.read_bytes()
    require(len(raw) <= 40*1024*1024, "Generated batch size bound")
    return json.loads(raw)


def baseline_cif(model, source):
    # A control export, never attributed to the changed-state generator.
    def num(x):
        return catalogue.canonical(catalogue.number(x))
    return "\n".join(["data_sclib_high_throughput_baseline", "# Unrelaxed source-derived baseline control; no physical calculation.",
        "# Source: " + source["cif_url"], "# Source CIF SHA-256: " + source["cif_sha256"],
        *["_cell_" + ("length_" if len(k) == 1 else "angle_") + k + " " + num(model["cell"][k]) for k in catalogue.CELL_KEYS],
        "_symmetry_space_group_name_H-M 'P 1'", "_symmetry_Int_Tables_number 1", "loop_", "_symmetry_equiv_pos_as_xyz", "'x,y,z'",
        "loop_", "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
        *[" ".join([a["label"], a["element"], *[num(x) for x in a["fractional"]], "1"]) for a in model["atoms"]], ""])


def verify_replay(recipe, result, ref, gemmi):
    require(result["recipe_id"] == recipe["id"], "Replay recipe order/identity")
    source = catalogue.source_record(ref)
    parent = parent_model(ref, recipe["repeats"])
    if recipe["role"] == "baseline_control":
        raw_parent = result["baseline"]
        require(raw_parent["reference"] == ref, "Baseline source drift")
        legacy_parent, legacy_candidate = result["parent_id"], None
        atoms, state_cell, edits = parent["atoms"], parent["cell"], []
        cif = baseline_cif(parent, source)
    else:
        batch = result["batch"]
        require(batch["source_reference"] == ref, "Generator source drift")
        require(batch["version"] == "discovery-combined-site-candidates/1.0.0" and len(batch["candidates"]) == 1, "Generator contract")
        require(all(batch["boundary"].get(k) is None for k in catalogue.CONDITIONS), "Unexpected physical conditions")
        require(all(batch["boundary"][k] is False for k in ["relaxed", "energy_calculated", "stability_validated", "tc_calculated", "scientific_acceptance", "ml_training_approved", "database_write"]), "Unexpected scientific promotion")
        raw_parent, candidate = batch["baseline"], batch["candidates"][0]
        expected_sites = [{"targetId": e["target_id"], "replacements": e["element"] if e["kind"] == "substitution" else "",
                           "vacancy": e["kind"] == "vacancy", "unchanged": False} for e in recipe["edits"]]
        if not expected_sites:
            expected_sites = [{"targetId": parent["atoms"][0]["id"], "replacements": "", "vacancy": False, "unchanged": True}]
        require(batch["requested"] == {"referenceId": recipe["reference_id"], "repeats": recipe["repeats"],
                "sites": expected_sites, "strain": catalogue.canonical(recipe["strain_percent"])}, "Generator request differs from recipe")
        legacy_parent, legacy_candidate = batch["parent_id"], candidate["id"]
        supplied = [{"target_id": e["target"]["id"], "kind": e["operation"]["kind"], "element": e["operation"]["element"]} for e in candidate["edits"]]
        require(sorted(supplied, key=lambda e:e["target_id"]) == sorted(recipe["edits"], key=lambda e:e["target_id"]), "Generator edits differ from recipe")
        original = {a["id"]: a for a in parent["atoms"]}
        for edit in candidate["edits"]:
            require(edit["target"]["occupancy"] == 1 and catalogue.atom(edit["target"]) == original[edit["target"]["id"]], "Generator target differs from source")
        changes = {e["target_id"]: e for e in recipe["edits"]}
        atoms = [{**a, "element": changes[a["id"]]["element"] if a["id"] in changes else a["element"]}
                 for a in parent["atoms"] if a["id"] not in changes or changes[a["id"]]["kind"] != "vacancy"]
        require(atoms and all(a["occupancy"] == 1 for a in candidate["atoms"])
                and atoms == [catalogue.atom(a) for a in candidate["atoms"]], "Generated coordinates or species drift")
        require(candidate["strain_percent"] == recipe["strain_percent"], "Generated strain differs from recipe")
        factor = 1 + recipe["strain_percent"] / 100
        state_cell = {key: catalogue.number(raw_parent["cell"][key] * (factor if len(key) == 1 else 1)) for key in catalogue.CELL_KEYS}
        require(catalogue.cell(candidate["cell"]) == state_cell, "Generated cell drift")
        require(candidate["composition"] == catalogue.composition(atoms), "Generated composition drift")
        cif = candidate["cif"]
        require(digest(cif) == candidate["cif_sha256"] and candidate["parent_id"] == legacy_parent, "Generated CIF/parent pin")
        legacy_body = {"version": batch["version"], "parent_id": legacy_parent, "cif_sha256": digest(cif)}
        require(legacy_candidate == "combined-candidate:" + digest(json.dumps(legacy_body, separators=(",", ":"))), "Original candidate ID mismatch")
        edits = [{**e, "original_element": original[e["target_id"]]["element"],
                  "source_site_label": original[e["target_id"]]["source_site_label"]} for e in recipe["edits"]]
    require(all(a["occupancy"] == 1 for a in raw_parent["atoms"]), "Generated parent occupancy drift")
    require(raw_parent["repeats"] == parent["repeats"] and catalogue.cell(raw_parent["cell"]) == parent["cell"]
            and [catalogue.atom(a) for a in raw_parent["atoms"]] == parent["atoms"], "Source supercell replay mismatch")
    expected_payload = {"version": "discovery-site-candidates/1.0.0", "source_sha256": source["cif_sha256"],
                        "repeats": raw_parent["repeats"], "cell": raw_parent["cell"], "atoms": raw_parent["atoms"]}
    require(json.loads(result["parent_payload_json"]) == expected_payload and
            legacy_parent == "supercell:" + digest(result["parent_payload_json"]), "Legacy parent ID/payload mismatch")
    catalogue.verify_cif(cif, state_cell, atoms, source, gemmi)
    parent_id = identity("ht-parent", {"source_id": source["id"], **parent})
    # IDs describe source-bound models, not symmetry equivalence or formal SQL identities.
    state_id = identity("ht-state", {"parent_id": parent_id, "cell": state_cell, "atoms": atoms, "conditions": catalogue.CONDITIONS})
    counts = catalogue.composition(atoms)
    gcd = math.gcd(*counts.values())
    reduced = {e: n//gcd for e,n in counts.items()}
    group_id = identity("ht-composition", reduced)
    parsed_cell = gemmi.UnitCell(*[state_cell[k] for k in catalogue.CELL_KEYS])
    lattice = [list(parsed_cell.orthogonalize(gemmi.Fractional(*row))) for row in [[1,0,0],[0,1,0],[0,0,1]]]
    require(all(math.isfinite(x) for row in lattice for x in row) and parsed_cell.volume > 0, "Invalid lattice conversion")
    changed_species = Counter(e["original_element"] for e in edits)
    nominal = [{"element": e, "changed_sites": n, "original_species_sites": sum(a["element"] == e for a in parent["atoms"]),
                "fraction": n/sum(a["element"] == e for a in parent["atoms"])} for e,n in sorted(changed_species.items())]
    state = {"id": state_id, "composition_group_id": group_id, "recipe_id": recipe["id"], "role": recipe["role"],
        "strategy": recipe["strategy"], "route_id": recipe["route_id"], "formula": catalogue.formula(counts, ref["formula"], edits),
        "composition": counts, "reduced_composition": reduced, "source_id": source["id"], "parent_id": parent_id,
        "legacy_parent_id": legacy_parent, "legacy_candidate_id": legacy_candidate, "host_formula": ref["formula"],
        "reference_id": ref["id"], "repeats": recipe["repeats"], "edits": edits, "strain_percent": recipe["strain_percent"],
        "nominal_changed_site_fractions": nominal, "nominal_fraction_basis": "Explicit original species site counts; not measured composition or carrier density.",
        "cell": state_cell, "atoms": atoms, "conditions": dict(catalogue.CONDITIONS), "status": "unrelaxed",
        "rationale": recipe["rationale"], "evidence": recipe["evidence"], "score": None, "rank": None,
        "high_potential": None, "novelty": "unassessed", "human_scientific_review": None,
        "formal_scientific_release": False, "rps_release": False,
        "physical_axes": {k: {"status": "unknown", "value": None} for k in catalogue.AXES},
        "next_calculation": {"kind": "chgnet_single_point_prefilter", "status": "input_prepared_not_executed",
            "scope": "Pretrained model energetics/force prefilter after state and method review; not DFT, Tc, carrier density, hull or stability certification."},
        "cif_sha256": digest(cif)}
    compute = {"schema_version": "discovery-chgnet-structure-input/1.0.0", "state_id": state_id,
        "role": recipe["role"], "parent_id": parent_id, "source_id": source["id"], "source_sha256": source["cif_sha256"],
        "structure_sha256": digest(cif), "conditions": dict(catalogue.CONDITIONS), "lattice_matrix_angstrom": lattice,
        "species": [a["element"] for a in atoms], "fractional_coordinates": [a["fractional"] for a in atoms],
        "occupancy": [1 for _ in atoms], "composition": counts, "periodic": True, "cell": state_cell,
        "original_atom_ids": [a["id"] for a in atoms]}
    return state, compute, cif, source, {"id": parent_id, "source_id": source["id"], "reference_id": ref["id"], **parent}


def assemble(document, generated, references, snapshot_sha, gemmi):
    recipes = validate_recipes(document, references, snapshot_sha)
    require(len(generated) == len(recipes), "Replay output length")
    states, sources, parents, artifacts, inputs = [], {}, {}, {}, []
    seen = set()
    for recipe, result in zip(recipes, generated):
        state, compute, cif, source, parent = verify_replay(recipe, result, references[recipe["reference_id"]], gemmi)
        require(state["id"] not in seen, "Duplicate exact source-bound coordinate state; keep aliases in the recipe review instead")
        seen.add(state["id"])
        sources[source["id"]], parents[parent["id"]] = source, parent
        compute["source_snapshot_sha256"] = snapshot_sha
        cif_path, input_path = f"cif/{recipe['id']}.cif", f"atom-inputs/{recipe['id']}.json"
        artifacts[cif_path], artifacts[input_path] = cif.encode(), pretty(compute)
        state.update(cif_path=cif_path, atom_input_path=input_path, atom_input_sha256=digest(artifacts[input_path]))
        inputs.append({"state_id": state["id"], "recipe_id": recipe["id"], "role": state["role"], "path": input_path,
                       "sha256": digest(artifacts[input_path]), "bytes": len(artifacts[input_path]),
                       "cif": {"path": cif_path, "bytes": len(artifacts[cif_path]), "sha256": digest(cif)}})
        states.append(state)
    groups = {}
    for state in states:
        group = groups.setdefault(state["composition_group_id"], {"id": state["composition_group_id"],
             "reduced_composition": state["reduced_composition"], "state_ids": [], "roles": []})
        group["state_ids"].append(state["id"])
        group["roles"] = sorted(set(group["roles"] + [state["role"]]))
    artifacts["sources.json"] = pretty(list(sources.values()))
    artifacts["parents.json"] = pretty(list(parents.values()))
    artifacts["composition-groups.json"] = pretty(list(groups.values()))
    for index in range(0, len(states), 32):
        artifacts[f"states/part-{index//32+1:03d}.json"] = pretty(states[index:index+32])
    artifacts["recipes.json"] = pretty(document)
    for index in range(0, len(generated), 32):
        artifacts[f"generator-replay/part-{index//32+1:03d}.json"] = pretty(generated[index:index+32])
    proposal_groups = {s["composition_group_id"] for s in states if s["role"] == "proposal"}
    baseline_groups = {s["composition_group_id"] for s in states if s["role"] == "baseline_control"}
    manifest = {"schema_version": "discovery-high-throughput-batch/1.0.0", "version": document["version"],
        "source_snapshot_sha256": snapshot_sha, "recipe_sha256": digest(artifacts["recipes.json"]),
        "builder_sha256": digest(Path(__file__).read_bytes()), "harness_sha256": digest(HARNESS),
        "generator_sources": [{"path": p, "sha256": digest((ROOT/p).read_bytes())} for p in GENERATOR_FILES],
        "validation": {"independent_parser": "Gemmi", "parser_version": gemmi.__version__, "full_coordinate_replay": True,
             "coordinate_precision": "Existing generator CIF decimal serialization, 14 significant digits; source model remains retained.",
             "lattice_convention": "Rows are a,b,c Cartesian vectors; a along x, b in xy, right-handed; Gemmi conversion.",
             "deduplication": "Global reduced composition groups; exact source-bound model states; symmetry-equivalent models are not claimed distinct discoveries."},
        "counts": {"sources": len(sources), "parents": len(parents), "states": len(states), "composition_groups": len(groups),
            "roles": dict(sorted(Counter(s["role"] for s in states).items())),
            "proposal_composition_groups_excluding_baselines": len(proposal_groups - baseline_groups),
            "scientifically_qualified_high_potential_groups": 0, "confirmed_novel_groups": 0},
        "authority": {"execution_performed": False, "scientific_approval": False, "formal_scientific_release": False,
             "rps_release": False, "high_potential": None, "scores": None,
             "scope": "Source-qualified coordinate hypotheses and controls. Generation counts do not establish potential or novelty."},
        "inputs": inputs, "artifacts": [{"path": p, "sha256": digest(data), "bytes": len(data)} for p,data in sorted(artifacts.items())]}
    artifacts["batch-manifest.json"] = pretty(manifest)
    artifacts["SHA256SUMS"] = "".join(f"{digest(data)}  {p}\n" for p,data in sorted(artifacts.items())).encode()
    return artifacts, manifest


def write_new(output, artifacts):
    require(not output.exists(), "Output must be a new immutable directory")
    output.mkdir(mode=0o700, parents=False)
    for name, raw in artifacts.items():
        path = output / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend-runtime", type=Path, required=True, help="Existing frontend with trusted node_modules; read only")
    parser.add_argument("--gemmi-runtime", type=Path, required=True, help="Existing Gemmi package directory compatible with this Python")
    args = parser.parse_args()
    os.umask(0o077)
    require(not args.output.exists(), "Output exists; refusing overwrite")
    sys.path.insert(0, str(args.gemmi_runtime.resolve()))
    import gemmi
    raw = args.recipes.read_bytes()
    require(len(raw) <= 2*1024*1024, "Recipe file size bound")
    document = json.loads(raw)
    snapshot, references = read_snapshot()
    recipes = validate_recipes(document, references, digest(snapshot))
    with tempfile.TemporaryDirectory(prefix="sclib-ht-replay-") as temp:
        generated = run_generators(recipes, args.frontend_runtime, Path(temp))
    artifacts, manifest = assemble(document, generated, references, digest(snapshot), gemmi)
    write_new(args.output, artifacts)
    print(json.dumps({"manifest_sha256": digest(artifacts["batch-manifest.json"]), "counts": manifest["counts"]}, indent=2))


if __name__ == "__main__":
    main()
