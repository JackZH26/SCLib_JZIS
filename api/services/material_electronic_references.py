"""Electronic band-gap references from the documented NOMAD index quantities."""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

VERSION = "nomad-electronic-references/1.0.0"
SCOPE = "task_electronic_band_gaps_not_superconducting_gaps"
SCHEMA_URL = "https://github.com/FAIRmat-NFDI/nomad/blob/2b16820bdf83f57437c906addae3faf955ca4acf/nomad/datamodel/metainfo/simulation/calculation.py#L794-L820"
JOULES_PER_EV = Decimal("1.602176634e-19")
KINDS = ("band_structure_electronic", "dos_electronic")
FIELDS = tuple(f"results.properties.electronic.{kind}.{leaf}" for kind in KINDS
               for leaf in ("band_gap.value", "band_gap.index", "band_gap.type", "spin_polarized"))


def _reading(kind: str, group_index: int, spin: Any, gap: Any) -> dict | None:
    if type(gap) is not dict or spin is not None and type(spin) is not bool:
        return None
    value, channel, gap_type = gap.get("value"), gap.get("index"), gap.get("type")
    if (type(value) not in (int, float) or value < 0
            or channel is not None and (type(channel) is not int or not 0 <= channel <= 255)
            or gap_type is not None and gap_type not in ("direct", "indirect")):
        return None
    try:
        ev = float(Decimal(str(value)) / JOULES_PER_EV)
        if not math.isfinite(value) or not math.isfinite(ev):
            return None
    except (ValueError, OverflowError):
        return None
    return {"source_kind": kind, "group_index": group_index, "spin_channel_index": channel,
            "spin_polarized": spin, "gap_type": gap_type, "value_j": value, "value_ev": ev}


def project_electronic_references(electronic: Any) -> dict:
    report = {"version": VERSION, "scope": SCOPE, "unit_schema_url": SCHEMA_URL,
              "status": "not_supplied", "band_gaps": []}
    if electronic is None:
        return report
    if type(electronic) is not dict:
        return {**report, "status": "requires_review"}
    readings = []
    for kind in KINDS:
        groups = electronic.get(kind)
        if groups is None:
            continue
        # Operational bounds: an oversized supplied field requires inspection,
        # not a scientific rejection or silently truncated channel selection.
        if type(groups) is not list or len(groups) > 4:
            return {**report, "status": "requires_review"}
        for group_index, group in enumerate(groups):
            if type(group) is not dict:
                return {**report, "status": "requires_review"}
            gaps = group.get("band_gap")
            if gaps is None:
                continue
            if type(gaps) is not list or len(gaps) > 2:
                return {**report, "status": "requires_review"}
            for gap in gaps:
                reading = _reading(kind, group_index, group.get("spin_polarized"), gap)
                if reading is None:
                    return {**report, "status": "requires_review"}
                readings.append(reading)
    return {**report, "status": "reported" if readings else "not_supplied", "band_gaps": readings}


def valid_electronic_references(value: Any) -> bool:
    if (type(value) is not dict or set(value) != {"version", "scope", "unit_schema_url", "status", "band_gaps"}
            or value.get("version") != VERSION or value.get("scope") != SCOPE
            or value.get("unit_schema_url") != SCHEMA_URL
            or value.get("status") not in ("reported", "not_supplied", "requires_review")
            or type(value.get("band_gaps")) is not list or len(value["band_gaps"]) > 16):
        return False
    rows = value["band_gaps"]
    if value["status"] != "reported":
        return not rows
    if not rows:
        return False
    groups = {}
    for row in rows:
        if (type(row) is not dict or row.get("source_kind") not in KINDS
                or type(row.get("group_index")) is not int or not 0 <= row["group_index"] < 4):
            return False
        restored = _reading(row["source_kind"], row["group_index"], row.get("spin_polarized"),
                            {"value": row.get("value_j"), "index": row.get("spin_channel_index"), "type": row.get("gap_type")})
        if restored is None or set(row) != set(restored) or type(row.get("value_ev")) not in (int, float) or row != restored:
            return False
        key = (row["source_kind"], row["group_index"])
        groups[key] = groups.get(key, 0) + 1
        if groups[key] > 2:
            return False
    return True
