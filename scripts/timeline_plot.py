#!/usr/bin/env python3
"""Generate publication-quality static Tc-vs-year scatter from v_tc_geo.

Produces drafts/latex/figures/timeline_scatter.pdf (and .png) suitable for
direct inclusion in the LaTeX manuscript via \\includegraphics.

Visual contract (matches https://jzis.org/sclib/timeline):
- x-axis: arXiv submission year (1994-2026)
- y-axis: Tc (K), 0-300 K
- color: material family (17 categories, palette below)
- marker style:
    * filled: experimental or ambiguous primary (treated as exp)
    * open:   theoretical (primary_theoretical)
    * black ring outline: high-pressure (pressure_gpa > 1)

Data source: audit/refresh_2026_05_26/timeline_data.csv
(produced by SQL query against v_tc_geo on 2026-05-27)

Run:
  python3 scripts/timeline_plot.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

REPO = Path(__file__).resolve().parent.parent


def _pick_snapshot_dir() -> Path:
    """Use --snapshot-dir CLI arg if provided, else the most recent audit/refresh_*."""
    for i, arg in enumerate(sys.argv):
        if arg == "--snapshot-dir" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
    candidates = sorted(REPO.glob("audit/refresh_*"))
    return candidates[-1] if candidates else (REPO / "audit" / "refresh_2026_05_26")


SNAPSHOT = _pick_snapshot_dir()
CSV_PATH = SNAPSHOT / "timeline_data.csv"
OUT_PDF = REPO / "drafts" / "latex" / "figures" / "timeline_scatter.pdf"
OUT_PNG = REPO / "drafts" / "latex" / "figures" / "timeline_scatter.png"

# Colour palette modeled on the SCLib web frontend
# (similar hues to the screenshot, optimised for print/colourblind contrast)
FAMILY_COLOR = {
    "cuprate":         "#1f77b4",   # blue (largest population)
    "iron_based":      "#d4a017",   # gold/ochre
    "hydride":         "#d62728",   # red
    "mgb2":            "#2ca02c",   # green
    "nickelate":       "#17becf",   # cyan
    "kagome":          "#08858a",   # teal
    "fulleride":       "#e377c2",   # pink/magenta
    "heavy_fermion":   "#9467bd",   # purple
    "conventional":    "#9e9e9e",   # mid-grey
    "elemental":       "#b8b8b8",   # light grey
    "chalcogenide":    "#7a7a7a",   # dark grey
    "ruthenate":       "#6a4c93",   # darker purple
    "organic":         "#c98a78",   # earthy
    "bismuthate":      "#8c564b",   # brown
    "borocarbide":     "#a0a0a0",   # grey
    "bis2_layered":    "#bcbd22",   # olive
}
FAMILY_LABEL = {
    "cuprate":         "Cuprate",
    "iron_based":      "Iron-based",
    "hydride":         "Hydride",
    "mgb2":            "MgB$_2$",
    "nickelate":       "Nickelate",
    "kagome":          "Kagome",
    "fulleride":       "Fulleride",
    "heavy_fermion":   "Heavy fermion",
    "conventional":    "Conventional",
    "elemental":       "Elemental",
    "chalcogenide":    "Chalcogenide",
    "ruthenate":       "Ruthenate",
    "organic":         "Organic",
    "bismuthate":      "Bismuthate",
    "borocarbide":     "Borocarbide",
    "bis2_layered":    "BiS$_2$-layered",
}
# Plotting order: smaller / less-populated families on top
PLOT_ORDER = [
    "elemental", "conventional", "chalcogenide", "borocarbide",
    "ruthenate", "bismuthate", "organic", "bis2_layered",
    "heavy_fermion", "mgb2",
    "cuprate", "iron_based",
    "fulleride", "kagome", "nickelate",
    "hydride",
]


def main() -> int:
    if not CSV_PATH.exists():
        print(f"Missing data file: {CSV_PATH}", file=sys.stderr)
        print("Run: ssh root@VPS2 to dump v_tc_geo first (see header).",
              file=sys.stderr)
        return 1

    df = pd.read_csv(CSV_PATH)
    # Filter out the "(N rows)" CSV trailer if present
    df = df[df["year"].apply(lambda x: str(x).strip().isdigit())].copy()
    df["year"] = df["year"].astype(int)
    df["tc_kelvin"] = pd.to_numeric(df["tc_kelvin"], errors="coerce")
    df["pressure_gpa"] = pd.to_numeric(df["pressure_gpa"], errors="coerce")
    df = df.dropna(subset=["tc_kelvin"])
    print(f"Loaded {len(df)} records from {CSV_PATH}")

    df["family"] = df["family"].fillna("Other")
    df.loc[~df["family"].isin(FAMILY_COLOR), "family"] = "Other"

    # Evidence and pressure flags
    df["is_theoretical"] = df["evidence_type"] == "primary_theoretical"
    df["is_hp"] = df["pressure_gpa"] > 1

    # Set up figure (LaTeX textwidth ≈ 6.5 in; use 7×3.6 for 16:8 aspect)
    fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=300)
    ax.set_xlim(1994, 2027)
    ax.set_ylim(-5, 305)
    ax.set_xlabel("Year (arXiv submission)", fontsize=10)
    ax.set_ylabel(r"$T_c$ (K)", fontsize=10)
    ax.grid(True, alpha=0.2, linewidth=0.5)
    ax.tick_params(labelsize=9)

    # Slight horizontal jitter to spread out the discrete-year columns
    rng = pd.Series(range(len(df))).map(lambda _: 0)  # placeholder if needed
    import numpy as np
    jitter = np.random.default_rng(42).uniform(-0.35, 0.35, size=len(df))
    df["year_j"] = df["year"].astype(float) + jitter

    # Plot in order: less-populated families first (so bigger ones overlay)
    for fam in PLOT_ORDER:
        sub = df[df["family"] == fam]
        if len(sub) == 0:
            continue
        color = FAMILY_COLOR.get(fam, "#999999")

        # Split into 4 marker styles
        exp_amb     = sub[(~sub["is_theoretical"]) & (~sub["is_hp"])]
        exp_amb_hp  = sub[(~sub["is_theoretical"]) & (sub["is_hp"])]
        theo        = sub[(sub["is_theoretical"]) & (~sub["is_hp"])]
        theo_hp     = sub[(sub["is_theoretical"]) & (sub["is_hp"])]

        # Experimental / ambiguous primary, ambient pressure: filled, no ring
        ax.scatter(exp_amb["year_j"], exp_amb["tc_kelvin"],
                   s=6, c=color, alpha=0.55,
                   edgecolors="none", linewidths=0, marker="o")
        # Experimental / ambiguous, high pressure: filled + black ring
        ax.scatter(exp_amb_hp["year_j"], exp_amb_hp["tc_kelvin"],
                   s=10, c=color, alpha=0.75,
                   edgecolors="black", linewidths=0.55, marker="o")
        # Theoretical, ambient: hollow (white fill + colour ring)
        ax.scatter(theo["year_j"], theo["tc_kelvin"],
                   s=10, facecolors="none", edgecolors=color,
                   alpha=0.85, linewidths=0.7, marker="o")
        # Theoretical, high pressure: hollow with black ring + colour fill ring
        ax.scatter(theo_hp["year_j"], theo_hp["tc_kelvin"],
                   s=14, facecolors="none", edgecolors=color,
                   alpha=0.95, linewidths=0.7, marker="o")
        # Overlay a smaller black ring on the HP-theoretical (visual cue)
        ax.scatter(theo_hp["year_j"], theo_hp["tc_kelvin"],
                   s=22, facecolors="none", edgecolors="black",
                   alpha=0.6, linewidths=0.4, marker="o")

    # Annotate landmark features for the reader
    # 100 K watershed line
    ax.axhline(100, color="black", linewidth=0.4, linestyle=":", alpha=0.6)
    ax.text(1994.5, 102, "100 K watershed", fontsize=7.5,
            style="italic", color="#444")

    # 50-80 K valley shading
    ax.axhspan(50, 80, color="black", alpha=0.045, zorder=0)
    ax.text(1994.5, 65, "50–80 K\ndensity valley", fontsize=7.5,
            style="italic", color="#444", va="center")

    # 2008 iron-based shock annotation
    ax.axvline(2008, color="#d4a017", linewidth=0.5, linestyle="--",
               alpha=0.6)
    ax.text(2008, 285, "2008", fontsize=7.5, color="#a07a10",
            ha="center", style="italic")

    # ---------- Legend ----------
    # Family legend (only families present in the data, in a sensible order)
    family_order_legend = [
        "cuprate", "iron_based", "hydride", "mgb2",
        "nickelate", "kagome", "heavy_fermion", "fulleride",
        "conventional", "elemental", "chalcogenide", "ruthenate",
        "organic", "bismuthate", "borocarbide", "bis2_layered",
    ]
    family_handles = [
        Patch(facecolor=FAMILY_COLOR[f], label=FAMILY_LABEL[f],
              edgecolor="none")
        for f in family_order_legend if f in df["family"].unique()
    ]
    leg1 = ax.legend(handles=family_handles, loc="lower center",
                     bbox_to_anchor=(0.5, -0.32),
                     ncol=8, fontsize=7.5, frameon=False,
                     handlelength=1.0, columnspacing=1.0)
    ax.add_artist(leg1)

    # Marker-style legend (top right)
    style_handles = [
        Line2D([], [], marker="o", linestyle="none", markersize=4.5,
               markerfacecolor="#444", markeredgecolor="#444",
               label="experimental"),
        Line2D([], [], marker="o", linestyle="none", markersize=5,
               markerfacecolor="none", markeredgecolor="#d62728",
               markeredgewidth=0.9, label="theoretical (DFT)"),
        Line2D([], [], marker="o", linestyle="none", markersize=5,
               markerfacecolor="#1f77b4", markeredgecolor="black",
               markeredgewidth=0.7, label="high-pressure"),
    ]
    leg2 = ax.legend(handles=style_handles, loc="upper right",
                     fontsize=7.5, frameon=True, framealpha=0.92,
                     edgecolor="#bbbbbb")

    # Title (small, top-left, in italic) — snapshot date pulled from SNAPSHOT dir name
    snapshot_label = SNAPSHOT.name.replace("refresh_", "").replace("_", "-")
    ax.set_title(
        f"All $T_c$ records in the SCLib corpus ($n$ = {len(df):,}), "
        f"{snapshot_label} snapshot",
        fontsize=9, loc="left", style="italic", color="#222",
        pad=4,
    )

    fig.tight_layout(rect=[0, 0.06, 1, 1])

    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PDF, dpi=300, bbox_inches="tight")
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    print(f"Saved:")
    print(f"  {OUT_PDF}")
    print(f"  {OUT_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
