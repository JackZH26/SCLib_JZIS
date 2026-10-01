"""Versioned NIMS MDR source-row references; never selected material properties.

This packaged CC-BY-4.0 snapshot covers the oxide/metallic table only. Formula
matches do not establish sample, phase, isotope-state or publication acceptance.
No network, source-paper text, coordinates or canonical writes are involved.
"""
from __future__ import annotations

import asyncio
import csv
import gzip
import hashlib
import io
import json
import math
import re
import threading
import zlib
from pathlib import Path
from typing import Any

from services._composition.formula_enrichment import enrich_formula
from services.material_external_references import external_query_formula

VERSION = "material-supercon-references/1.0.0"
DATA_VERSION = "240322"
DATA_DOI = "https://doi.org/10.48505/nims.4487"
SOURCE_URL = "https://mdr.nims.go.jp/filesets/2347b413-9c15-43b7-90e6-41fe9243b1a5/download"
SOURCE_FILE = "20240322_MDR_OAndM.txt"
SOURCE_SHA256 = "f599ef0040c18521e386f758ee826fe269f67ef369c1a007656035d03ccdfdf6"
HEADER_SHA256 = "eead04a2ef6843764dd1d70a71a820b6ab52b14ea91131a80541fa7da447261c"
EXPECTED_ROWS = 33458
EXPECTED_COLUMNS = 191
MAX_REFERENCES = 20
MAX_SOURCE_BYTES = 22_000_000
MAX_RESOURCE_BYTES = 4_000_000
MAX_DECOMPRESSED_BYTES = 20_000_000
RESOURCE_DIR = Path(__file__).parent / "resources"
RESOURCE_PATH = RESOURCE_DIR / "supercon_mdr_240322_oxide_metadata.json.gz"
MANIFEST_PATH = RESOURCE_DIR / "supercon_mdr_240322_manifest.json"
ATTRIBUTION = "MDR SuperCon Datasheet Ver.240322, National Institute for Materials Science (NIMS), DOI 10.48505/nims.4487. Licensed under Creative Commons Attribution 4.0 International."

