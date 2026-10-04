"""Rebuild captured host coordinates offline with Gemmi 0.7.5.

The original three references remain byte-for-byte equal as JSON objects.
New references retain omitted occupancy separately from the CIF dictionary
default, and retain original ionic type symbols separately from elements.
No sample association, symmetry inference or physical calculation is performed.
"""
import collections
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

import gemmi

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend/public/research-pilots"
NAME = "discovery-structure-coordinates-2026-10-05.json"
CAPTURES = ROOT / "docs/data/discovery-host-source-captures-2026-10-05.json"
TOLERANCE = 0.001
OCCUPANCY_DICTIONARY = "https://www.iucr.org/__data/iucr/cifdic_html/1/cif_core.dic/Iatom_site_occupancy.html"


def numeric(raw):
    value = gemmi.cif.as_number(raw)
    if not math.isfinite(value):
        raise ValueError(f"Explicit finite numeric token required: {raw}")
    return value


def uncertainty(raw):
    match = re.fullmatch(r"[+-]?(\d*\.?\d+)\((\d+)\)(?:[eE]([+-]?\d+))?", raw)
    if not match:
        return None
    decimals = len(match[1].split(".")[1]) if "." in match[1] else 0
    return int(match[2]) * 10 ** (int(match[3] or 0) - decimals)


def same_periodic_point(cell, first, second, tolerance=TOLERANCE):
    """Exact finite search for images closer than tolerance, even in skew cells.

    If |A(delta+n)| < r, each fractional component is bounded by
    r times the norm of its reciprocal-basis row. Enumerate only those integers.
    No assumption that component-wise wrapping finds the nearest image.
    """
    delta = [a - b for a, b in zip(first, second)]
    reciprocal = cell.frac.mat.tolist()
    radii = [tolerance * math.sqrt(sum(v*v for v in row)) for row in reciprocal]
    choices = [range(math.ceil(-d-r), math.floor(-d+r)+1) for d, r in zip(delta, radii)]
    return any(cell.orthogonalize(gemmi.Fractional(*(d+n for d, n in zip(delta, shift)))).length() < tolerance
               for shift in itertools.product(*choices))


