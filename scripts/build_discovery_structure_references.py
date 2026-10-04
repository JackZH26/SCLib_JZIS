"""Reproduce the finite COD coordinate reference artifact (requires Gemmi 0.7.5).

Reads only the three byte-pinned, CC0 CIFs already in this repository. No network,
catalogue association, structure relaxation or symmetry inference is performed.
"""
import hashlib
import itertools
import json
import math
from pathlib import Path

import gemmi

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend/public/research-pilots"
NAME = "discovery-structure-coordinates-2026-10-04.json"
TOLERANCE = 0.001  # Angstrom; display deduplication, never a change to source sites.


def periodic_distance(cell, first, second):
    # This finite pilot has orthogonal/hexagonal cells; adjacent translations
    # suffice here. Do not reuse this as a general triclinic nearest-image search.
    lengths = []
    for shift in itertools.product((-1, 0, 1), repeat=3):
        difference = gemmi.Fractional(*(a - b + n for a, b, n in zip(first, second, shift)))
        position = cell.orthogonalize(difference)
        lengths.append(math.sqrt(position.x ** 2 + position.y ** 2 + position.z ** 2))
    return min(lengths)


def scalar(raw):
    value = gemmi.cif.as_number(raw)
    if not math.isfinite(value):
        raise ValueError("The finite pilot requires explicitly supplied numeric sites")
    return {"raw": raw, "value": value}


def build():
    if gemmi.__version__ != "0.7.5":
        raise ValueError("Reproduce with the recorded Gemmi 0.7.5 parser")
    refs = json.loads((PUBLIC / "materials-source-references-2026-10-02.json").read_text())["structure_references"]
    output = []
    for ref in refs:
        source = ref["source"]
        filename = f"{ref['cod_id']}-{source['file_sha256'][:12]}.cif"
        path = PUBLIC / "structure-cifs" / filename
        data = path.read_bytes()
        if len(data) != source["bytes"] or hashlib.sha256(data).hexdigest() != source["file_sha256"]:
            raise ValueError(f"CIF identity mismatch: {ref['cod_id']}")
        block = gemmi.cif.read_string(data.decode()).sole_block()
        small = gemmi.make_small_structure_from_block(block)
        sites = []
        tags = ["label", "type_symbol", "fract_x", "fract_y", "fract_z", "occupancy"]
        for row in block.find(["_atom_site_" + tag for tag in tags]):
            row = list(row)
            sites.append({"label": row[0], "element": row[1],
                          "fractional": [scalar(raw) for raw in row[2:5]],
                          "occupancy": scalar(row[5])})
        operations = list(block.find_values("_symmetry_equiv_pos_as_xyz"))
        operations = [gemmi.cif.as_string(op) for op in operations]
        if len(sites) != 2 or len(operations) not in (16, 24):
            raise ValueError("Unexpected source inventory")
        expanded = []
        for site in sites:
            unique = []
            for index, expression in enumerate(operations):
                image = [coordinate % 1 for coordinate in gemmi.Op(expression).apply_to_xyz(
                    [coordinate["value"] for coordinate in site["fractional"]])]
                same = next((point for point in unique if periodic_distance(
                    small.cell, image, point["fractional"]) < TOLERANCE), None)
                if same is not None:
                    same["equivalent_operation_indices"].append(index)
                    continue
                unique.append({"source_site_label": site["label"], "element": site["element"],
                               "fractional": image, "occupancy": site["occupancy"],
                               "representative_operation_index": index,
                               "equivalent_operation_indices": [index]})
            expanded.extend(unique)
        expected = 4 if ref["cod_id"] == "4002152" else 3
        if len(expanded) != expected:
            raise ValueError("Unexpected symmetry expansion")
        output.append({"id": ref["id"], "formula": ref["formula"],
                       "declared_formula": ref["declared_formula"],
                       "space_group": ref["declared_space_group"],
                       "space_group_number": ref["declared_space_group_number"],
                       "lattice": ref["lattice"], "structure_conditions": ref["structure_conditions"],
                       "source": source, "original_cif_filename": filename,
                       "sites": sites, "declared_symmetry_operations": operations,
                       "display_unit_cell_sites": expanded, "limitations": ref["limitations"],
                       "rounding_notes": ref["checks"]["rounding_scope"]})
    artifact = {"version": "discovery-structure-coordinates/1.0.0", "prepared_on": "2026-10-04",
                "parser": "Gemmi 0.7.5", "site_coordinate_system": "fractional",
                "display_expansion": {"operation_source": "CIF declared operations, in source order",
                                      "periodic_deduplication_tolerance_angstrom": TOLERANCE,
                                      "representative": "first image per listed site, modulo one; no snapping or averaging",
                                      "indices_are_zero_based": True},
                "scope": {"catalogue_sample_association": "unestablished", "stable_host_validated": False,
                          "independent_symmetry_inference": False, "relaxation_executed": False,
                          "scientific_acceptance": False, "ml_training_approved": False},
                "references": output}
    data = (json.dumps(artifact, ensure_ascii=False, indent=2) + "\n").encode()
    (PUBLIC / NAME).write_bytes(data)
    (PUBLIC / (NAME + ".sha256")).write_text(f"{hashlib.sha256(data).hexdigest()}  {NAME}\n")
    print(f"{len(output)} references; {sum(len(x['sites']) for x in output)} listed sites; {len(data)} bytes")


if __name__ == "__main__":
    build()