# field: label, source unit column (None means no supplied unit), meaning,
# source temperature column, direction. Labels/contexts come from the versioned
# NIMS guide, not an inferred joint observation or a family prior.
QUANTITIES = {
    "tc": ("Tc (recommended for source sample)", "utc", "recommended_tc", None, None),
    "t1": ("Tc (R = 0)", "utc", "zero_resistance_tc", None, None),
    "t2": ("Tc (midpoint)", "utc", "midpoint_tc", None, None),
    "t3": ("Tc (R = 100%)", "utc", "resistive_r100_tc", None, None),
    "tcsus": ("Tc (susceptibility)", "utc", "susceptibility_tc", None, None),
    "tcn": ("Lowest measurement temperature (non-SC report)", "utc", "non_superconducting_measurement_lower_temperature_not_tc", None, None),
    "tcwidth": ("Resistive transition width", "utc", "transition_width_not_tc", None, None),
    "lata": ("Lattice a", "ulat", "lattice_parameter", None, None),
    "latb": ("Lattice b", "ulat", "lattice_parameter", None, None),
    "latc": ("Lattice c", "ulat", "lattice_parameter", None, None),
    "hc1zero": ("Hc1 at 0 K (polycrystal)", "uhc1", "source_column_reports_zero_kelvin", None, None),
    "hc1t": ("Hc1 at supplied temperature (polycrystal)", "uhc1", "measurement_temperature_unit_not_supplied", "tempc1", None),
    "hc2zero": ("Hc2 at 0 K (polycrystal)", "uhc2", "source_column_reports_zero_kelvin", None, None),
    "phc2zero": ("Hc2 at 0 K (H parallel to ab)", "uhc2", "source_column_reports_zero_kelvin", None, "H_parallel_ab"),
    "nhc2zero": ("Hc2 at 0 K (H parallel to c)", "uhc2", "source_column_reports_zero_kelvin", None, "H_parallel_c"),
    "hc2t": ("Hc2 at supplied temperature (polycrystal)", "uhc2", "measurement_temperature_unit_not_supplied", "tempc2", None),
    "phc2t": ("Hc2 at supplied temperature (H parallel to ab)", "uhc2", "measurement_temperature_unit_not_supplied", "tempc2", "H_parallel_ab"),
    "nhc2t": ("Hc2 at supplied temperature (H parallel to c)", "uhc2", "measurement_temperature_unit_not_supplied", "tempc2", "H_parallel_c"),
    "cohere": ("Coherence length at 0 K (polycrystal)", "ucohere", "source_column_reports_zero_kelvin", None, None),
    "pcohere": ("Coherence length at 0 K (H parallel to ab)", "ucohere", "source_column_reports_zero_kelvin", None, "H_parallel_ab"),
    "ncohere": ("Coherence length at 0 K (H normal to ab)", "ucohere", "source_column_reports_zero_kelvin", None, "H_normal_ab"),
    "penet": ("Penetration depth at 0 K (polycrystal)", "upenet", "source_column_reports_zero_kelvin", None, None),
    "ppenet": ("Penetration depth at 0 K (H parallel to ab)", "upenet", "source_column_reports_zero_kelvin", None, "H_parallel_ab"),
    "npenet": ("Penetration depth at 0 K (H normal to ab)", "upenet", "source_column_reports_zero_kelvin", None, "H_normal_ab"),
    "gamma": ("Electronic specific heat coefficient", "ugamma", "electronic_specific_heat_coefficient", None, None),
    "debyet": ("Debye temperature", None, "temperature_unit_not_supplied", None, None),
    "gap": ("Energy gap at 0 K", "ugap", "source_column_reports_zero_kelvin", None, None),
    "gapene": ("2 delta(0) / k Tc", "__dimensionless", "normalized_energy_gap_not_energy", None, None),
    "isotope": ("Isotope-effect exponent", "__dimensionless", "alpha_in_tc_equals_a_times_mass_to_minus_alpha", None, None),
    "dtcdp": ("dTc/dP at P = 0", "udtcdp", "pressure_derivative_not_measurement_pressure", None, None),
    "pmax": ("Maximum pressure applied", None, "maximum_applied_pressure_not_any_tc_measurement_pressure", None, None),
    "vols": ("Meissner volume fraction", "__percent", "source_column_reports_percent", None, None),
}
SELECTED_COLUMNS = tuple(dict.fromkeys((
    "num", "element", "name", "refno", "title", "journal", "year", "sample",
    "spaceg", "tblno", "str3", "shape", "analm", "tcmeth", "isoel", "isorat",
    *QUANTITIES, *(q[1] for q in QUANTITIES.values() if q[1] and not q[1].startswith("__")),
    "tempc1", "tempc2", "mhc1", "mhc2", "mcohere", "mpenet", "gapmeth", "gamcom", "mdebye",
)))
CODE_LABELS = {
    "shape": {"1": "Single phase bulk", "2": "Multiphase bulk", "3": "Single crystal bulk", "4": "Film", "5": "Film (single)"},
    "analm": {"1": "X-ray crystallography", "2": "Neutron crystallography", "3": "Powder X-ray diffraction", "4": "Powder neutron diffraction", "5": "Electron diffraction"},
    "tcmeth": {"1": "Magnetization", "2": "AC susceptibility", "3": "Resistivity", "4": "Heat capacity", "5": "Tunneling", "6": "Infrared spectroscopy", "7": "Thermal conductivity", "8": "Raman spectroscopy", "9": "Nuclear magnetic resonance", "10": "Surface impedance", "11": "Neutron diffraction", "12": "Photoemission spectroscopy", "13": "Microwave transmission", "14": "Other method"},
}
_GAP_METHODS = {"1": "Tunneling", "2": "Infrared spectroscopy", "3": "Thermal conductivity", "4": "Raman spectroscopy", "5": "AC susceptibility", "6": "Nuclear magnetic resonance", "7": "Surface impedance", "8": "Neutron diffraction", "9": "Ultraviolet photoemission spectroscopy", "10": "Microwave transmission"}
METHOD_COLUMNS = ("mhc1", "mhc2", "mcohere", "mpenet", "gapmeth", "gamcom", "mdebye")
_LENGTH_UNITS = {"A": "Å", "Å": "Å", "nm": "nm", "um": "µm", "micron": "µm", "micrometer": "µm", "mm": "mm"}
_FIELD_UNITS = {"T": "T", "mT": "mT", "kT": "kT", "micro-T": "µT", "Oe": "Oe", "kOe": "kOe", "KOe": "kOe", "gauss": "G", "G": "G", "kG": "kG", "KG": "kG", "kA/m": "kA/m", "E+3 A/m": "10³ A/m"}
_UNIT_MAPS = {
    "utc": {"K": "K"}, "ulat": _LENGTH_UNITS, "ucohere": _LENGTH_UNITS, "upenet": _LENGTH_UNITS,
    "uhc1": _FIELD_UNITS, "uhc2": _FIELD_UNITS,
    "ugap": {"meV": "meV", "K": "K", "cm-1": "cm⁻¹", "cm(-1)": "cm⁻¹", "micro-eV": "µeV"},
    "ugamma": {"mJ/mol.K2": "mJ/(mol K²)", "mJ/molK2": "mJ/(mol K²)", "mJ/K2mol": "mJ/(mol K²)", "J/mol.K2": "J/(mol K²)", "uJ/g.K2": "µJ/(g K²)", "uJ/K2.g": "µJ/(g K²)"},
    "udtcdp": {"K/GPa": "K/GPa", "K/GPA": "K/GPa", "K/Gpa": "K/GPa", "K/kbar": "K/kbar", "K/KBAR": "K/kbar", "K/kBar": "K/kbar", "K/Kbar": "K/kbar", "mK/MPa": "mK/MPa"},
}
_HEX = re.compile(r"[0-9a-f]{64}")
_NUM = re.compile(r"(?:0|[1-9][0-9]{0,9})")
_load_lock = threading.Lock()
_snapshot: tuple[dict, dict] | None = None
_workers = asyncio.Semaphore(2)
_worker_tasks: set[asyncio.Task] = set()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _composition_key(formula: str) -> tuple | None:
    parsed = enrich_formula(formula)
    return tuple(sorted(parsed["atomic_fractions"].items())) if parsed["composition_status"] == "exact" else None


