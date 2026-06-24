#!/usr/bin/env python3
"""Build per-year APS Harvest-ready manifests from existing yearly JSONL.

This script reads files like:

  /opt/sclib_aps_manifests/yearly/aps_2024.jsonl

and writes:

  /opt/sclib_aps_manifests/yearly/aps_2024_harvest_ready.jsonl
  /opt/sclib_aps_manifests/yearly/aps_2024_harvest_ready.txt
  /opt/sclib_aps_manifests/reports/aps_2024_harvest_ready_excluded.csv

The filtering logic is shared with `build_aps_superconductivity_manifest.py`
so the yearly batch runner uses the same Harvest-ready definition as the
master manifest builder.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
from pathlib import Path
from typing import Any


YEAR_RE = re.compile(r"aps_(\d{4})\.jsonl$")


def _load_manifest_helpers() -> Any:
    here = Path(__file__).resolve().parent
    target = here / "build_aps_superconductivity_manifest.py"
    spec = importlib.util.spec_from_file_location("build_aps_manifest", target)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load manifest helper: {target}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MANIFEST_HELPERS = _load_manifest_helpers()


def iter_year_files(yearly_dir: Path) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for path in yearly_dir.glob("aps_*.jsonl"):
        m = YEAR_RE.fullmatch(path.name)
        if not m:
            continue
        out.append((int(m.group(1)), path))
    return sorted(out)


def classify_reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "excluded_journal": sum(
            1
            for row in rows
            if str(row.get("excluded_reason", "")).startswith("excluded_journal:")
        ),
        "excluded_doi_prefix": sum(
            1
            for row in rows
            if str(row.get("excluded_reason", "")).startswith("excluded_doi_prefix:")
        ),
        "missing_volume": sum(1 for row in rows if row.get("excluded_reason") == "missing_volume"),
        "missing_issue": sum(1 for row in rows if row.get("excluded_reason") == "missing_issue"),
        "missing_locator": sum(
            1 for row in rows if row.get("excluded_reason") == "missing_locator"
        ),
    }


def process_year(src: Path, reports_dir: Path, *, force: bool) -> dict[str, Any]:
    m = YEAR_RE.fullmatch(src.name)
    if not m:
        raise ValueError(f"unexpected source file name: {src}")
    year = int(m.group(1))
    kept_jsonl = src.with_name(f"aps_{year}_harvest_ready.jsonl")
    kept_txt = src.with_name(f"aps_{year}_harvest_ready.txt")
    dropped_csv = reports_dir / f"aps_{year}_harvest_ready_excluded.csv"

    if not force and kept_jsonl.exists() and kept_txt.exists() and dropped_csv.exists():
        rows = sum(1 for line in kept_jsonl.read_text(encoding="utf-8").splitlines() if line.strip())
        return {"year": year, "status": "skipped_existing", "kept": rows}

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        reason = MANIFEST_HELPERS.harvest_filter_reason(  # type: ignore[attr-defined]
            {
                "doi": row.get("doi"),
                "year": row.get("year"),
                "published_date": row.get("published_date"),
                "volume": row.get("volume"),
                "issue": row.get("issue"),
                "article-number": row.get("article_number"),
                "page": row.get("page"),
            },
            row.get("journal_abbrev"),
        )
        if reason:
            row["excluded_reason"] = reason
            dropped.append(row)
        else:
            kept.append(row)

    kept_jsonl.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in kept),
        encoding="utf-8",
    )
    kept_txt.write_text("\n".join(row["doi"] for row in kept) + "\n", encoding="utf-8")

    with dropped_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "doi",
                "journal_abbrev",
                "published_date",
                "volume",
                "issue",
                "article_number",
                "page",
                "excluded_reason",
                "title",
            ],
        )
        writer.writeheader()
        for row in dropped:
            writer.writerow({k: row.get(k) for k in writer.fieldnames})

    counts = classify_reason_counts(dropped)
    return {
        "year": year,
        "status": "written",
        "input": len(kept) + len(dropped),
        "kept": len(kept),
        "dropped": len(dropped),
        **counts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yearly-dir",
        type=Path,
        required=True,
        help="Directory containing aps_<year>.jsonl files",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        required=True,
        help="Directory to write aps_<year>_harvest_ready_excluded.csv reports",
    )
    parser.add_argument(
        "--years",
        nargs="*",
        type=int,
        help="Optional explicit year list. Default: every aps_<year>.jsonl found.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite outputs even if harvest_ready files already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.reports_dir.mkdir(parents=True, exist_ok=True)

    year_files = iter_year_files(args.yearly_dir)
    if args.years:
        wanted = set(args.years)
        year_files = [(year, path) for year, path in year_files if year in wanted]
    if not year_files:
        raise SystemExit("no aps_<year>.jsonl files found to process")

    summary_rows = [
        [
            "year",
            "status",
            "input_count",
            "kept_count",
            "dropped_count",
            "dropped_excluded_journal",
            "dropped_excluded_doi_prefix",
            "dropped_missing_volume",
            "dropped_missing_issue",
            "dropped_missing_locator",
        ]
    ]
    for year, src in year_files:
        result = process_year(src, args.reports_dir, force=args.force)
        print(json.dumps(result, ensure_ascii=False))
        summary_rows.append(
            [
                year,
                result.get("status"),
                result.get("input", ""),
                result.get("kept", ""),
                result.get("dropped", ""),
                result.get("excluded_journal", ""),
                result.get("excluded_doi_prefix", ""),
                result.get("missing_volume", ""),
                result.get("missing_issue", ""),
                result.get("missing_locator", ""),
            ]
        )

    summary = args.reports_dir / "harvest_ready_manifest_summary_all_years.csv"
    with summary.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(summary_rows)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
