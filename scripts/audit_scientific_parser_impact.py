"""Read local material JSONL and print a parser-impact manifest to stdout.

No database, cloud or model calls; no input rewrite or automatic backfill.
The manifest is an audit proposal, not approval of parsed science. A numeric
legacy value without preserved raw evidence is explicitly source-unverifiable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))

from ingestion.extract.formula_enrichment import (
    PARSER_VERSION as COMPOSITION_VERSION,
)
from ingestion.extract.formula_enrichment import (
    enrich_material_composition,
)
from ingestion.extract.scientific_values import (
    FIELD_UNITS,
    PARSER_VERSION,
    json_safe_raw,
    legacy_scalar,
    record_quantity,
)


def build_impact_report(materials: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for material in materials:
        composition = enrich_material_composition(material)
        cached = material.get("composition_data")
        expected_cache = {
            k: v for k, v in composition.items() if k != "composition_status"
        }
        cache_current = (
            isinstance(cached, Mapping)
            and dict(cached) == expected_cache
            and material.get("composition_status") == composition["composition_status"]
        )
        quantities = []
        records = material.get("records") or []
        if isinstance(records, str):
            records = json.loads(records)
        if not isinstance(records, list):
            raise TypeError("material.records must be a list")
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                continue
            supplied = record.get("scientific_values")
            for field in FIELD_UNITS:
                if field not in record and not (
                    isinstance(supplied, Mapping) and field in supplied
                ):
                    continue
                proposed = record_quantity(record, field)
                preserved = (
                    isinstance(supplied, Mapping)
                    and isinstance(supplied.get(field), Mapping)
                    and "raw_value" in supplied[field]
                )
                ambiguous_legacy = (
                    not preserved
                    and isinstance(record.get(field), (int, float))
                    and not isinstance(record.get(field), bool)
                )
                quantities.append(
                    {
                        "record_index": index,
                        "field": field,
                        "old_scalar": json_safe_raw(record.get(field)),
                        "proposed_scalar": legacy_scalar(proposed),
                        "proposed_relation": proposed["relation"],
                        "proposal": proposed,
                        "requires_source_recheck": ambiguous_legacy
                        or proposed["status"] == "invalid",
                        "reason": "legacy_raw_unit_and_relation_unverifiable"
                        if ambiguous_legacy
                        else "parse_failure"
                        if proposed["status"] == "invalid"
                        else None,
                    }
                )
        rows.append(
            {
                "material_id": str(material.get("id") or ""),
                "old_composition_parser_version": cached.get("parser_version")
                if isinstance(cached, Mapping)
                else None,
                "composition_cache_current": cache_current,
                "invalidate_cached_features": cached is not None and not cache_current,
                "proposed_composition": composition,
                "quantities": quantities,
            }
        )
    rows.sort(key=lambda row: row["material_id"])
    manifest = {
        "schema": "sclib-scientific-parser-impact/v1",
        "mode": "offline_dry_run",
        "scientific_parser_version": PARSER_VERSION,
        "composition_parser_version": COMPOSITION_VERSION,
        "materials": rows,
        "limitations": [
            "No raw source information can be recovered from a previously stripped number.",
            "Successful parsing is not scientific review or permission for ML release.",
        ],
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            manifest, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("materials_jsonl", type=Path)
    args = parser.parse_args()
    with args.materials_jsonl.open(encoding="utf-8") as source:
        materials = [json.loads(line) for line in source if line.strip()]
    if not all(isinstance(row, dict) for row in materials):
        parser.error("Every JSONL row must be an object")
    print(
        json.dumps(
            build_impact_report(materials),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