def parse_source_table(raw: bytes, *, require_known_snapshot: bool = True) -> list[dict]:
    """Validate source bytes/headers/IDs and preserve exact physical row hashes.

    The actual release has two headers; quoted multiline author cells explain
    why physical lines and records differ. Authors are not projected, but their
    original bytes still participate in each complete source row hash.
    """
    if type(raw) is not bytes or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source byte bound")
    lines = raw.splitlines(keepends=True)
    if len(lines) < 3:
        raise ValueError("missing source headers")
    if require_known_snapshot and hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("unexpected immutable source snapshot")
    reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), delimiter="\t")
    labels, symbols = next(reader), next(reader)
    if (len(labels) != len(symbols) or len(set(symbols)) != len(symbols)
            or not set(SELECTED_COLUMNS).issubset(symbols)):
        raise ValueError("source schema requires review")
    if require_known_snapshot and (len(symbols) != EXPECTED_COLUMNS or hashlib.sha256(lines[0] + lines[1]).hexdigest() != HEADER_SHA256):
        raise ValueError("unexpected immutable source headers")
    previous = reader.line_num
    rows, seen = [], set()
    for values in reader:
        start, end = previous + 1, reader.line_num
        previous = end
        if len(values) != len(symbols):
            raise ValueError("source row width requires review")
        row = dict(zip(symbols, values, strict=True))
        number = row["num"]
        if not _NUM.fullmatch(number) or number in seen:
            raise ValueError("source row identity requires review")
        seen.add(number)
        selected = [row[column] for column in SELECTED_COLUMNS]
        if any(len(value) > 1000 or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in selected):
            raise ValueError("selected source cell requires review")
        rows.append({"n": number, "l": start, "e": end,
                     "h": hashlib.sha256(b"".join(lines[start - 1:end])).hexdigest(), "v": selected})
    if reader.line_num != len(lines):
        raise ValueError("physical source row boundaries require review")
    if require_known_snapshot and len(rows) != EXPECTED_ROWS:
        raise ValueError("unexpected immutable source row count")
    return sorted(rows, key=lambda row: int(row["n"]))