def build_reference(capture):
    meta, receipt = capture["search_record"], capture["capture"]
    source_bytes = (PUBLIC / "structure-cifs" / capture["filename"]).read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == receipt["sha256"]
    assert len(source_bytes) == receipt["bytes"]
    text = source_bytes.decode()
    block = gemmi.cif.read_string(text).sole_block()
    small = gemmi.make_small_structure_from_block(block)
    assert block.name == capture["cod_id"]
    revision = int(re.search(r"\$Revision: (\d+)", text)[1])
    if "@" in receipt["url"]:
        assert revision <= int(receipt["url"].rsplit("@", 1)[1])

    def value(*tags):
        return next((block.find_value(tag) for tag in tags if block.find_value(tag) is not None), None)

    def string(*tags):
        token = value(*tags)
        return gemmi.cif.as_string(token) if token is not None else None

    def line(tag):
        return next((i for i, row in enumerate(text.splitlines(), 1) if row.lower().startswith(tag.lower() + " ")), None)

    lattice = {}
    for axis in ["a", "b", "c", "alpha", "beta", "gamma"]:
        tag = "_cell_" + ("length_" if len(axis) == 1 else "angle_") + axis
        raw = value(tag)
        lattice[axis] = {"raw": raw, "value": numeric(raw), "unit": "Å" if len(axis) == 1 else "degrees",
                         "standard_uncertainty": uncertainty(raw),
                         "uncertainty_status": "reported" if uncertainty(raw) is not None else "not_reported",
                         "CIF_tag": tag, "CIF_line_1_based": line(tag)}
    assert small.cell.volume > 0
    conditions = {}
    for key, tag, unit in [("celltemp", "_cell_measurement_temperature", "K"),
                            ("diffrtemp", "_diffrn_ambient_temperature", "K"),
                            ("cellpressure", "_cell_measurement_pressure", "kPa"),
                            ("diffrpressure", "_diffrn_ambient_pressure", "kPa")]:
        raw = value(tag)
        supplied = raw not in (None, ".", "?")
        conditions[key] = {"raw": raw, "value": numeric(raw) if supplied else None,
                           "standard_uncertainty": uncertainty(raw) if supplied else None,
                           "unit": unit, "status": "source_reported" if supplied else "not_supplied",
                           "source_tag": tag, "source_line": line(tag)}

    labels = list(block.find_values("_atom_site_label"))
    symbols = list(block.find_values("_atom_site_type_symbol"))
    occupancies = list(block.find_values("_atom_site_occupancy"))
    coordinates = [list(block.find_values("_atom_site_fract_" + axis)) for axis in "xyz"]
    assert len(set(labels)) == len(labels) == len(small.sites) > 0
    assert all(len(c) == len(labels) for c in coordinates)
    assert not symbols or len(symbols) == len(labels)
    assert not occupancies or len(occupancies) == len(labels)
    sites = []
    for i, label in enumerate(labels):
        site = small.sites[i]
        assert site.label == gemmi.cif.as_string(label) and site.element.atomic_number > 0
        raw = occupancies[i] if occupancies else None
        occupancy = {"raw": raw, "value": numeric(raw) if raw is not None else 1.0,
                     "basis": "source_token" if raw is not None else "cif_dictionary_default"}
        assert 0 <= occupancy["value"] <= 1
        assert abs(occupancy["value"] - site.occ) < 1e-8
        sites.append({"label": site.label, "element": site.element.name,
                      "type_symbol_raw": symbols[i] if symbols else None,
                      "element_basis": "type_symbol" if symbols else "CIF_label_element_prefix",
                      "fractional": [{"raw": c[i], "value": numeric(c[i])} for c in coordinates],
                      "occupancy": occupancy})
    operation_tag = next((tag for tag in ["_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"]
                          if len(block.find_values(tag))), None)
    assert operation_tag, "Only explicit source operations are accepted"
    operations = [gemmi.cif.as_string(op) for op in block.find_values(operation_tag)]
    expanded = []
    for site in sites:
        unique = []
        for index, expression in enumerate(operations):
            point = [v % 1 for v in gemmi.Op(expression).apply_to_xyz([v["value"] for v in site["fractional"]])]
            same = next((x for x in unique if same_periodic_point(small.cell, point, x["fractional"])), None)
            if same is not None:
                same["equivalent_operation_indices"].append(index)
            else:
                unique.append({"source_site_label": site["label"], "element": site["element"], "fractional": point,
                               "occupancy": site["occupancy"], "representative_operation_index": index,
                               "equivalent_operation_indices": [index]})
        expanded.extend(unique)
    gemmi_sites = small.get_all_unit_cell_sites()
    assert len(gemmi_sites) == len(expanded), "Independent Gemmi expansion count differs"
    for point in expanded:
        assert any(site.label == point["source_site_label"] and
                   same_periodic_point(small.cell, point["fractional"], [site.fract.x, site.fract.y, site.fract.z])
                   for site in gemmi_sites)
    # Require distinct ordered sites; mixed/partial occupancy remains an explicit model.
    overlaps = sum(same_periodic_point(small.cell, a["fractional"], b["fractional"])
                   for a, b in itertools.combinations(expanded, 2))
    counts = collections.defaultdict(float)
    for point in expanded:
        counts[point["element"]] += point["occupancy"]["value"]
    declared = string("_chemical_formula_sum")
    terms = re.findall(r"([A-Z][a-z]?)([0-9.]*)", declared)
    assert " ".join(element + number for element, number in terms) == declared
    formula = {element: float(number or 1) for element, number in terms}
    ratios = [counts[element] / number for element, number in formula.items()]
    assert set(counts) == set(formula) and max(ratios) - min(ratios) < 0.005
    z = value("_cell_formula_units_Z")
    if z:
        assert abs(ratios[0] - numeric(z)) < 0.005
    bibliography = {key: meta.get(key) for key in ["authors", "title", "journal", "year", "volume", "firstpage", "lastpage", "doi"]}
    bibliography.update(CIF_doi=string("_journal_paper_doi"), COD_method=string("_cod_determination_method"), CIF_radiation_probe=string("_diffrn_radiation_probe"))
    sg = string("_space_group_name_H-M_alt", "_symmetry_space_group_name_H-M")
    sg_number = int(numeric(value("_space_group_IT_number", "_symmetry_Int_Tables_number")))
    assert int(meta["sgNumber"]) == sg_number
    return {"id": "cod-" + capture["cod_id"], "formula": capture["formula"], "declared_formula": declared,
            "space_group": sg, "space_group_number": sg_number, "lattice": lattice, "structure_conditions": conditions,
            "source": {"entry_url": f"https://www.crystallography.net/cod/{capture['cod_id']}.html",
                       "cif_url": receipt["url"], "captured_revision": revision,
                       "version_url_succeeded_at_capture": "@" in receipt["url"],
                       "file_sha256": receipt["sha256"], "bytes": receipt["bytes"],
                       "year": int(meta["year"]), "doi": meta.get("doi"), "bibliography": bibliography,
                       "captured_at_utc": receipt["captured_at_utc"], "captured_HTTP_status": receipt["http_status"],
                       "license": "CC0-1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                       "license_basis": "Official COD home page dedicates all COD data to CC0; acknowledge the source authors.",
                       "download_is_mutable_current_file": "@" not in receipt["url"], "publication_revision_verified": False},
            "original_cif_filename": capture["filename"], "sites": sites, "declared_symmetry_operations": operations,
            "display_unit_cell_sites": expanded,
            "limitations": ["Structure references do not establish sample association, superconductivity or target-condition stability.",
                            "Missing numeric temperature and pressure remain unspecified.", capture["selection_reason"]],
            "rounding_notes": ["Source central coordinates are expanded without snapping or averaging; geometric grouping tolerance is 0.001 Å."],
            "host_context": {"family": capture["family"], "phase": capture["phase"], "selection_reason": capture["selection_reason"],
                             "operation_tag": operation_tag, "occupancy_default_dictionary": OCCUPANCY_DICTIONARY,
                             "expanded_weighted_composition": dict(counts), "coincident_site_pairs": overlaps,
                             "formula_units_token": z, "gemmi_expansion_count": len(gemmi_sites)}}


