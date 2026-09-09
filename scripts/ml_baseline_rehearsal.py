#!/usr/bin/env python3
"""Run/replay one fixed synthetic ML engineering rehearsal; no dataset input."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from services.ml_audited_dataset import canonical, digest
from services.ml_baseline_rehearsal import (
    run_synthetic_rehearsal,
    verify_synthetic_rehearsal,
)

from scripts.ml_audited_dataset import (
    OutputStateUnknown,
    read_package,
    write_new_package,
)


def run(*, mode, output_path=None, receipt_path=None, expected_receipt_sha256=None):
    if mode == "build":
        if output_path is None or receipt_path is not None or expected_receipt_sha256 is not None:
            raise ValueError("invalid_rehearsal_paths")
        receipt = run_synthetic_rehearsal()
        gate = receipt["report"]["gate"]["status"]
        if gate not in {"pass", "no_go"}:
            raise ValueError("invalid_rehearsal_gate")
        should_write = gate == "pass"
        if should_write:
            write_new_package(output_path, receipt, forbidden_directory=ROOT)
        return {"version": receipt["version"], "scope": receipt["scope"],
                "technical_gate": gate, "output_written": should_write,
                "receipt_sha256": digest(receipt), "fixture_sha256": receipt["fixture_sha256"],
                "report_sha256": receipt["report_sha256"], **receipt["authority"]}
    if mode == "verify" and output_path is None and receipt_path is not None:
        receipt, signature = read_package(receipt_path, expected_receipt_sha256)
        result = verify_synthetic_rehearsal(receipt, expected_receipt_sha256=expected_receipt_sha256)
        if read_package(receipt_path, expected_receipt_sha256) != (receipt, signature):
            raise ValueError("rehearsal_changed_during_verification")
        return {**result, "output_written": False}
    raise ValueError("invalid_rehearsal_paths")


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid_rehearsal_arguments")


def main(argv=None):
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=["build", "verify"])
    for name in ("output", "receipt", "receipt-sha256"):
        parser.add_argument("--" + name)
    try:
        args = parser.parse_args(argv)
        result = run(mode=args.mode, output_path=args.output, receipt_path=args.receipt,
                     expected_receipt_sha256=args.receipt_sha256)
    except OutputStateUnknown:
        print('{"status":"output_state_unknown","output_written":null}', file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError, OverflowError):
        print('{"status":"invalid","output_written":false}', file=sys.stderr)
        return 2
    print(canonical(result).decode())
    return 0 if result["technical_gate"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