def build_snapshot(raw: bytes) -> tuple[bytes, dict]:
    rows = parse_source_table(raw)
    document = {"schema_version": VERSION, "dataset_version": DATA_VERSION, "dataset_doi": DATA_DOI,
                "source_sha256": SOURCE_SHA256, "columns": list(SELECTED_COLUMNS), "rows": rows}
    plain = _canonical(document)
    if len(plain) > MAX_DECOMPRESSED_BYTES:
        raise ValueError("projected snapshot byte bound")
    compressed = gzip.compress(plain, compresslevel=9, mtime=0)
    if len(compressed) > MAX_RESOURCE_BYTES:
        raise ValueError("compressed snapshot byte bound")
    manifest = {"schema_version": VERSION, "dataset_version": DATA_VERSION, "dataset_doi": DATA_DOI,
                "provider": "MDR SuperCon", "source_table": "oxide_metallic", "source_file": SOURCE_FILE,
                "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256, "source_bytes": len(raw),
                "source_header_sha256": HEADER_SHA256, "source_header_rows": 2,
                "source_rows": len(rows), "source_columns": EXPECTED_COLUMNS,
                "resource_file": RESOURCE_PATH.name, "resource_sha256": hashlib.sha256(compressed).hexdigest(),
                "resource_bytes": len(compressed), "decompressed_sha256": hashlib.sha256(plain).hexdigest(),
                "decompressed_bytes": len(plain), "projected_columns": list(SELECTED_COLUMNS),
                "row_hash_basis": "complete_original_physical_source_lines_including_line_endings",
                "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/legalcode",
                "attribution": ATTRIBUTION, "guide_doi": "https://doi.org/10.48505/nims.4488",
                "guide_sha256": "89096c1f006a5d5c256d14394880b31684ad2ce0b4f7ea0d37175256ea6a029d",
                "scope": "oxide_metallic_only_organic_table_not_included", "source_publication_status": "not_checked",
                "scientific_acceptance": False, "sample_identity_established": False,
                "phase_identity_established": False, "canonical_properties_modified": False,
                "builder": "scripts/build_supercon_mdr_snapshot.py/1.0.0"}
    return compressed, manifest


def _read_snapshot() -> tuple[dict, dict]:
    global _snapshot
    with _load_lock:
        if _snapshot is not None:
            return _snapshot
        if MANIFEST_PATH.stat().st_size > 16000 or RESOURCE_PATH.stat().st_size > MAX_RESOURCE_BYTES:
            raise ValueError("packaged resource byte bound")
        manifest = json.loads(MANIFEST_PATH.read_bytes())
        if (type(manifest) is not dict or manifest.get("schema_version") != VERSION or manifest.get("source_sha256") != SOURCE_SHA256
                or manifest.get("source_header_sha256") != HEADER_SHA256
                or manifest.get("dataset_doi") != DATA_DOI or manifest.get("dataset_version") != DATA_VERSION
                or manifest.get("source_rows") != EXPECTED_ROWS or manifest.get("projected_columns") != list(SELECTED_COLUMNS)
                or manifest.get("license") != "CC BY 4.0" or manifest.get("source_table") != "oxide_metallic"
                or any(manifest.get(key) is not False for key in ("scientific_acceptance", "sample_identity_established", "phase_identity_established", "canonical_properties_modified"))):
            raise ValueError("packaged manifest requires review")
        compressed = RESOURCE_PATH.read_bytes()
        if len(compressed) != manifest.get("resource_bytes") or hashlib.sha256(compressed).hexdigest() != manifest.get("resource_sha256"):
            raise ValueError("packaged snapshot integrity")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
            plain = handle.read(MAX_DECOMPRESSED_BYTES + 1)
        if (len(plain) > MAX_DECOMPRESSED_BYTES or len(plain) != manifest.get("decompressed_bytes")
                or hashlib.sha256(plain).hexdigest() != manifest.get("decompressed_sha256")):
            raise ValueError("decompressed snapshot integrity")
        document = json.loads(plain)
        if (type(document) is not dict or set(document) != {"schema_version", "dataset_version", "dataset_doi", "source_sha256", "columns", "rows"}
                or document.get("schema_version") != VERSION or document.get("dataset_version") != DATA_VERSION
                or document.get("dataset_doi") != DATA_DOI or document.get("source_sha256") != SOURCE_SHA256
                or document.get("columns") != list(SELECTED_COLUMNS) or type(document.get("rows")) is not list
                or len(document["rows"]) != EXPECTED_ROWS):
            raise ValueError("snapshot document requires review")
        index: dict[tuple, list[dict]] = {}
        previous_id = -1
        for encoded in document["rows"]:
            if (type(encoded) is not dict or set(encoded) != {"n", "l", "e", "h", "v"}
                    or type(encoded["n"]) is not str or not _NUM.fullmatch(encoded["n"])
                    or int(encoded["n"]) <= previous_id or type(encoded["l"]) is not int or encoded["l"] < 3
                    or type(encoded["e"]) is not int or encoded["e"] < encoded["l"]
                    or type(encoded["h"]) is not str or not _HEX.fullmatch(encoded["h"])
                    or type(encoded["v"]) is not list or len(encoded["v"]) != len(SELECTED_COLUMNS)
                    or any(type(v) is not str or len(v) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in encoded["v"])):
                raise ValueError("snapshot row requires review")
            previous_id = int(encoded["n"])
            raw_row = dict(zip(SELECTED_COLUMNS, encoded["v"], strict=True))
            if raw_row["num"] != encoded["n"]:
                raise ValueError("snapshot row identity mismatch")
            key = _composition_key(raw_row["element"])
            if key is not None:
                index.setdefault(key, []).append(encoded)
        _snapshot = manifest, index
        return _snapshot