def build(check=False):
    assert gemmi.__version__ == "0.7.5"
    original = json.loads((PUBLIC / "discovery-structure-coordinates-2026-10-04.json").read_text())
    captures = json.loads(CAPTURES.read_text())
    new = [build_reference(c) for c in captures]
    artifact = {**original, "version": "discovery-structure-coordinates/1.1.0", "prepared_on": "2026-10-05",
                "occupancy_default_dictionary": OCCUPANCY_DICTIONARY,
                "references": original["references"] + new}
    data = (json.dumps(artifact, ensure_ascii=False, indent=2) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    checksum = f"{digest}  {NAME}\n"
    if check:
        assert (PUBLIC / NAME).read_bytes() == data, "Captured inventory differs from reconstruction"
        assert (PUBLIC / (NAME + ".sha256")).read_text() == checksum
    else:
        (PUBLIC / NAME).write_bytes(data)
        (PUBLIC / (NAME + ".sha256")).write_text(checksum)
    print(f"{len(artifact['references'])} references; SHA-256 {digest}")
    for ref in new:
        print(ref["formula"], ref["id"], len(ref["display_unit_cell_sites"]), "sites", ref["host_context"]["expanded_weighted_composition"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify exact reproduction without writing files")
    build(parser.parse_args().check)
