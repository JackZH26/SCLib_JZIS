"""Build a finite, source-qualified JARVIS reference; never import catalogue values."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import re
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "frontend/public/research-pilots"
SOURCE_NAME = "jarvis-host-records-2025-09-24.json"
OUTPUT_NAME = "discovery-host-reference-2026-10-05.json"
ZIP_SHA256 = "f9e0a3309f0000d5de1ec9e49c93963109ea45e63f451103f8f6595d2eabf7f5"
MEMBER_SHA256 = "9dacb55ac8371c7c2bf0332933b55c98e9cca6201e92eb9d6fcd03aab0975907"
FORMULAS = "Al2O3 MgO ZrO2 HfO2 Ga2O3 AlN BN GaN TiN NbN SiC TiC ZrC HfC NbC TiB2 ZrB2 MgB2 MgAl2O4 LaAlO3 SrTiO3 BaZrO3".split()
FAMILIES = dict(zip(FORMULAS, ["Oxide"] * 5 + ["Nitride"] * 5 + ["Carbide"] * 5 + ["Boride"] * 3 + ["Complex oxide"] * 4, strict=True))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture_archive(path: Path) -> bytes:
    """Recreate the subset from the pinned full archive without loading 254 MB at once."""
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != ZIP_SHA256:
            raise ValueError("Unexpected archive bytes")
    entries = []
    with ZipFile(path) as archive:
        member = "jdft_3d-9-24-2025.json"
        if archive.namelist() != [member] or archive.getinfo(member).file_size != 254061560:
            raise ValueError("Unexpected archive member")
        with archive.open(member) as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != MEMBER_SHA256:
                raise ValueError("Unexpected dataset bytes")
        decoder = json.JSONDecoder()
        buffer, index = "", 0
        with archive.open(member) as stream, io.TextIOWrapper(stream, encoding="utf-8", newline="") as reader:
            while chunk := reader.read(1024 * 1024):
                buffer += chunk
                while True:
                    buffer = buffer.lstrip(" \r\n\t[,")
                    if not buffer or buffer.startswith("]"):
                        break
                    try:
                        record, end = decoder.raw_decode(buffer)
                    except json.JSONDecodeError:
                        break
                    if record.get("formula") in FORMULAS:
                        entries.append({"dataset_row_index": index, "source_record_json": buffer[:end]})
                    buffer = buffer[end:]
                    index += 1
                if len(buffer) > 2_000_000:
                    raise ValueError("Record exceeds bound")
        if buffer.strip() != "]" or index != 93902 or len(entries) != 184:
            raise ValueError("Unexpected complete dataset inventory")
    return (json.dumps({"archive_sha256": ZIP_SHA256, "member_sha256": MEMBER_SHA256, "entries": entries}, indent=2) + "\n").encode()


def composition(formula: str) -> dict[str, int]:
    terms = re.findall(r"([A-Z][a-z]?)([0-9]*)", formula)
    if not terms or "".join(a + b for a, b in terms) != formula:
        raise ValueError("Unsupported source formula")
    counts: Counter[str] = Counter()
    for element, count in terms:
        counts[element] += int(count or 1)
    if min(counts.values()) < 1:
        raise ValueError("Invalid formula count")
    divisor = math.gcd(*counts.values())
    return {element: count // divisor for element, count in sorted(counts.items())}


def scalar(raw: str, record: dict, field: str, unit: str) -> dict:
    value = record.get(field)
    if type(value) not in (int, float) or not math.isfinite(value):
        # Do not silently make missing or malformed science look like zero.
        raise ValueError(f"Invalid {field}")
    token = re.search(r'"' + field + r'"\s*:\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*[,}]', raw)
    if not token or float(token[1]) != value:
        raise ValueError(f"Missing source token for {field}")
    return {"value": value, "raw": token[1], "unit": unit, "source_field": field, "uncertainty": None}


def build(source_bytes: bytes) -> dict:
    if len(source_bytes) > 2_000_000:
        raise ValueError("Source subset exceeds the finite pilot bound")
    source = json.loads(source_bytes)
    if source["archive_sha256"] != ZIP_SHA256 or source["member_sha256"] != MEMBER_SHA256:
        raise ValueError("Unexpected source edition")
    if len(source["entries"]) != 184:
        raise ValueError("Incomplete captured host subset")
    rows = []
    seen = set()
    previous_index = -1
    for entry in source["entries"]:
        raw = entry["source_record_json"]
        record = json.loads(raw)
        jid, formula, index = record["jid"], record["formula"], entry["dataset_row_index"]
        if not re.fullmatch(r"JVASP-[0-9]+", jid) or jid in seen or formula not in FORMULAS:
            raise ValueError("Invalid source identity")
        if type(index) is not int or not previous_index < index < 93902:
            raise ValueError("Invalid source row order")
        previous_index = index
        seen.add(jid)
        atoms = record["atoms"]
        elements = Counter(atoms["elements"])
        divisor = math.gcd(*elements.values())
        atom_composition = {element: count // divisor for element, count in sorted(elements.items())}
        if atom_composition != composition(formula) or len(atoms["coords"]) != len(atoms["elements"]):
            raise ValueError("Source composition and atom inventory disagree")
        inventory_matches = len(atoms["elements"]) == record["nat"]
        if record["func"] != "OptB88vdW" or record["typ"] != "bulk":
            raise ValueError("Unexpected method or dimensional scope")
        gap = scalar(raw, record, "optb88vdw_bandgap", "eV")
        if gap["value"] < 0:
            raise ValueError("Negative source gap")
        rows.append({
            "id": jid, "formula": formula, "family": FAMILIES[formula],
            "space_group": record["spg_symbol"], "space_group_number": record["spg_number"],
            "cell_atoms": record["nat"], "method": record["func"],
            "coordinate_atoms": len(atoms["elements"]), "plottable": inventory_matches,
            "review_note": "" if inventory_matches else "Source nat differs from the supplied coordinate count. Cell association requires review; excluded from the plot.",
            "formation_energy": scalar(raw, record, "formation_energy_peratom", "eV/atom"),
            "band_gap": gap,
            "source": {"dataset_row_index": index, "json_pointer": f"/{index}",
                       "record_sha256": digest(raw.encode()),
                       "atoms_sha256": digest(json.dumps(atoms, sort_keys=True, separators=(",", ":")).encode())},
        })
    if set(row["formula"] for row in rows) != set(FORMULAS):
        raise ValueError("Incomplete methodology formula coverage")
    return {
        "version": "discovery-host-physical-reference/1.0.0",
        "status": "external_computed_reference",
        "source": {"title": "JARVIS-DFT 3D dataset (jdft_3d.json)", "author": "Kamal Choudhary",
                   "doi": "10.6084/m9.figshare.6815699.v11", "license": "CC BY 4.0",
                   "license_url": "https://creativecommons.org/licenses/by/4.0/",
                   "download_url": "https://ndownloader.figshare.com/files/64391379",
                   "archive_sha256": ZIP_SHA256, "member": "jdft_3d-9-24-2025.json",
                   "member_sha256": MEMBER_SHA256, "dataset_records": 93902,
                   "subset_filename": SOURCE_NAME, "subset_sha256": digest(source_bytes),
                   "unit_reference": "https://github.com/usnistgov/alignn/blob/f2366daa3413d28a825b46e34d001b5549b05a40/README.md#2-on-jarvis-dft-2021-dataset-regression",
                   "changes": "Selected every matching record for the 22 named formulas; added locators and display metadata. Source object strings are unchanged."},
        "scope": {"formula_count": 22, "record_count": 184, "plotted_record_count": sum(row["plottable"] for row in rows), "formula_selection": FORMULAS,
                  "conditions": "Individual calculation temperature, pressure and convergence are not established by this metadata view.",
                  "association": "Provider JID only; no association with catalogue measurements or COD reference geometries.",
                  "ehull": "Excluded from axes: captured same-formula differences require normalization review. Original values remain in the source download.",
                  "inference": "Formation energy relative to elemental references is not convex-hull, phonon, chemical or finite-temperature stability. The band gap is an electronic descriptor, not a pairing or superconducting gap."},
        "authority": {"catalogue_updates": 0, "new_calculation_executed": False,
                      "stable_host_certified": False, "superconductivity_established": False,
                      "ml_training_approved": False},
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--archive", type=Path, help="Verify/recreate the source subset from the pinned public archive")
    args = parser.parse_args()
    if args.archive:
        captured = capture_archive(args.archive)
        if args.check:
            if (ASSETS / SOURCE_NAME).read_bytes() != captured:
                raise SystemExit("Source subset differs from pinned archive")
        else:
            (ASSETS / SOURCE_NAME).write_bytes(captured)
    result = build((ASSETS / SOURCE_NAME).read_bytes())
    payload = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode()
    target = ASSETS / OUTPUT_NAME
    checksum = f"{digest(payload)}  {OUTPUT_NAME}\n".encode()
    if args.check:
        source_checksum = f"{digest((ASSETS / SOURCE_NAME).read_bytes())}  {SOURCE_NAME}\n".encode()
        if target.read_bytes() != payload or Path(str(target) + ".sha256").read_bytes() != checksum or (ASSETS / (SOURCE_NAME + ".sha256")).read_bytes() != source_checksum:
            raise SystemExit("Host reference artifact differs from source reconstruction")
    else:
        target.write_bytes(payload)
        Path(str(target) + ".sha256").write_bytes(checksum)
        (ASSETS / (SOURCE_NAME + ".sha256")).write_text(f"{digest((ASSETS / SOURCE_NAME).read_bytes())}  {SOURCE_NAME}\n")
    print(f"184 records / 22 formulas; {digest(payload)}")


if __name__ == "__main__":
    main()