def _code(row: dict, field: str) -> dict:
    raw = row.get(field) or None
    label = CODE_LABELS[field].get(raw)
    return {"raw_code": raw, "label": label,
            "status": "reported" if label else "not_supplied" if raw is None else "requires_review"}


def _finite(value: str) -> float | None:
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _quantity_method(row: dict, field: str) -> dict:
    if field in {"tc", "t1", "t2", "t3", "tcsus", "tcn", "tcwidth"}:
        source = "tcmeth"
    elif field in {"lata", "latb", "latc"}:
        source = "analm"
    elif field.startswith("hc1"):
        source = "mhc1"
    elif field in {"hc2zero", "phc2zero", "nhc2zero", "hc2t", "phc2t", "nhc2t"}:
        source = "mhc2"
    elif field in {"cohere", "pcohere", "ncohere"}:
        source = "mcohere"
    elif field in {"penet", "ppenet", "npenet"}:
        source = "mpenet"
    else:
        source = {"gap": "gapmeth", "gapene": "gapmeth", "gamma": "gamcom", "debyet": "mdebye"}.get(field)
    raw = row.get(source) or None
    if raw is None:
        label = None
    elif source in {"tcmeth", "analm"}:
        label = CODE_LABELS[source].get(raw)
    elif source == "gapmeth":
        label = _GAP_METHODS.get(raw)
    elif raw.isdigit():
        # The guide supplies a numerical codebook for mhc1, but mhc2 is a
        # free-text field. Its three actual raw "3" cells remain unresolved.
        label = CODE_LABELS["tcmeth"].get(raw) if source == "mhc1" else None
    else:
        # Free-text derivation descriptions are reported source metadata, not
        # normalized methods or proof that a fitted/calculated value is observed.
        label = raw
    return {"source_method_raw": raw, "method_label": label,
            "method_status": "not_supplied" if raw is None else "reported" if label else "requires_review"}


