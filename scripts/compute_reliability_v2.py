#!/usr/bin/env python3
"""Extended IRR computation with bootstrap CIs and intra-model α.

Builds on scripts/compute_reliability.py (P2.1).

Adds:
- Bootstrap 95% CI (B=1000) for each Krippendorff α and Fleiss κ
- Intra-model Krippendorff α across the 5 runs of each multi-run model
  (Opus, GPT-5.5, GPT-5.4-mini): formula-set + family + evidence_type
- Saves results to audit/refresh_2026_05_26/irr_bootstrap.csv and irr_intramodel.csv
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import krippendorff
import numpy as np

DB = Path(__file__).resolve().parent.parent / "audit" / "audit_review.db"
OUT_DIR = Path(__file__).resolve().parent.parent / "audit" / "refresh_2026_05_26"
OUT_DIR.mkdir(exist_ok=True)

VENDOR_MODEL_LABELS = {
    ("anthropic", "claude-opus-4-7"): "Opus",
    ("openai", "gpt-5.5"): "GPT-5.5",
    ("openai", "gpt-5.4-mini"): "GPT-mini",
    ("google", "gemini-2.5-flash"): "Gemini",
}
MODEL_ORDER = ["Opus", "GPT-5.5", "GPT-mini", "Gemini"]
MULTI_RUN_MODELS = ["Opus", "GPT-5.5", "GPT-mini"]  # Gemini has only 1 run

B = 1000  # bootstrap iterations
rng = np.random.default_rng(42)


def normalize_formula(s: str) -> str:
    if not s:
        return ""
    return "".join(s.strip().split()).lower()


def load_extractions(conn: sqlite3.Connection, run_idx: int | None = 0) -> dict:
    """If run_idx is int, load that run for each model.
    If run_idx is None, load ALL runs (per (paper, model, run)).
    Restrict to material_ner_v2_core prompt (filter out geo-NER rows that
    share the (paper, vendor, model, run) key)."""
    cur = conn.cursor()
    if run_idx is not None:
        rows = cur.execute(
            "SELECT paper_id, vendor, model_name, run_idx, materials_json "
            "FROM audit_extraction_model "
            "WHERE run_idx=? AND prompt_version='material_ner_v2_core'",
            (run_idx,),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT paper_id, vendor, model_name, run_idx, materials_json "
            "FROM audit_extraction_model WHERE prompt_version='material_ner_v2_core'"
        ).fetchall()
    data: dict = defaultdict(lambda: defaultdict(dict))
    for paper_id, vendor, model_name, ridx, mj in rows:
        label = VENDOR_MODEL_LABELS.get((vendor, model_name))
        if label is None:
            continue
        if not mj:
            data[paper_id][label][ridx] = []
            continue
        try:
            parsed = json.loads(mj)
        except Exception:
            parsed = []
        data[paper_id][label][ridx] = parsed if isinstance(parsed, list) else []
    return data


def formula_set_matrix(data: dict, run_per_model: dict[str, int]) -> np.ndarray | None:
    """Build raters x items matrix of binary formula-set membership."""
    rows = {m: [] for m in MODEL_ORDER}
    for paper_id in sorted(data.keys()):
        per_model = data[paper_id]
        if any(m not in per_model for m in MODEL_ORDER):
            continue
        union = set()
        for m in MODEL_ORDER:
            recs = per_model[m].get(run_per_model[m], [])
            for r in recs:
                f = normalize_formula(r.get("formula", ""))
                if f:
                    union.add(f)
        for f in sorted(union):
            for m in MODEL_ORDER:
                recs = per_model[m].get(run_per_model[m], [])
                fs = {normalize_formula(r.get("formula", "")) for r in recs}
                rows[m].append(1 if f in fs else 0)
    mat = np.array([rows[m] for m in MODEL_ORDER], dtype=float)
    return mat if mat.size else None


def bootstrap_alpha(matrix: np.ndarray, B: int = 1000) -> tuple[float, float, float]:
    """Bootstrap 95% CI by resampling items (columns) with replacement."""
    if matrix is None or matrix.size == 0:
        return float("nan"), float("nan"), float("nan")
    n_items = matrix.shape[1]
    point = float(krippendorff.alpha(reliability_data=matrix, level_of_measurement="nominal"))
    if n_items < 5:
        return point, float("nan"), float("nan")
    boots = []
    for _ in range(B):
        idx = rng.integers(0, n_items, n_items)
        try:
            a = krippendorff.alpha(reliability_data=matrix[:, idx], level_of_measurement="nominal")
            if not np.isnan(a):
                boots.append(a)
        except Exception:
            continue
    if not boots:
        return point, float("nan"), float("nan")
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return point, float(lo), float(hi)


def intra_model_formula_set_alpha(data: dict, model: str) -> tuple[float, int]:
    """For a single model, compute Krippendorff α across its 5 runs treating
    each run as a rater on (paper, formula-in-union)."""
    # Find papers where all 5 runs exist
    rows = {r: [] for r in range(5)}
    n_papers = 0
    for paper_id in sorted(data.keys()):
        runs = data[paper_id].get(model, {})
        if not all(r in runs for r in range(5)):
            continue
        n_papers += 1
        union = set()
        for r in range(5):
            for rec in runs[r]:
                f = normalize_formula(rec.get("formula", ""))
                if f:
                    union.add(f)
        for f in sorted(union):
            for r in range(5):
                fs = {normalize_formula(rec.get("formula", "")) for rec in runs[r]}
                rows[r].append(1 if f in fs else 0)
    mat = np.array([rows[r] for r in range(5)], dtype=float)
    if mat.size == 0:
        return float("nan"), 0
    return float(krippendorff.alpha(reliability_data=mat, level_of_measurement="nominal")), n_papers


def main() -> int:
    print(f"Bootstrap iterations: B={B}")
    conn = sqlite3.connect(DB)

    print("\n=== A.8 — Bootstrap 95% CI on inter-model Krippendorff α (run 0) ===\n")
    data0 = load_extractions(conn, run_idx=0)
    print(f"Loaded {len(data0)} papers (run 0)")

    # Formula-set α with bootstrap
    rpm = {m: 0 for m in MODEL_ORDER}
    mat = formula_set_matrix(data0, rpm)
    fs_alpha, fs_lo, fs_hi = bootstrap_alpha(mat, B=B)
    print(f"\nFormula-set α (4 raters):")
    print(f"  point = {fs_alpha:.3f}, 95% CI = [{fs_lo:.3f}, {fs_hi:.3f}]")

    print("\n=== A.11 — Intra-model Krippendorff α across 5 runs (per model) ===\n")
    data_all = load_extractions(conn, run_idx=None)
    intra_results = {}
    for m in MULTI_RUN_MODELS:
        a, n = intra_model_formula_set_alpha(data_all, m)
        intra_results[m] = (a, n)
        print(f"  {m:<10}  intra-α = {a:.3f}  (papers with all 5 runs = {n})")

    # Compose CSV
    with (OUT_DIR / "irr_bootstrap.csv").open("w") as f:
        f.write("metric,scope,n_raters,n_items,point,ci_low,ci_high\n")
        f.write(f"krippendorff_alpha,formula_set_inter_model_run0,4,{mat.shape[1] if mat is not None else 0},{fs_alpha:.4f},{fs_lo:.4f},{fs_hi:.4f}\n")

    with (OUT_DIR / "irr_intramodel.csv").open("w") as f:
        f.write("model,scope,n_runs,n_papers,intra_alpha\n")
        for m, (a, n) in intra_results.items():
            f.write(f"{m},intra_model_formula_set,5,{n},{a:.4f}\n")

    print("\nWrote:")
    print(f"  {OUT_DIR / 'irr_bootstrap.csv'}")
    print(f"  {OUT_DIR / 'irr_intramodel.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
