#!/usr/bin/env python3
"""Stratification table for the 100-paper golden set (Reviewer 1 M6).

For each paper in audit_sample we need year, dominant_family, and pressure
regime (ambient vs HP). Strata × per-pair Jaccard within stratum.

Data sources:
- audit/audit_review.db .audit_sample (paper_id list)
- For each paper_id, query VPS2 v_tc_geo to get year + family + pressure of
  the records associated with that paper.

Output: audit/refresh_2026_05_26/golden_set_stratification.csv
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "audit" / "audit_review.db"
OUT = Path(__file__).resolve().parent.parent / "audit" / "refresh_2026_05_26"
OUT.mkdir(exist_ok=True)


def get_golden_paper_ids() -> list[str]:
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT paper_id FROM audit_sample ORDER BY paper_id").fetchall()
    return [r[0] for r in rows]


def query_vps2_attributes(paper_ids: list[str]) -> dict[str, dict]:
    """Use ssh + docker exec to query v_tc_geo for the given paper_ids."""
    # Build IN-list (paper_ids are arxiv IDs like 'arxiv:cond-mat/0xxxxxx')
    sql_in = ",".join([f"'{pid}'" for pid in paper_ids])
    sql = f"""
    SELECT paper_id,
           min(year) AS year,
           mode() WITHIN GROUP (ORDER BY family) AS dominant_family,
           bool_or(pressure_gpa>1) AS has_hp,
           count(*) AS n_records,
           round(avg(tc_kelvin)::numeric, 1) AS mean_tc
    FROM v_tc_geo
    WHERE paper_id IN ({sql_in})
    GROUP BY paper_id
    """
    cmd = [
        "ssh", "-i", str(Path.home() / ".ssh/id_ed25519"), "root@72.62.251.29",
        "set -e; docker exec -i sclib-postgres psql -U sclib -d sclib --csv -A -F$'\\t' -c \"" + sql + "\"",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        print("SSH error:", r.stderr, file=sys.stderr)
        return {}
    out = {}
    for line in r.stdout.strip().splitlines()[1:]:  # skip header
        if not line.strip() or "(" in line:
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        pid, year, family, has_hp, n_recs, mean_tc = parts
        out[pid] = {
            "year": int(year) if year else None,
            "family": family or "unknown",
            "has_hp": has_hp == "t",
            "n_records": int(n_recs) if n_recs else 0,
            "mean_tc": float(mean_tc) if mean_tc else 0.0,
        }
    return out


def main() -> int:
    pids = get_golden_paper_ids()
    print(f"Golden set has {len(pids)} papers")
    if not pids:
        print("No papers in audit_sample.", file=sys.stderr)
        return 1

    attrs = query_vps2_attributes(pids)
    print(f"Got VPS2 attributes for {len(attrs)} papers (of {len(pids)})")

    # Strata definitions
    def year_bucket(y: int | None) -> str:
        if y is None:
            return "unknown"
        if y < 2005:
            return "1995-2004"
        if y < 2010:
            return "2005-2009"
        if y < 2015:
            return "2010-2014"
        if y < 2020:
            return "2015-2019"
        return "2020-2026"

    def pressure_bucket(has_hp: bool) -> str:
        return "HP" if has_hp else "ambient"

    by_year = Counter()
    by_family = Counter()
    by_pressure = Counter()
    cross_year_family = defaultdict(Counter)

    for pid in pids:
        a = attrs.get(pid, {})
        yb = year_bucket(a.get("year"))
        fam = a.get("family") or "unknown"
        pb = pressure_bucket(a.get("has_hp", False))
        by_year[yb] += 1
        by_family[fam] += 1
        by_pressure[pb] += 1
        cross_year_family[yb][fam] += 1

    # Write stratification table
    with (OUT / "golden_set_stratification.csv").open("w") as f:
        f.write("dimension,stratum,n_papers\n")
        for k, v in sorted(by_year.items()):
            f.write(f"year,{k},{v}\n")
        for k, v in sorted(by_family.items(), key=lambda kv: -kv[1]):
            f.write(f"family,{k},{v}\n")
        for k, v in sorted(by_pressure.items()):
            f.write(f"pressure,{k},{v}\n")

    # Print summary
    print("\n=== Golden-set 100-paper stratification ===\n")
    print("By year bucket:")
    for k, v in sorted(by_year.items()):
        print(f"  {k:>12}  {v}")
    print("\nBy dominant family (top 8):")
    for k, v in sorted(by_family.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {k:>15}  {v}")
    print("\nBy pressure regime:")
    for k, v in sorted(by_pressure.items()):
        print(f"  {k:>10}  {v}")

    print("\nCross-tabulation (year × family, top families):")
    top_fams = [k for k, _ in sorted(by_family.items(), key=lambda kv: -kv[1])[:5]]
    print("  ", "year_bucket".ljust(13), end="")
    for f in top_fams:
        print(f"{f:>15}", end="")
    print()
    for yb in sorted(cross_year_family.keys()):
        print("  ", yb.ljust(13), end="")
        for f in top_fams:
            print(f"{cross_year_family[yb].get(f, 0):>15}", end="")
        print()

    print(f"\nWrote {OUT/'golden_set_stratification.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