def project_source_row(encoded: dict) -> dict:
    row = dict(zip(SELECTED_COLUMNS, encoded["v"], strict=True))
    quantities = []
    for field, (label, unit_column, meaning, temperature_column, direction) in QUANTITIES.items():
        raw = row[field]
        if not raw:
            continue
        raw_unit = row.get(unit_column) or None
        unit = _UNIT_MAPS.get(unit_column, {}).get(raw_unit)
        if unit_column == "__dimensionless":
            unit = "dimensionless"
        elif unit_column == "__percent":
            unit = "%"
        number = _finite(raw)
        status = ("value_requires_review" if number is None else "reported" if unit
                  else "unit_not_supplied" if raw_unit is None else "unit_requires_review")
        quantities.append({"field": field, "label": label, "raw_value": raw, "value": number,
                           "raw_unit": raw_unit, "unit": unit, "status": status, "meaning": meaning,
                           "temperature_raw": row.get(temperature_column) or None, "direction": direction,
                           **_quantity_method(row, field)})
    raw_group = row["tblno"] or None
    group = int(raw_group) if raw_group and re.fullmatch(r"[0-9]{1,3}", raw_group) and 1 <= int(raw_group) <= 230 else None
    return {"id": "mdr:" + DATA_VERSION + ":oxide_metallic:" + row["num"], "source_row_id": row["num"],
            "source_table": "oxide_metallic", "source_file": SOURCE_FILE,
            "source_sha256": SOURCE_SHA256, "source_row_sha256": encoded["h"],
            "source_line": encoded["l"], "source_line_end": encoded["e"], "url": DATA_DOI,
            "formula": row["element"], "raw_common_formula": row["name"] or None,
            "bibliography": {"reference_code": row["refno"] or None, "title": row["title"] or None,
                             "journal": row["journal"] or None, "publication_year_raw": row["year"] or None},
            "structure": {"space_group": row["spaceg"] or None, "space_group_number": group,
                          "space_group_number_raw": raw_group, "common_name": row["str3"] or None},
            "sample_form": _code(row, "shape"), "structure_method": _code(row, "analm"),
            "tc_method": _code(row, "tcmeth"), "isotope_element": row["isoel"] or None,
            "isotope_exchange_ratio": row["isorat"] or None, "sample_identifier": row["sample"] or None,
            "raw_source_method_fields": {field: row[field] or None for field in METHOD_COLUMNS},
            "quantities": quantities}


def _base(formula: str, status: str, reason: str | None = None, query: str | None = None) -> dict:
    return {"version": VERSION, "provider": "MDR SuperCon", "formula": formula,
            "query_formula": query, "status": status, "reason": reason, "references": [],
            "matches_total": None, "omitted_rows": 0, "truncated": False,
            "dataset_version": DATA_VERSION, "dataset_doi": DATA_DOI,
            "license": "CC BY 4.0", "attribution": ATTRIBUTION,
            "scope": "oxide_metallic_curated_source_rows_composition_references_not_selected_material_properties",
            "snapshot_sha256": SOURCE_SHA256, "resource_sha256": None,
            "source_publication_status": "not_checked", "scientific_acceptance": False,
            "sample_identity_established": False, "phase_identity_established": False}


def _query_snapshot(formula: str, query: str) -> dict:
    try:
        manifest, index = _read_snapshot()
    except (OSError, ValueError, KeyError, TypeError, EOFError, UnicodeError, RecursionError, zlib.error):
        return _base(formula, "unavailable", "snapshot_unavailable_or_requires_review", query)
    rows = index.get(_composition_key(query), [])
    response = _base(formula, "available" if rows else "no_match",
                     None if rows else "no_fixed_composition_row_in_oxide_metallic_240322", query)
    response.update(references=[project_source_row(row) for row in rows[:MAX_REFERENCES]],
                    matches_total=len(rows), omitted_rows=max(0, len(rows) - MAX_REFERENCES),
                    truncated=len(rows) > MAX_REFERENCES, resource_sha256=manifest["resource_sha256"])
    return response


async def fetch_material_supercon_references(formula: str, *, current_records: list[dict] | None = None) -> dict:
    # Current eligible source spellings constrain composition BEFORE cached
    # resource access. The caller owns source lifecycle/epoch fencing.
    query = external_query_formula(formula, current_records=current_records)
    if query is None:
        return _base(formula, "not_applicable", "composition_requires_resolution")
    semaphore = _workers
    await semaphore.acquire()
    try:
        work = asyncio.create_task(asyncio.to_thread(_query_snapshot, formula, query))
    except BaseException:
        semaphore.release()
        raise
    _worker_tasks.add(work)

    def completed(finished):
        _worker_tasks.discard(finished)
        semaphore.release()
        if not finished.cancelled():
            finished.exception()

    # Caller cancellation never cancels the CPU task or releases its permit.
    work.add_done_callback(completed)
    return await asyncio.shield(work)
