"""Replay the reviewed JARVIS expansion into a private, immutable research bundle.

No download, database, model execution, promotion or frontend write. Gemmi is
mandatory; optional Pymatgen adds another independent CIF check. The trusted
planning manifest is a closed, reviewed source snapshot, not a recipe API.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLAN_MANIFEST_SHA = "255ee173551993c1725c69a5edcd087dd17242e0a04ee730abb66915e713d93a"
PLAN_SHA = "be131c9cda03ff1ea8f3f5dd31758f97d43ba28231fa1e8d4211fef76ad2a085"
IDENTITY_SHA = "b78d22a8f1bdfe397a5b48cf8bf7e168286cd34f4048fa726a22ae6b8db1e5c5"
ARCHIVE_SHA = "4213651cee9b4c13a376dd74ac1f8d3bd9efcd451f1b8da615255c8df0e1487f"
MEMBER_SHA = "77e7c22c82f5fe7d8ea6c5b43ab4ac17b3d414620dffe22f37f0dca3ccaeaa0a"
MEMBER = "jarvis_epc_data_figshare_1058.json"
VERSION = "2026-10-06-jarvis-reviewed33-coordinate-proposals-v1"
CONDITIONS = dict.fromkeys(["pressure_gpa", "temperature_k", "charge_state", "magnetic_state"])
AXES = ["stability", "electronic", "pairing", "coherence", "geometry", "competing_order"]
HASH = re.compile(r"[a-f0-9]{64}\Z")
MAX_MEMBER = 128 * 1024 * 1024
GENERATOR_SOURCE_PINS = {
    "scripts/build_discovery_research_catalogue.py": "3c6e242993bedcc3b2261bddfeb2c4e93e5f2fa75c2eb7ec975374ee78469d0a",
    "scripts/run_discovery_chgnet_batch.py": "93007282b1b2eece5f2b5573bf9b5e0980b4c2d1ae93579abdbe41bfc47d0cf3",
}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pretty(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()


def pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, "duplicate_json_key")
        value[key] = item
    return value


def decode(raw):
    def invalid(_):
        raise ValueError("nonfinite_json")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def read_file(path, expected=None, maximum=MAX_MEMBER):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum, "file_type_or_size")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    def fields(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    require(fields(before) == fields(after) and len(raw) == before.st_size, "file_changed")
    require(expected is None or HASH.fullmatch(expected) and digest(raw) == expected, "file_hash")
    return raw


def module(name, path, expected):
    # Compile the exact bytes read from one bounded O_NOFOLLOW regular-file fd,
    # after the before/after stat and fixed hash checks. No importlib path reopen.
    raw = read_file(path, expected, maximum=1024 * 1024)
    result = types.ModuleType(name)
    result.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), result.__dict__)
    return result, raw


# These fixed pins are the original frozen batch's generator_sources. The
# reader in turn verifies its lifecycle helper; no execution API is invoked.
C_PATH, R_PATH = GENERATOR_SOURCE_PINS
C, C_BYTES = module("jarvis_serialization", ROOT / C_PATH, GENERATOR_SOURCE_PINS[C_PATH])
R, R_BYTES = module("jarvis_input_contract", ROOT / R_PATH, GENERATOR_SOURCE_PINS[R_PATH])
GENERATOR_SOURCE_BYTES = {C_PATH: C_BYTES, R_PATH: R_BYTES}


def composition_key(counts):
    require(type(counts) is dict and counts and all(e in C.ELEMENTS and type(n) is int and n > 0
                                                  for e, n in counts.items()), "composition_counts")
    total = sum(counts.values())
    return tuple(sorted((e, str(Fraction(n, total))) for e, n in counts.items()))


def periodic_close(a, b, tolerance=1e-10):
    return all(abs((x - y + .5) % 1 - .5) <= tolerance for x, y in zip(a, b))


def matrix(value, n=3):
    return type(value) is list and len(value) == n and all(type(row) is list and len(row) == 3
        and all(type(x) in (int, float) and math.isfinite(x) for x in row) for row in value)


def determinant(m):
    return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
            - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
            + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))


def inverse(m):
    d = determinant(m)
    require(d > 1e-8, "source_lattice_handedness_or_volume")
    result = []
    for i in range(3):
        row = []
        for j in range(3):
            minor = [[m[r][c] for c in range(3) if c != i] for r in range(3) if r != j]
            row.append((-1)**(i+j) * (minor[0][0]*minor[1][1]-minor[0][1]*minor[1][0]) / d)
        result.append(row)
    return result


def row_times_matrix(row, m):
    return [sum(row[k]*m[k][j] for k in range(3)) for j in range(3)]


def cell_from_matrix(lattice):
    lengths = [math.sqrt(sum(x*x for x in row)) for row in lattice]
    angles = [math.degrees(math.acos(max(-1, min(1, sum(a*b for a, b in zip(lattice[i], lattice[j]))
        / (lengths[i]*lengths[j]))))) for i, j in [(1, 2), (0, 2), (0, 1)]]
    return dict(zip(C.CELL_KEYS, lengths + angles))


def validate_atoms(value):
    require(type(value) is dict and set(value) == {"lattice_mat", "coords", "elements", "abc", "angles", "cartesian", "props"}, "source_atom_fields")
    lattice, positions, species = value["lattice_mat"], value["coords"], value["elements"]
    require(type(species) is list and 1 <= len(species) <= 12 and all(e in C.ELEMENTS for e in species), "source_species")
    require(matrix(lattice) and matrix(positions, len(species)) and value["cartesian"] is True, "source_matrix_or_cartesian_flag")
    require(value["props"] == [""] * len(species), "source_disorder_or_unsupported_site_properties")
    inv = inverse(lattice)
    fractions = [row_times_matrix(x, inv) for x in positions]
    for xyz, frac in zip(positions, fractions):
        require(all(abs(a-b) < 1e-9 for a, b in zip(xyz, row_times_matrix(frac, lattice))), "cartesian_fractional_roundtrip")
    for i, frac in enumerate(fractions):
        require(not any(periodic_close(frac, other) for other in fractions[:i]), "duplicate_source_coordinates")
    cell = cell_from_matrix(lattice)
    for reported, keys in [(value["abc"], C.CELL_KEYS[:3]), (value["angles"], C.CELL_KEYS[3:])]:
        require(type(reported) is list and len(reported) == 3 and all(type(x) in (int, float) and math.isfinite(x)
                and math.isclose(x, cell[k], rel_tol=1e-5, abs_tol=1e-4) for x, k in zip(reported, keys)), "source_reported_cell_mismatch")
    return fractions


def load_sources(planning, archive):
    manifest_raw = read_file(planning / "manifest.final.json", PLAN_MANIFEST_SHA, 64*1024)
    manifest = decode(manifest_raw)
    files = {}
    for entry in manifest["files"]:
        name = entry["path"]
        require(type(name) is str and not name.startswith("/") and all(p not in ("", ".", "..") for p in name.split("/"))
                and "\\" not in name and name not in files, "planning_manifest_path")
        files[name] = entry
    require(files["expansion-plan.reviewed.json"]["sha256"] == PLAN_SHA and files["identity-results.json"]["sha256"] == IDENTITY_SHA, "reviewed_plan_pin")
    plan_raw = read_file(planning / "expansion-plan.reviewed.json", PLAN_SHA, 1024*1024)
    plan = decode(plan_raw)
    audit_raw = read_file(planning / "identity-results.json", IDENTITY_SHA, 16*1024*1024)
    audit = decode(audit_raw)
    input_raw = read_file(planning / "identity-input.json", audit["input_sha256"], 1024*1024)
    require(files["identity-input.json"]["sha256"] == digest(input_raw), "identity_input_pin")
    original = read_file(archive, ARCHIVE_SHA, 16*1024*1024)
    with zipfile.ZipFile(io.BytesIO(original)) as z:
        require(z.namelist().count(MEMBER) == 1, "archive_member_ambiguous")
        require(0 < z.getinfo(MEMBER).file_size <= MAX_MEMBER, "archive_expanded_size")
        member = z.read(MEMBER)
    require(digest(member) == MEMBER_SHA, "archive_member_hash")
    # This exact author archive has non-standard NaN in some unadopted fields.
    # Retain a marked native token instead of inventing zero. Selected atoms
    # are separately strict-decoded from their raw spans and must be finite.
    records = json.loads(member, object_pairs_hook=pairs,
        parse_constant=lambda token: {"unadopted_source_nonfinite_token": token})
    require(type(records) is list and len(records) == 1058, "source_record_count")
    parents, raw_atoms = {}, {}
    for p in plan["parents"]:
        pointer = p["source_row_pointer"]
        require(re.fullmatch(r"/[0-9]+", pointer) and p["planning_reference_id"] not in parents, "source_pointer")
        index = int(pointer[1:])
        require(0 <= index < len(records) and records[index]["jid"] == p["jid"], "source_row_identity")
        span = p["atoms_raw_byte_span"]
        start, end = span["start_inclusive"], span["end_exclusive"]
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(member), "source_raw_span")
        raw = member[start:end]
        require(digest(raw) == p["atoms_file"]["sha256"] and len(raw) == p["atoms_file"]["bytes"], "source_raw_span_hash")
        name = "parents/" + p["jid"] + ".atoms.source.json"
        require(name in files and files[name]["sha256"] == digest(raw), "source_cut_manifest")
        require(read_file(planning / name, digest(raw), 65536) == raw and decode(raw) == records[index]["atoms"], "source_cut_record_mismatch")
        atoms = decode(raw)
        fractions = validate_atoms(atoms)
        require(dict(Counter(atoms["elements"])) == p["composition"] and len(atoms["elements"]) == p["native_atoms"], "source_parent_composition")
        record = records[index]
        require(all(type(record[k]) in (int, float) and math.isfinite(record[k]) for k in ["Tc", "lamb", "wlog"])
                and record["press"] == p["source_pressure_raw"] and record["stability"] == p["source_stability_raw"], "selected_source_study_fields")
        parents[p["planning_reference_id"]] = {"plan": p, "atoms": atoms, "fractions": fractions, "record": records[index]}
        raw_atoms[name] = raw
    require(len(parents) == 12, "source_parent_count")
    return {"plan": plan, "parents": parents, "records": records, "audit": audit, "audit_input": decode(input_raw),
            "plan_raw": plan_raw, "audit_raw": audit_raw, "manifest_raw": manifest_raw, "raw_atoms": raw_atoms}


def source_edits(idea, parent):
    require(idea["repeats"] == [2, 2, 2] and idea["parent_atoms_sha256"] == parent["plan"]["atoms_file"]["sha256"], "recipe_parent_or_repeats")
    require(idea["planned_conditions"] == {"target_pressure_gpa": None, "temperature_k": None, "charge_state": None, "magnetic_state": None}, "recipe_physical_conditions")
    require(all(idea[k] is None for k in ["score", "high_potential", "candidate_tc_k", "candidate_stability"]), "recipe_physical_claim")
    edits, targets = [], set()
    require(type(idea["edits"]) is list and len(idea["edits"]) == 2, "recipe_edit_count")
    for e in idea["edits"]:
        index, image = e["source_atom_index_zero_based"], e["supercell_image"]
        require(type(index) is int and 0 <= index < len(parent["fractions"]), "source_site_index")
        require(type(image) is list and len(image) == 3 and all(type(x) is int and 0 <= x < 2 for x in image), "source_site_image")
        target = (index, *image)
        require(target not in targets, "overlapping_edits")
        targets.add(target)
        require(e["source_element"] == parent["atoms"]["elements"][index] and e["source_cartesian_angstrom"] == parent["atoms"]["coords"][index], "source_site_drift")
        require(matrix([e["source_fractional_derived"], e["planned_supercell_fractional"]], 2), "source_coordinate_shape")
        require(all(abs(a-b) < 1e-12 for a, b in zip(e["source_fractional_derived"], parent["fractions"][index])), "source_fractional_drift")
        expected = [(f % 1 + t)/2 for f, t in zip(parent["fractions"][index], image)]
        require(periodic_close(e["planned_supercell_fractional"], expected), "planned_site_drift")
        kind, element = e["kind"], e["replacement_element"]
        require(kind in {"substitution", "vacancy"} and (element is None if kind == "vacancy" else element in C.ELEMENTS and element != e["source_element"]), "source_edit_kind_or_element")
        edits.append({"target_id": "jarvis-atom-{}-cell-{}-{}-{}".format(*target), "source_atom_index": index,
                      "image": image, "kind": kind, "element": element, "original_element": e["source_element"]})
    return edits


def parent_model(parent):
    native = parent["atoms"]
    lattice = [[x*2 for x in row] for row in native["lattice_mat"]]
    atoms = []
    for i in range(2):
        for j in range(2):
            for k in range(2):
                for index, (element, frac) in enumerate(zip(native["elements"], parent["fractions"])):
                    # A source coordinate on a periodic boundary may round to 1.
                    # Wrap after expansion, preserving the reviewed image target.
                    xyz = [C.number((f % 1 + t)/2) % 1 for f, t in zip(frac, [i, j, k])]
                    atoms.append({"id": f"jarvis-atom-{index}-cell-{i}-{j}-{k}", "label": f"S{len(atoms)+1}",
                        "element": element, "fractional": xyz, "occupancy": 1, "source_atom_index": index,
                        "source_image": [i, j, k]})
    require(len(atoms) <= 96, "supercell_atom_bound")
    return {"repeats": [2, 2, 2], "lattice_matrix_angstrom": lattice, "cell": cell_from_matrix(lattice), "atoms": atoms}


def edited_model(parent, edits):
    require(len({e["target_id"] for e in edits}) == len(edits), "overlapping_edits")
    changes = {e["target_id"]: e for e in edits}
    original = {a["id"]: a for a in parent["atoms"]}
    for e in edits:
        require(e["target_id"] in original and original[e["target_id"]]["element"] == e["original_element"], "edit_target")
        require(e["kind"] in {"vacancy", "substitution"} and (e["element"] is None if e["kind"] == "vacancy" else e["element"] in C.ELEMENTS and e["element"] != e["original_element"]), "edit_operation")
    result = []
    for a in parent["atoms"]:
        e = changes.get(a["id"])
        if e and e["kind"] == "vacancy":
            continue
        result.append({**a, "element": e["element"] if e else a["element"]})
    require(0 < len(result) <= 96 and all(a["occupancy"] == 1 for a in result), "state_occupancy_or_atom_bound")
    for i, a in enumerate(result):
        require(not any(periodic_close(a["fractional"], b["fractional"]) for b in result[:i]), "duplicate_state_coordinates")
    return result


def reviewed_recipes(loaded):
    plan, parents = loaded["plan"], loaded["parents"]
    audit = {r["id"]: r for r in loaded["audit"]["entries"]}
    require(len(plan["ideas"]) == 36 and len(plan["controls"]) == 72, "reviewed_recipe_count")
    recipes, derived_controls = [], {}
    epc_keys = {composition_key(dict(Counter(r["atoms"]["elements"]))) for r in loaded["records"]}
    prior_keys = {tuple(tuple(pair) for pair in r["exact_rational_composition_key"])
                  for r in audit.values() if r["role"] != "proposal" and r["exact_rational_composition_key"]}
    seen = set()
    for idea in plan["ideas"]:
        parent = parents[idea["parent_planning_reference_id"]]
        model = parent_model(parent)
        edits = source_edits(idea, parent)
        counts = C.composition(edited_model(model, edits))
        key = composition_key(counts)
        require(counts == idea["planned_composition"] and sum(counts.values()) == idea["planned_atoms"], "reviewed_composition_drift")
        require(key not in seen and key not in epc_keys and key not in prior_keys, "global_proposal_composition_duplicate")
        seen.add(key)
        row = audit[idea["idea_id"]]
        require(tuple(tuple(x) for x in row["exact_rational_composition_key"]) == key
                and row["parser_status"] == "exact" and row["frozen_capture_exact_composition_rows"] == 0
                and row["matching_reference_input_ids"] == [] and row["same_composition_input_ids"] == [idea["idea_id"]], "frozen_identity_audit_mismatch")
        eligible = row["same_chemical_system_exact_rows"] == 0
        require(idea["count_toward_additional_candidate_ideas"] is eligible
                and idea["role"] == ("unscored_joint_modification_planning_idea" if eligible else "known_alloy_family_followup_reference"), "classification_drift")
        require(idea["strategy"] in {"high_bandwidth", "high_carrier_density", "geometry_construction"}, "strategy")
        if eligible:
            recipes.append({"id": "jarvis-" + parent["plan"]["jid"].lower() + "-" + idea["strategy"].replace("_", "-"),
                "planning_id": idea["idea_id"], "parent_planning_id": idea["parent_planning_reference_id"],
                "role": "proposal", "strategy": idea["strategy"], "edits": edits, "rationale": idea["question"]})
        for edit in edits:
            single = C.composition(edited_model(model, [edit]))
            control_id = "control-plan:" + digest(json.dumps([idea["parent_planning_reference_id"], single], sort_keys=True).encode())[:24]
            body = {"id": control_id, "parent": idea["parent_planning_reference_id"], "composition": single, "edit": edit}
            require(control_id not in derived_controls or derived_controls[control_id] == body, "control_hash_collision")
            derived_controls[control_id] = body
    require(len(derived_controls) == 72, "single_axis_control_count")
    for declared in plan["controls"]:
        control = derived_controls.pop(declared["id"])
        require(declared["role"] == "single_axis_comparator_not_new_candidate"
                and declared["parent_planning_reference_id"] == control["parent"]
                and declared["composition"] == control["composition"], "control_classification_or_composition_drift")
        recipes.append({"id": "jarvis-control-" + declared["id"].split(":")[1], "planning_id": declared["id"],
            "parent_planning_id": control["parent"], "role": "exploratory_control", "strategy": None,
            "edits": [control["edit"]], "rationale": "Single-axis source-bound comparator; excluded from proposal counts."})
    require(not derived_controls, "control_inventory")
    for parent_id, parent in parents.items():
        recipes.append({"id": "jarvis-" + parent["plan"]["jid"].lower() + "-baseline", "planning_id": parent_id,
            "parent_planning_id": parent_id, "role": "baseline_control", "strategy": None, "edits": [],
            "rationale": "Unchanged source-derived supercell reference; no physical property inheritance."})
    require(len(recipes) == 117 and Counter(r["role"] for r in recipes) == {"proposal": 33, "exploratory_control": 72, "baseline_control": 12}, "role_inventory")
    return recipes


def cif_text(cell, atoms, source):
    return "\n".join(["data_sclib_jarvis_derived", "# Explicit derived P1 coordinate model; not an observed space group.",
        "# Original source: https://doi.org/10.6084/m9.figshare.23681025.v2", "# Source JID: " + source["jid"],
        "# Source atoms JSON SHA-256: " + source["atoms_sha256"], "# Original Cartesian frame is retained in the companion input JSON.",
        *["_cell_" + ("length_" if len(k) == 1 else "angle_") + k + " " + C.canonical(v) for k, v in cell.items()],
        "_symmetry_space_group_name_H-M 'P 1'", "_symmetry_Int_Tables_number 1", "loop_", "_symmetry_equiv_pos_as_xyz", "'x,y,z'",
        "loop_", "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
        *[" ".join([a["label"], a["element"], *[C.canonical(x) for x in a["fractional"]], "1"]) for a in atoms], ""])


def verify_cif(cif, compute, gemmi, pymatgen_parser=None):
    require(gemmi is not None, "gemmi_required")
    block = gemmi.cif.read_string(cif).sole_block()
    require(block.find_value("_symmetry_space_group_name_H-M") in {"'P 1'", "P 1"}
            and block.find_value("_symmetry_Int_Tables_number") == "1", "derived_p1_required")
    parsed = gemmi.make_small_structure_from_block(block)
    require(len(parsed.sites) == len(compute["species"]) and parsed.cell.volume > 0, "gemmi_inventory")
    for got, species, frac in zip(parsed.sites, compute["species"], compute["fractional_coordinates"]):
        require(got.element.name == species and got.occ == 1 and periodic_close(list(got.fract), frac, 1e-11), "gemmi_species_occupancy_coordinates")
    lattice = compute["lattice_matrix_angstrom"]
    metric = [[sum(a*b for a, b in zip(x, y)) for y in lattice] for x in lattice]
    vectors = [list(parsed.cell.orthogonalize(gemmi.Fractional(*x))) for x in [[1, 0, 0], [0, 1, 0], [0, 0, 1]]]
    require(all(math.isclose(metric[i][j], sum(a*b for a, b in zip(vectors[i], vectors[j])), rel_tol=1e-10, abs_tol=1e-9)
                for i in range(3) for j in range(3)), "gemmi_cell_metric")
    if pymatgen_parser is not None:
        parser = pymatgen_parser.from_str(cif, occupancy_tolerance=1, site_tolerance=1e-8, frac_tolerance=0)
        structures = parser.parse_structures(primitive=False, check_occu=True)
        require(len(structures) == 1, "pymatgen_single_structure")
        R.match_cif(compute, structures[0])


def assemble(loaded, gemmi, pymatgen_parser=None):
    recipes = reviewed_recipes(loaded)
    sources, parents, originals = {}, {}, []
    artifacts = dict(loaded["raw_atoms"])
    for key, p in loaded["parents"].items():
        origin = p["plan"]
        source = {"provider": "JARVIS-DFT", "jid": origin["jid"], "record_pointer": origin["source_row_pointer"],
            "archive_sha256": ARCHIVE_SHA, "member": MEMBER, "member_sha256": MEMBER_SHA,
            "atoms_sha256": origin["atoms_file"]["sha256"], "atoms_raw_byte_span": origin["atoms_raw_byte_span"],
            "original_cartesian_flag": True, "host_formula": origin["host_formula"], "license": "CC-BY-4.0",
            "scope": "Exact original atom-array reference. No child physical conditions or source property inheritance."}
        source["id"] = C.identity("jarvis-source", source)
        sources[key] = source
        model = parent_model(p)
        model.update(source_id=source["id"], host_formula=origin["host_formula"])
        model["id"] = C.identity("ht-parent", model)
        parents[key] = model
        originals.append({"source_id": source["id"], "jid": source["jid"], "record_pointer": source["record_pointer"],
            "raw_provider_fields": {k: p["record"][k] for k in ["stability", "press", "Tc", "lamb", "wlog"]},
            "temperature_condition_k": None, "scope": "Original-study computed fields only; not observations or adopted child quantities.",
            "properties_inherited": False})
    snapshot = {"schema_version": "jarvis-epc-original-atom-snapshot/1.0.0", "member_sha256": MEMBER_SHA,
        "sources": list(sources.values()), "original_atoms": {sources[k]["id"]: p["atoms"] for k, p in loaded["parents"].items()},
        "native_nonfinite_boundary": "Unadopted NaN tokens in the pinned author archive are not numerical values; selected raw atom spans and copied source-only study scalar fields are required finite. No zero substitution."}
    snapshot_raw = pretty(snapshot)
    snapshot_sha = digest(snapshot_raw)
    states, inputs, seen = [], [], set()
    for recipe in recipes:
        parent, source = parents[recipe["parent_planning_id"]], sources[recipe["parent_planning_id"]]
        atoms = edited_model(parent, recipe["edits"])
        counts = C.composition(atoms)
        reduced = {e: n//math.gcd(*counts.values()) for e, n in counts.items()}
        state_id = C.identity("ht-state", {"parent_id": parent["id"], "lattice_matrix_angstrom": parent["lattice_matrix_angstrom"],
            "atoms": atoms, "conditions": CONDITIONS})
        require(state_id not in seen, "duplicate_source_bound_state")
        seen.add(state_id)
        cif = cif_text(parent["cell"], atoms, source)
        compute = {"schema_version": "discovery-chgnet-structure-input/1.0.0", "state_id": state_id, "role": recipe["role"],
            "parent_id": parent["id"], "source_id": source["id"], "source_sha256": source["atoms_sha256"],
            "source_snapshot_sha256": snapshot_sha, "structure_sha256": digest(cif.encode()), "conditions": dict(CONDITIONS),
            "lattice_matrix_angstrom": parent["lattice_matrix_angstrom"], "cell": parent["cell"],
            "species": [a["element"] for a in atoms], "fractional_coordinates": [a["fractional"] for a in atoms],
            "occupancy": [1]*len(atoms), "composition": counts, "periodic": True, "original_atom_ids": [a["id"] for a in atoms]}
        R.validate_input(compute)
        verify_cif(cif, compute, gemmi, pymatgen_parser)
        name = recipe["id"]
        input_path, cif_path = f"atom-inputs/{name}.json", f"cif/{name}.cif"
        input_raw = pretty(compute)
        artifacts[input_path], artifacts[cif_path] = input_raw, cif.encode()
        inputs.append({"state_id": state_id, "recipe_id": name, "role": recipe["role"], "path": input_path,
            "bytes": len(input_raw), "sha256": digest(input_raw), "cif": {"path": cif_path, "bytes": len(cif.encode()), "sha256": digest(cif.encode())}})
        states.append({"id": state_id, "composition_group_id": C.identity("ht-composition", reduced), "recipe_id": name,
            "role": recipe["role"], "strategy": recipe["strategy"], "planning_id": recipe["planning_id"],
            "host_formula": source["host_formula"], "formula": C.formula(counts, source["host_formula"], recipe["edits"]),
            "composition": counts, "reduced_composition": reduced, "source_id": source["id"], "parent_id": parent["id"],
            "source_provider": "JARVIS-DFT", "cell": parent["cell"], "lattice_matrix_angstrom": parent["lattice_matrix_angstrom"],
            "atoms": atoms, "edits": recipe["edits"], "conditions": dict(CONDITIONS), "status": "unrelaxed",
            "score": None, "rank": None, "high_potential": None, "novelty": "unassessed", "human_scientific_review": None,
            "formal_scientific_release": False, "rps_release": False, "properties_inherited": False,
            "physical_axes": {axis: {"status": "unknown", "value": None} for axis in AXES}, "rationale": recipe["rationale"],
            "cif_path": cif_path, "cif_sha256": digest(cif.encode()), "atom_input_path": input_path, "atom_input_sha256": digest(input_raw)})
    groups = {}
    for state in states:
        group = groups.setdefault(state["composition_group_id"], {"id": state["composition_group_id"],
            "reduced_composition": state["reduced_composition"], "state_ids": [], "roles": []})
        group["state_ids"].append(state["id"])
        group["roles"] = sorted(set(group["roles"] + [state["role"]]))
    artifacts.update({"sources.json": pretty(list(sources.values())), "source-snapshot.json": snapshot_raw,
        "parents.json": pretty(list(parents.values())), "original-study-index.json": pretty(originals),
        "composition-groups.json": pretty(list(groups.values())), "recipes.json": pretty(recipes),
        "planning-provenance.json": pretty({"planning_manifest_sha256": PLAN_MANIFEST_SHA, "reviewed_plan_sha256": PLAN_SHA,
            "excluded_known_joint_followups": [i["idea_id"] for i in loaded["plan"]["ideas"] if not i["count_toward_additional_candidate_ideas"]]}),
        "frozen-identity-projection.json": pretty({"source_audit_sha256": IDENTITY_SHA,
            "frozen_source_pins": loaded["audit"]["frozen_source_pins"], "code_pins": loaded["audit"]["code_pins"],
            "scope": "Frozen exact-composition retrieval only; no global novelty finding or scientific admission.",
            "proposal_entries": [{k: row[k] for k in ["id", "exact_rational_composition_key", "frozen_capture_exact_composition_rows",
                "same_chemical_system_exact_rows", "same_element_tokens_nonexact_rows", "capture_result"]}
                for row in loaded["audit"]["entries"] if row["role"] == "proposal"]})})
    for i in range(0, len(states), 32):
        artifacts[f"states/part-{i//32+1:03d}.json"] = pretty(states[i:i+32])
    proposals = {s["composition_group_id"] for s in states if s["role"] == "proposal"}
    require(len(proposals) == 33, "proposal_composition_count")
    manifest = {"schema_version": "discovery-high-throughput-batch/1.0.0", "version": VERSION,
        "source_snapshot_sha256": snapshot_sha, "planning_manifest_sha256": PLAN_MANIFEST_SHA, "reviewed_plan_sha256": PLAN_SHA,
        "frozen_identity_audit_sha256": IDENTITY_SHA, "recipe_sha256": digest(artifacts["recipes.json"]),
        "builder_sha256": digest(Path(__file__).read_bytes()),
        "dependency_loading": "fixed_sha256_verified_single_fd_bytes_compiled",
        "generator_sources": [{"path": name, "sha256": digest(raw)} for name, raw in GENERATOR_SOURCE_BYTES.items()],
        "validation": {"independent_parser": "Gemmi", "parser_version": gemmi.__version__, "pymatgen": "checked" if pymatgen_parser else "not_run",
            "full_coordinate_replay": True, "lattice_convention": "Original JARVIS row-vector Cartesian frame retained in input JSON; CIF preserves metric and fractional coordinates in explicit derived P1.",
            "coordinate_precision": "14 significant digits for expanded fractional coordinates; original atom bytes retained unchanged.",
            "deduplication": "33 distinct proposals against old catalogue/batch/reference input and original1058; frozen MDR audit has no exact composition match. No worldwide novelty conclusion."},
        "counts": {"sources": 12, "parents": 12, "states": len(states), "composition_groups": len(groups),
            "roles": dict(Counter(s["role"] for s in states)), "proposal_composition_groups_excluding_baselines": len(proposals),
            "scientifically_qualified_high_potential_groups": 0, "confirmed_novel_groups": 0},
        "authority": {"execution_performed": False, "scientific_approval": False, "formal_scientific_release": False,
            "rps_release": False, "high_potential": None, "scores": None, "properties_inherited": False,
            "scope": "Private coordinate hypotheses, controls and references. No computed child physical properties or scientific admission."},
        "inputs": inputs, "artifacts": [{"path": path, "sha256": digest(raw), "bytes": len(raw)} for path, raw in sorted(artifacts.items())]}
    artifacts["batch-manifest.json"] = pretty(manifest)
    artifacts["SHA256SUMS"] = "".join(f"{digest(raw)}  {path}\n" for path, raw in sorted(artifacts.items())).encode()
    return artifacts, manifest


def write_new(output, artifacts):
    require(not output.exists() and not output.is_symlink(), "output_exists")
    parent = output.parent.resolve(strict=True)
    st = parent.stat()
    require(st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700, "output_parent_must_be_owned_0700")
    require(not (parent == ROOT or ROOT in parent.parents), "private_output_outside_repository_required")
    output.mkdir(mode=0o700)
    for name, raw in artifacts.items():
        require(not name.startswith("/") and all(x not in ("", ".", "..") for x in name.split("/")), "artifact_path")
        path = output / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
            stream.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planning-directory", required=True, type=Path)
    parser.add_argument("--epc-archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gemmi-runtime", type=Path)
    parser.add_argument("--pymatgen-runtime", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    require(not args.output.exists(), "output_exists")
    if args.gemmi_runtime:
        sys.path.insert(0, str(args.gemmi_runtime.resolve(strict=True)))
    import gemmi
    pymatgen_parser = None
    if args.pymatgen_runtime:
        sys.path.insert(0, str(args.pymatgen_runtime.resolve(strict=True)))
        from pymatgen.io.cif import CifParser
        pymatgen_parser = CifParser
    loaded = load_sources(args.planning_directory, args.epc_archive)
    artifacts, manifest = assemble(loaded, gemmi, pymatgen_parser)
    # A second full reconstruction must reproduce byte-for-byte artifacts before
    # this otherwise-new output is sealed. No child native input is executed.
    replay, _ = assemble(loaded, gemmi, pymatgen_parser)
    require(artifacts == replay, "nondeterministic_replay")
    write_new(args.output, artifacts)
    R.load_bundle(args.output, digest(artifacts["batch-manifest.json"]))
    print(json.dumps({"manifest_sha256": digest(artifacts["batch-manifest.json"]), "counts": manifest["counts"],
        "pymatgen": manifest["validation"]["pymatgen"]}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, ImportError, zipfile.BadZipFile):
        print(json.dumps({"error": "jarvis_expansion_rejected", "payload_logged": False}), file=sys.stderr)
        raise SystemExit(2)
