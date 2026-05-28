#!/usr/bin/env python3
"""Compare two corpus-refresh snapshot directories and emit a Markdown diff.

Usage:
    python3 scripts/compare_snapshots.py \\
        --old audit/refresh_2026_05_26 \\
        --new audit/refresh_2026_05_28 \\
        --out audit/SNAPSHOT_DIFF_05_26_to_05_28.md

The diff is structured as:
    * **Headline deltas**       — q0_corpus + q9_watershed + q_evidence_breakdown
                                  (the numbers most likely to need updating in the paper)
    * **Per-query changes**     — one section per q*.csv, showing added/removed/changed
                                  rows and (for numeric columns) absolute and % change
    * **Files only in one side** — missing CSVs (e.g., dropped or newly added queries)

The script is read-only — it never modifies the source CSVs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Per-file key-column definitions
# (everything else in the file is treated as a numeric/value column)
# ---------------------------------------------------------------------------
KEY_COLS: dict[str, list[str]] = {
    # Headline corpus
    "q0_corpus.csv":                 ["metric"],
    "q_evidence_breakdown.csv":      ["evidence_type"],
    # Temporal
    "q1_family_succession.csv":      ["bucket", "rk"],
    "q2_2008_shock.csv":             ["year", "family"],
    "q2b_annual_submissions.csv":    ["year"],
    "q2c_2008_multi_family.csv":     [],   # single-row, all-numeric
    "q12_mean_tc_bucket.csv":        ["bucket"],
    # Tc structure
    "q3_hp_ratio.csv":               ["bucket"],
    "q4_high_tc_records.csv":        ["paper_id", "formula", "tc_kelvin"],
    "q9_watershed.csv":              ["scope"],
    "q10_above100k.csv":             ["family"],
    "q10b_above100k_bins.csv":       ["tc_band"],
    "q10c_material_scarcity.csv":    [],
    "q10d_above100k_temporal.csv":   ["bucket"],
    "q11_tc_histogram.csv":          ["tc_low"],
    "q11b_tc_5k_bins.csv":           ["tc_low"],
    "q11c_family_band_decomp.csv":   ["family"],
    # Geography
    "q5_us_china_all_papers.csv":    ["year"],
    "q5b_us_china_tcgeo.csv":        ["year"],
    "q6_family_leadership.csv":      ["family", "rk"],
    "q7_multi_country.csv":          ["n_countries"],
    "q7b_us_china_joint.csv":        ["bucket"],
    "q15_country_top25.csv":         ["country"],
    # Materials & Pareto
    "q8_pareto.csv":                 ["bucket"],
    "q8b_top_materials.csv":         ["formula"],
    "q8c_powerlaw_raw.csv":          ["papers"],
    "q8d_top25_materials.csv":       ["formula"],
    "q13_rocket_materials.csv":      ["formula"],
    "q14_fulleride_above100k.csv":   ["paper_id", "formula", "tc_kelvin"],
    "q14b_fulleride_papers.csv":     ["paper_id"],
}

# Legacy filenames from older snapshots — map them so a 2026-05-26 → 2026-05-28
# comparison can pair v1 with v2 / current names.
LEGACY_ALIASES: dict[str, list[str]] = {
    "q0_corpus.csv":             ["q0_v2_corpus_stats.csv", "q0_corpus_stats.csv"],
    "q3_hp_ratio.csv":           ["q3_hp_ambient_ratio.csv"],
    "q5_us_china_all_papers.csv": ["q5_v2_us_china_all_papers.csv", "q5_us_china_annual.csv"],
    "q5b_us_china_tcgeo.csv":    ["q5b_v2_us_china_tcgeo.csv"],
    "q6_family_leadership.csv":  ["q6_v2_family_leadership.csv"],
    "q7b_us_china_joint.csv":    ["q7b_v2_us_china_joint.csv"],
    "q9_watershed.csv":          ["q9_v2_watershed_filters.csv", "q9_watershed_filters.csv"],
    "q10_above100k.csv":         ["q10_v2_above100k_families.csv", "q10_above100k_families.csv"],
    "q11_tc_histogram.csv":      ["q11_v2_tc_histogram.csv"],
    "q11b_tc_5k_bins.csv":       ["q11b_v2_tc_5k.csv"],
    "q15_country_top25.csv":     ["q15_v2_country_top25.csv", "q15_country_variants.csv"],
}

HEADLINE_FILES = [
    "q0_corpus.csv",
    "q_evidence_breakdown.csv",
    "q9_watershed.csv",
    "q10_above100k.csv",
    "q15_country_top25.csv",
]


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def find_file(root: Path, canonical: str) -> Optional[Path]:
    """Resolve a canonical filename to a path in `root`, falling back to legacy aliases."""
    p = root / canonical
    if p.exists():
        return p
    for alias in LEGACY_ALIASES.get(canonical, []):
        ap = root / alias
        if ap.exists():
            return ap
    return None


def read_csv_clean(path: Path) -> pd.DataFrame:
    """Read a CSV and drop any '(N rows)' trailer line that psql adds."""
    df = pd.read_csv(path, dtype=object)  # keep dtypes as strings, coerce later
    # Drop trailer rows like "(7 rows)" — they appear as a single non-csv string in col 0
    bad = df.iloc[:, 0].astype(str).str.contains(r"\(\d+ row", regex=True, na=False)
    df = df[~bad].copy()
    # Coerce numeric columns
    for c in df.columns:
        coerced = pd.to_numeric(df[c], errors="coerce")
        # If at least one row is numeric AND no row that started non-null became NaN, treat as numeric
        non_null_orig = df[c].notna().sum()
        non_null_coerced = coerced.notna().sum()
        if non_null_coerced == non_null_orig and non_null_orig > 0:
            df[c] = coerced
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

def df_to_markdown(df: pd.DataFrame) -> str:
    """Render a small DataFrame as a Markdown table (dependency-free)."""
    if df.empty:
        return "_(empty)_"
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |"]
    out.append("|" + "---|" * len(cols))
    for _, row in df.iterrows():
        out.append("| " + " | ".join(fmt_num(row[c]) for c in cols) + " |")
    return "\n".join(out)


def fmt_num(x) -> str:
    if pd.isna(x):
        return "—"
    if isinstance(x, float) and x.is_integer():
        return f"{int(x):,}"
    if isinstance(x, float):
        return f"{x:,.3f}".rstrip("0").rstrip(".")
    if isinstance(x, int):
        return f"{x:,}"
    return str(x)


def pct_change(old, new) -> str:
    if pd.isna(old) or pd.isna(new):
        return ""
    try:
        old_f, new_f = float(old), float(new)
    except (TypeError, ValueError):
        return ""
    if old_f == 0:
        return "—" if new_f == 0 else "(+∞)"
    delta = (new_f - old_f) / old_f * 100
    sign = "+" if delta >= 0 else ""
    return f"({sign}{delta:.2f}%)"


def diff_single_row(name: str, df_old: pd.DataFrame, df_new: pd.DataFrame) -> list[str]:
    """Diff a single-row metric file column-by-column."""
    lines = [f"### `{name}`  (single-row metric)", ""]
    if df_old.empty and df_new.empty:
        lines.append("_both sides empty_")
        return lines
    if df_old.empty:
        lines.append("_left side empty; full new content:_")
        lines.append(df_new.to_markdown(index=False))
        return lines
    if df_new.empty:
        lines.append("_right side empty; full old content:_")
        lines.append(df_old.to_markdown(index=False))
        return lines
    cols = sorted(set(df_old.columns) | set(df_new.columns))
    rows = [["metric", "old", "new", "Δ", "Δ%"]]
    any_change = False
    for c in cols:
        o = df_old[c].iloc[0] if c in df_old.columns and len(df_old) else float("nan")
        n = df_new[c].iloc[0] if c in df_new.columns and len(df_new) else float("nan")
        try:
            d = float(n) - float(o) if not (pd.isna(o) or pd.isna(n)) else float("nan")
            d_str = ("+" if (d >= 0 and not pd.isna(d)) else "") + fmt_num(d)
        except (TypeError, ValueError):
            d_str = ""
        changed = (str(o) != str(n)) and not (pd.isna(o) and pd.isna(n))
        if changed:
            any_change = True
        rows.append([c, fmt_num(o), fmt_num(n), d_str, pct_change(o, n)])
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("|" + "---|" * len(rows[0]))
    for r in rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    if not any_change:
        lines.append("\n_no changes_")
    return lines


def diff_keyed(name: str, df_old: pd.DataFrame, df_new: pd.DataFrame,
               keys: list[str]) -> list[str]:
    """Diff a multi-row file keyed on `keys`."""
    lines = [f"### `{name}`  (keys: {', '.join(keys)})", ""]
    if df_old.empty and df_new.empty:
        lines.append("_both sides empty_")
        return lines
    # Make sure key columns exist
    for k in keys:
        if k not in df_old.columns:
            lines.append(f"_left side missing key column `{k}` — skipping_")
            return lines
        if k not in df_new.columns:
            lines.append(f"_right side missing key column `{k}` — skipping_")
            return lines

    # Cast keys to common dtype for safe merging
    for k in keys:
        if pd.api.types.is_numeric_dtype(df_old[k]) and pd.api.types.is_numeric_dtype(df_new[k]):
            df_old[k] = df_old[k].astype("Int64") if df_old[k].dropna().apply(float).apply(float.is_integer).all() else df_old[k]
            df_new[k] = df_new[k].astype("Int64") if df_new[k].dropna().apply(float).apply(float.is_integer).all() else df_new[k]
        else:
            df_old[k] = df_old[k].astype(str)
            df_new[k] = df_new[k].astype(str)

    value_cols = [c for c in df_old.columns if c not in keys]
    # Some files may have extra columns on the new side; include them
    for c in df_new.columns:
        if c not in keys and c not in value_cols:
            value_cols.append(c)

    merged = df_old.merge(df_new, on=keys, how="outer", suffixes=("_old", "_new"), indicator=True)

    added = merged[merged["_merge"] == "right_only"]
    removed = merged[merged["_merge"] == "left_only"]
    both = merged[merged["_merge"] == "both"]

    # Detect changed rows (NaN==NaN treated as equal; int/float dtype mismatches ignored)
    def _col_diff(s_old: pd.Series, s_new: pd.Series) -> pd.Series:
        a = pd.to_numeric(s_old, errors="coerce")
        b = pd.to_numeric(s_new, errors="coerce")
        # If both columns coerce cleanly (no value lost), compare numerically
        if (a.isna() == s_old.isna()).all() and (b.isna() == s_new.isna()).all():
            return (a != b) & ~(a.isna() & b.isna())
        # Fall back to string comparison
        s1, s2 = s_old.astype(str), s_new.astype(str)
        return (s1 != s2) & ~(s_old.isna() & s_new.isna())

    changed_mask = pd.Series(False, index=both.index)
    for c in value_cols:
        co, cn = f"{c}_old", f"{c}_new"
        if co in both.columns and cn in both.columns:
            changed_mask = changed_mask | _col_diff(both[co], both[cn])
    changed = both[changed_mask]

    if added.empty and removed.empty and changed.empty:
        lines.append("_no changes_")
        return lines

    if not changed.empty:
        lines.append(f"**Changed rows:** {len(changed)}")
        lines.append("")
        header = ["**" + k + "**" for k in keys]
        for c in value_cols:
            header += [f"{c} (old)", f"{c} (new)", "Δ%"]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "---|" * len(header))
        # Sort by largest Δ% on first value col if numeric
        def sort_key(row):
            try:
                co, cn = f"{value_cols[0]}_old", f"{value_cols[0]}_new"
                o = float(row[co]) if co in row.index else 0
                n = float(row[cn]) if cn in row.index else 0
                if o == 0:
                    return abs(n)
                return abs((n - o) / o)
            except (TypeError, ValueError, ZeroDivisionError):
                return 0
        changed_sorted = changed.copy()
        changed_sorted["_sortkey"] = changed_sorted.apply(sort_key, axis=1)
        changed_sorted = changed_sorted.sort_values("_sortkey", ascending=False).head(25)
        for _, row in changed_sorted.iterrows():
            cells = [fmt_num(row[k]) for k in keys]
            for c in value_cols:
                co, cn = f"{c}_old", f"{c}_new"
                o = row.get(co, float("nan"))
                n = row.get(cn, float("nan"))
                cells.append(fmt_num(o))
                cells.append(fmt_num(n))
                cells.append(pct_change(o, n))
            lines.append("| " + " | ".join(cells) + " |")
        if len(changed) > 25:
            lines.append(f"\n_(showing top 25 by magnitude; {len(changed) - 25} more changed rows omitted)_")
        lines.append("")

    if not added.empty:
        lines.append(f"**Added rows (new side only):** {len(added)}")
        cols_to_show = keys + [f"{c}_new" for c in value_cols if f"{c}_new" in added.columns]
        snippet = added[cols_to_show].head(10).rename(
            columns={f"{c}_new": c for c in value_cols})
        lines.append(df_to_markdown(snippet))
        if len(added) > 10:
            lines.append(f"\n_(showing first 10; {len(added) - 10} more)_")
        lines.append("")

    if not removed.empty:
        lines.append(f"**Removed rows (old side only):** {len(removed)}")
        cols_to_show = keys + [f"{c}_old" for c in value_cols if f"{c}_old" in removed.columns]
        snippet = removed[cols_to_show].head(10).rename(
            columns={f"{c}_old": c for c in value_cols})
        lines.append(df_to_markdown(snippet))
        if len(removed) > 10:
            lines.append(f"\n_(showing first 10; {len(removed) - 10} more)_")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def build_diff(old_dir: Path, new_dir: Path) -> str:
    out: list[str] = []
    out.append(f"# Snapshot Diff: {old_dir.name} → {new_dir.name}")
    out.append("")
    out.append(f"Generated by `scripts/compare_snapshots.py`")
    out.append("")

    # ---------- Headline section ----------
    out.append("## Headline deltas")
    out.append("")
    out.append("Numbers most likely to require updating in the paper if you re-issue.")
    out.append("")
    for f in HEADLINE_FILES:
        op = find_file(old_dir, f)
        np_ = find_file(new_dir, f)
        if op is None and np_ is None:
            continue
        if op is None:
            out.append(f"### `{f}` — _missing in old side_")
            out.append("")
            continue
        if np_ is None:
            out.append(f"### `{f}` — _missing in new side_")
            out.append("")
            continue
        df_o = read_csv_clean(op)
        df_n = read_csv_clean(np_)
        keys = KEY_COLS.get(f, [])
        if not keys:
            out.extend(diff_single_row(f, df_o, df_n))
        else:
            out.extend(diff_keyed(f, df_o, df_n, keys))
        out.append("")

    # ---------- Per-query section ----------
    out.append("## Per-query changes (non-headline)")
    out.append("")
    canonical = sorted(KEY_COLS.keys())
    for f in canonical:
        if f in HEADLINE_FILES:
            continue
        op = find_file(old_dir, f)
        np_ = find_file(new_dir, f)
        if op is None and np_ is None:
            continue
        if op is None:
            out.append(f"### `{f}` — _missing in old side_ (likely newly added query)")
            out.append("")
            continue
        if np_ is None:
            out.append(f"### `{f}` — _missing in new side_ (likely dropped query)")
            out.append("")
            continue
        df_o = read_csv_clean(op)
        df_n = read_csv_clean(np_)
        keys = KEY_COLS.get(f, [])
        if not keys:
            out.extend(diff_single_row(f, df_o, df_n))
        else:
            out.extend(diff_keyed(f, df_o, df_n, keys))
        out.append("")

    # ---------- Files only in one side ----------
    old_files = {p.name for p in old_dir.glob("q*.csv")}
    new_files = {p.name for p in new_dir.glob("q*.csv")}
    canonical_set = set(KEY_COLS.keys())
    alias_set = set()
    for v in LEGACY_ALIASES.values():
        alias_set.update(v)
    leftovers_old = old_files - canonical_set - alias_set
    leftovers_new = new_files - canonical_set - alias_set
    if leftovers_old or leftovers_new:
        out.append("## Unrecognised CSV files (no canonical key map)")
        out.append("")
        if leftovers_old:
            out.append("**Only in old side:**")
            for f in sorted(leftovers_old):
                out.append(f"  - `{f}`")
            out.append("")
        if leftovers_new:
            out.append("**Only in new side:**")
            for f in sorted(leftovers_new):
                out.append(f"  - `{f}`")
            out.append("")

    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff two SCLib snapshot directories.")
    ap.add_argument("--old", required=True, type=Path, help="Path to older snapshot dir")
    ap.add_argument("--new", required=True, type=Path, help="Path to newer snapshot dir")
    ap.add_argument("--out", required=True, type=Path, help="Output Markdown report")
    args = ap.parse_args()

    if not args.old.is_dir():
        print(f"[err] --old not a directory: {args.old}", file=sys.stderr)
        return 1
    if not args.new.is_dir():
        print(f"[err] --new not a directory: {args.new}", file=sys.stderr)
        return 1

    md = build_diff(args.old, args.new)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md)
    print(f"Wrote {len(md):,} chars → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
