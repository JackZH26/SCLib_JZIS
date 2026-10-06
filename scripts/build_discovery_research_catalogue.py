"""Offline, bounded projection of retained coordinate batches; no scientific scoring.

Run --check to compare exact output bytes; --write explicitly creates a new version.
The source files are original scientific batch bytes, pinned by the input manifest.
Gemmi is optional for reconstruction and required by --require-gemmi acceptance.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "docs/data/discovery-research-catalogue"
OUTPUT_DIR = ROOT / "frontend/lib/discovery-research-catalogues"
DEFAULT_MANIFEST = INPUT_DIR / "2026-10-06-inputs.json"
AXES = ["stability", "electronic", "pairing", "coherence", "geometry", "competing_order"]
CONDITIONS = {key: None for key in ["pressure_gpa", "temperature_k", "charge_state", "magnetic_state"]}
CELL_KEYS = ["a", "b", "c", "alpha", "beta", "gamma"]
NEXT_ACTION = {"kind": "state_method_input_review", "summary": "Review the state, methods and reproducible inputs before relaxation."}
ELEMENTS = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split())


def require(value, message):
    if not value:
        raise ValueError(message)


def normalize(value):
    if isinstance(value, float):
        require(math.isfinite(value), "Non-finite number")
        return int(value) if value.is_integer() else value
    if isinstance(value, list):
        return [normalize(x) for x in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return value


def canonical(value):
    # Plain decimal JSON numbers avoid Python/JavaScript exponent spelling differences.
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical(value[k]) for k in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        require(math.isfinite(value), "Non-finite canonical number")
        text = format(Decimal(str(value)), "f")
        return (text.rstrip("0").rstrip(".") if "." in text else text) if value else "0"
    return json.dumps(value, ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def identity(prefix, value):
    return prefix + ":" + digest(canonical(value))


def pretty(value):
    return (json.dumps(normalize(value), indent=2, ensure_ascii=False) + "\n").encode()


def number(value):
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), "Invalid numeric coordinate")
    return normalize(float(format(value, ".14g")))


def cell(value):
    result = {key: number(value[key]) for key in CELL_KEYS}
    require(all(result[k] > 0 for k in ["a", "b", "c"]), "Nonpositive cell length")
    require(all(0 < result[k] < 180 for k in ["alpha", "beta", "gamma"]), "Invalid cell angle")
    return result


def atom(value):
    return {"id": value["id"], "label": value["label"], "element": value["element"],
            "fractional": [number(x) for x in value["fractional"]], "occupancy": 1,
            "source_site_label": value["source_site_label"]}


def composition(atoms):
    counts = {}
    for site in atoms:
        counts[site["element"]] = counts.get(site["element"], 0) + 1
    return dict(sorted(counts.items()))


def formula(counts, host, edits, reduced=False):
    order = list(dict.fromkeys(re.findall(r"[A-Z][a-z]?", host)))
    for edit in edits:
        element = edit["element"]
        if element and element not in order:
            order.insert(order.index(edit["original_element"]) + 1, element)
    order += sorted(set(counts) - set(order))
    divisor = math.gcd(*counts.values()) if reduced else 1
    return "".join(e + (str(counts[e] // divisor) if counts[e] // divisor != 1 else "") for e in order if e in counts)


def verify_cif(text, expected_cell, atoms, source, gemmi_module=None):
    require(isinstance(text, str) and len(text.encode()) <= 65536 and text.endswith("\n"), "CIF size or termination")
    lines = text.splitlines()
    require("_symmetry_space_group_name_H-M 'P 1'" in lines and "_symmetry_Int_Tables_number 1" in lines, "Expected explicit P1 output")
    require(f"# Source CIF SHA-256: {source['cif_sha256']}" in lines, "CIF source hash mismatch")
    require(f"# Source: {source['cif_url']}" in lines, "CIF source URL mismatch")
    for key in CELL_KEYS:
        tag = "_cell_" + ("length_" if len(key) == 1 else "angle_") + key
        values = [line.split()[1] for line in lines if line.startswith(tag + " ")]
        require(len(values) == 1 and Decimal(values[0]) == Decimal(str(expected_cell[key])), "CIF cell mismatch")
    require(lines.count("_atom_site_occupancy") == 1, "CIF atom loop missing")
    rows = [line.split() for line in lines[lines.index("_atom_site_occupancy") + 1:] if line]
    require(len(rows) == len(atoms), "CIF atom count mismatch")
    for row, expected in zip(rows, atoms):
        require(len(row) == 6 and row[:2] == [expected["label"], expected["element"]] and row[5] == "1", "CIF atom identity mismatch")
        require(all(Decimal(x) == Decimal(str(y)) for x, y in zip(row[2:5], expected["fractional"])), "CIF coordinate mismatch")
    if gemmi_module:
        block = gemmi_module.cif.read_string(text).sole_block()
        parsed = gemmi_module.make_small_structure_from_block(block)
        require(len(parsed.sites) == len(atoms) and parsed.cell.volume > 0, "Gemmi inventory or volume")
        for parsed_site, expected in zip(parsed.sites, atoms):
            require(parsed_site.element.name == expected["element"] and parsed_site.occ == 1, "Gemmi species/occupancy")
            require(all(abs(x-y) < 1e-12 for x, y in zip(parsed_site.fract, expected["fractional"])), "Gemmi coordinates")


def source_record(reference):
    source = reference["source"]
    return {"id": identity("proposal-source", {"cif_sha256": source["file_sha256"], "record_id": reference["id"]}),
            "provider": "COD", "record_id": reference["id"].removeprefix("cod-"), "revision": source["captured_revision"],
            "cif_sha256": source["file_sha256"], "cif_url": source["cif_url"], "entry_url": source["entry_url"],
            "formula": reference["formula"], "phase": reference.get("host_context", {}).get("phase"),
            "license": source["license"], "license_url": source["license_url"], "license_basis": source["license_basis"],
            "capture_kind": "mutable_current_file" if source["download_is_mutable_current_file"] else "revision_url"}


def build(manifest_path=DEFAULT_MANIFEST, gemmi_module=None):
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest["schema_version"] == "research-proposal-build/1.0.0", "Unsupported input manifest")
    require(re.fullmatch(r"[a-z0-9-]{1,100}", manifest["version"]), "Unsafe version")
    require(isinstance(manifest["batches"], list) and 0 < len(manifest["batches"]) <= 100, "Input batch bound")
    snapshot_path = ROOT / manifest["source_snapshot"]["path"]
    require(snapshot_path.resolve().is_relative_to(ROOT / "frontend/public/research-pilots"), "Source snapshot path")
    snapshot_bytes = snapshot_path.read_bytes()
    require(digest(snapshot_bytes) == manifest["source_snapshot"]["sha256"], "Source snapshot changed")
    references = {r["id"]: r for r in json.loads(snapshot_bytes)["references"]}
    sources, parents, states, groups, occurrences = {}, {}, {}, {}, []
    for package in manifest["batches"]:
        path = INPUT_DIR / package["filename"]
        require(path.resolve().is_relative_to(INPUT_DIR), "Batch path outside input directory")
        raw = path.read_bytes()
        require(len(raw) <= 1024 * 1024 and digest(raw) == package["sha256"], "Source batch changed or oversized")
        batch = json.loads(raw)
        require(batch["version"] in ["discovery-site-candidates/1.0.0", "discovery-combined-site-candidates/1.0.0"], "Unsupported generator")
        boundary = batch["boundary"]
        require(all(boundary[k] is False for k in ["relaxed", "energy_calculated", "stability_validated", "tc_calculated", "scientific_acceptance", "ml_training_approved", "database_write"]), "Source is not an unassessed proposal batch")
        require(all(boundary.get(k) is None for k in CONDITIONS), "Defined source conditions need a new adapter")
        reference = batch["source_reference"]
        pinned = references[reference["id"]]
        require(all(reference[key] == pinned[key] for key in ["source", "sites", "display_unit_cell_sites", "lattice", "formula", "declared_symmetry_operations"]), "Source identity/coordinates drift")
        for site in reference["sites"]:
            occ = site["occupancy"]
            require(occ["value"] == 1 and (occ["raw"] is None and occ.get("basis") == "cif_dictionary_default" or isinstance(occ["raw"], str) and re.fullmatch(r"1(?:\.0*)?", occ["raw"])), "Ordered occupancy required")
        require(not reference.get("host_context", {}).get("coincident_site_pairs"), "Coincident source sites")
        source = source_record(reference)
        sources[source["id"]] = source
        baseline = batch["baseline"]
        repeats = baseline["repeats"]
        require(len(repeats) == 3 and all(type(n) is int and 1 <= n <= 4 for n in repeats), "Invalid supercell")
        rebuilt = []
        for i in range(repeats[0]):
            for j in range(repeats[1]):
                for k in range(repeats[2]):
                    for index, site in enumerate(reference["display_unit_cell_sites"]):
                        rebuilt.append({"id": f"image-{index}-cell-{i}-{j}-{k}", "label": f"S{len(rebuilt)+1}", "element": site["element"],
                                        "fractional": [number((f+t)/n) for f, t, n in zip(site["fractional"], [i, j, k], repeats)],
                                        "occupancy": 1, "source_site_label": site["source_site_label"]})
        require(0 < len(rebuilt) <= 96 and rebuilt == [atom(a) for a in baseline["atoms"]], "Parent inventory mismatch")
        parent_cell = {key: number(reference["lattice"][key]["value"] * (repeats[CELL_KEYS.index(key)] if len(key) == 1 else 1)) for key in CELL_KEYS}
        require(cell(baseline["cell"]) == parent_cell, "Parent cell mismatch")
        parent_body = {"source_id": source["id"], "reference_id": reference["id"], "repeats": repeats, "cell": parent_cell, "atoms": rebuilt}
        parent_id = identity("proposal-parent", parent_body)
        parent = {"id": parent_id, **parent_body, "legacy_parent_id": batch["parent_id"]}
        require(parent_id not in parents or parents[parent_id] == parent, "Conflicting legacy parent lineage")
        parents[parent_id] = parent
        require(0 < len(batch["candidates"]) <= 64, "Batch candidate bound")
        for index, candidate in enumerate(batch["candidates"]):
            raw_edits = candidate.get("edits", [{"target": candidate.get("target_atom"), "operation": candidate.get("operation")}])
            edits = []
            for edit in raw_edits:
                original = next((a for a in rebuilt if a["id"] == edit["target"]["id"]), None)
                require(original is not None and atom(edit["target"]) == original, "Edit target mismatch")
                operation = edit["operation"]
                require(operation["kind"] in ["substitution", "vacancy"], "Unknown site edit")
                element = operation["element"]
                require(element is None if operation["kind"] == "vacancy" else isinstance(element, str) and element in ELEMENTS and element != original["element"], "Invalid species edit")
                edits.append({"target_id": original["id"], "source_site_label": original["source_site_label"], "original_element": original["element"], "kind": operation["kind"], "element": element})
            edits.sort(key=lambda e: e["target_id"])
            require(len({e["target_id"] for e in edits}) == len(edits) <= 3, "Conflicting edits")
            strain = Decimal(str(candidate.get("strain_percent", 0))) * 1000000
            require(strain == strain.to_integral_value() and abs(strain) <= 10000000, "Strain micro-percent grid")
            require(edits or strain != 0, "Unchanged reference is not a proposal")
            edit_map = {e["target_id"]: e for e in edits}
            expected_atoms = []
            for original in rebuilt:
                edit = edit_map.get(original["id"])
                if edit and edit["kind"] == "vacancy":
                    continue
                expected_atoms.append({**original, "element": edit["element"] if edit else original["element"]})
            require(expected_atoms and expected_atoms == [atom(a) for a in candidate["atoms"]], "Edited atom inventory mismatch")
            # Apply the generator's operation to original double values, then its 14-digit CIF serialization.
            factor = 1 + float(strain) / 100000000
            expected_cell = {key: number(baseline["cell"][key] * (factor if len(key) == 1 else 1)) for key in CELL_KEYS}
            if "cell" in candidate:
                require(cell(candidate["cell"]) == expected_cell, "Modified cell mismatch")
            counts = composition(expected_atoms)
            require(candidate["composition"] == counts, "Composition mismatch")
            text = candidate["cif"]
            require(digest(text) == candidate["cif_sha256"], "CIF bytes mismatch")
            require(candidate["parent_id"] == batch["parent_id"], "Legacy parent mismatch")
            if batch["version"] == "discovery-site-candidates/1.0.0":
                legacy_body = {"version": batch["version"], "parent_id": batch["parent_id"], "target_atom_id": candidate["target_atom"]["id"],
                               "operation": {"kind": candidate["operation"]["kind"], "element": candidate["operation"]["element"]}, "cif_sha256": candidate["cif_sha256"]}
                legacy_prefix = "site-candidate"
            else:
                legacy_body = {"version": batch["version"], "parent_id": batch["parent_id"], "cif_sha256": candidate["cif_sha256"]}
                legacy_prefix = "combined-candidate"
            # These original ID projections contain only strings/null; original JS key order is explicit.
            require(candidate["id"] == legacy_prefix + ":" + digest(json.dumps(legacy_body, separators=(",", ":"), ensure_ascii=False)), "Legacy candidate identity mismatch")
            verify_cif(text, expected_cell, expected_atoms, source, gemmi_module)
            state_projection = {"parent_id": parent_id, "edits": edits, "strain_micro_percent": int(strain), "conditions": CONDITIONS, "status": "unrelaxed"}
            state_id = identity("proposal-state", state_projection)
            group_id = identity("proposal-group", {"source_id": source["id"], "composition": {e: n // math.gcd(*counts.values()) for e, n in counts.items()}})
            label = formula(counts, source["formula"], edits)
            occurrence_body = {"source_batch_sha256": package["sha256"], "source_locator": f"/candidates/{index}", "legacy_candidate_id": candidate["id"], "cif_sha256": candidate["cif_sha256"]}
            occurrence_id = identity("proposal-occurrence", occurrence_body)
            occurrences.append({"id": occurrence_id, "state_id": state_id, **occurrence_body, "cif_text": text})
            if state_id not in states:
                states[state_id] = {"id": state_id, "group_id": group_id, **state_projection, "formula": label, "composition": counts,
                    "cell": expected_cell, "atoms": expected_atoms, "occurrence_ids": [], "primary_occurrence_id": occurrence_id,
                    "score": None, "rank": None, "formal_approval": None,
                    "physical_axes": {axis: {"status": "unknown", "value": None} for axis in AXES}, "next_action": NEXT_ACTION}
            else:
                require(states[state_id]["cell"] == expected_cell and states[state_id]["atoms"] == expected_atoms, "Same recipe produced conflicting geometry")
            states[state_id]["occurrence_ids"].append(occurrence_id)
            if group_id not in groups:
                groups[group_id] = {"id": group_id, "formula": label, "reduced_formula": formula(counts, source["formula"], edits, True),
                    "composition": {e: n // math.gcd(*counts.values()) for e, n in counts.items()}, "source_id": source["id"], "host_formula": source["formula"], "state_ids": []}
            if state_id not in groups[group_id]["state_ids"]:
                groups[group_id]["state_ids"].append(state_id)
    result = {"schema_version": "research-proposal-catalog/2.0.0", "version": manifest["version"],
              "selection_basis": "Manually selected retained coordinate batches; source and structural integrity checked. No scientific potential ranking.",
              "formal_scientific_release": False, "rps_release": False, "human_scientific_review": None,
              "counts": {"source_entries": len(occurrences), "coordinate_states": len(states), "composition_groups": len(groups), "duplicate_occurrences": len(occurrences)-len(states)},
              "sources": list(sources.values()), "parents": list(parents.values()), "states": list(states.values()), "groups": list(groups.values()), "occurrences": occurrences}
    require(0 < len(states) <= 100 and len(occurrences) <= 200, "Catalogue bound")
    require(len({o["id"] for o in occurrences}) == len(occurrences), "Duplicate source occurrence")
    encoded = pretty(result)
    require(len(encoded) <= 1024 * 1024, "Catalogue byte bound")
    require(not any(x in encoded.decode() for x in ["/Users/", "/var/", "jack@", "account_id", "campaign_budget"]), "Private metadata in public catalogue")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--require-gemmi", action="store_true")
    args = parser.parse_args()
    try:
        import gemmi
    except ImportError:
        gemmi = None
    require(not args.require_gemmi or gemmi is not None, "Gemmi unavailable; use the existing validation runtime")
    result = build(args.manifest, gemmi)
    output = OUTPUT_DIR / (result["version"] + ".json")
    pins = OUTPUT_DIR / (result["version"] + ".pins.json")
    encoded = pretty(result)
    pin_bytes = pretty({"version": result["version"], "sha256": digest(canonical(result)), "file_sha256": digest(encoded), "bytes": len(encoded)})
    if args.write:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
        pins.write_bytes(pin_bytes)
    else:
        require(output.read_bytes() == encoded and pins.read_bytes() == pin_bytes, "Reconstruction drift")
    print(json.dumps({"counts": result["counts"], "sha256": digest(encoded), "gemmi": getattr(gemmi, "__version__", None), "mode": "write" if args.write else "check"}))


if __name__ == "__main__":
    main()
