"""Offline ML08 preparation/review accounting; not scientific approval.

Compatibility entry point. Scientific/schema validation lives in the API-packaged
services.ml_pilot_accounting module so CLI and server use the same contract.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from services.ml_pilot_accounting import (  # noqa: F401 -- compatibility exports
    FIELDS,
    MAX_BYTES,
    MAX_REVIEWS,
    SCHEMA_PATH,
    WARNINGS,
    _date,
    _finite_number,
    _loads,
    _pairs,
    _quantity_valid,
    _result_errors,
    _schema_errors,
    canonical,
    review_hash,
    selection_hash,
    validate,
)
from services.ml_pilot_documents import json_value, review_records


def _read(path: Path) -> str:
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("input_exceeds_operational_size_limit")
    return data.decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    parser.add_argument("reviews", type=Path, nargs="?")
    parser.add_argument("--conclusion", type=Path)
    parser.add_argument("--expected-selection-sha256")
    parser.add_argument("--print-selection-hash", action="store_true")
    parser.add_argument("--require", choices=["ready", "final"], help="Exit 2 when the requested documentary gate is incomplete")
    args = parser.parse_args()
    try:
        selection = json_value(_read(args.selection).encode("utf-8"))
        if args.print_selection_hash:
            if not isinstance(selection, dict):
                raise ValueError("selection_object_required")
            print(selection_hash(selection))
            return 0
        review_text = _read(args.reviews) if args.reviews else ""
        reviews = review_records(review_text.encode("utf-8"))
        conclusion = json_value(_read(args.conclusion).encode("utf-8")) if args.conclusion else None
        report = validate(selection, reviews, conclusion, args.expected_selection_sha256)
    except (ValueError, OSError, UnicodeError, RecursionError, OverflowError, TypeError):
        print(json.dumps({"status": "invalid", "scientific_acceptance": False, "errors": ["input_unreadable_or_invalid_json"]}))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    if report["errors"]:
        return 1
    if args.require and not report["ready_for_review" if args.require == "ready" else "ready_for_final_human_signoff"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
