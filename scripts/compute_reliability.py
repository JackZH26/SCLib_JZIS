#!/usr/bin/env python3
"""Compute inter-rater reliability statistics for the multi-model audit.

Outputs:
- Krippendorff α on formula-set membership (binary, 4 raters)
- Krippendorff α on family classification (categorical, multi-rater)
- Krippendorff α on evidence_type (categorical, multi-rater)
- Cohen κ pairwise on family (over formula-overlap subset)
- Fleiss κ on family classification (over formula-overlap subset)

Source: audit/audit_review.db, table audit_extraction_model (3,200 rows).
For each model, use run_idx=0 as the canonical extraction (matching the
single-shot production methodology). Multi-run intra-model variance is
reported separately.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import krippendorff
import numpy as np
from sklearn.metrics import cohen_kappa_score
from statsmodels.stats.inter_rater import fleiss_kappa

DB = Path(__file__).resolve().parent.parent / "audit" / "audit_review.db"
OUT_DIR = Path(__file__).resolve().parent.parent / "audit" / "refresh_2026_05_26"

VENDOR_MODEL_LABELS = {
    ("anthropic", "claude-opus-4-7"): "Opus",
    ("openai", "gpt-5.5"): "GPT-5.5",
    ("openai", "gpt-5.4-mini"): "GPT-mini",
    ("google", "gemini-2.5-flash"): "Gemini",
}
MODEL_ORDER = ["Opus", "GPT-5.5", "GPT-mini", "Gemini"]


def normalize_formula(s: str) -> str:
    """Light formula normalization for matching across vendors."""
    if not s:
        return ""
    s = s.strip()
    s = s.replace("·", ".").replace("·", ".")
    s = "".join(s.split())
    return s.lower()


def load_run0_extractions(conn: sqlite3.Connection) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Load run_idx=0 material extractions, keyed by paper_id -> model_label -> list[dict]."""
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT paper_id, vendor, model_name, materials_json
        FROM audit_extraction_model
        WHERE run_idx = 0
        ORDER BY paper_id
        """
    ).fetchall()

    data: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for paper_id, vendor, model_name, materials_json in rows:
        label = VENDOR_MODEL_LABELS.get((vendor, model_name))
        if label is None:
            continue
        if not materials_json:
            data[paper_id][label] = []
            continue
        try:
            parsed = json.loads(materials_json)
        except json.JSONDecodeError:
            data[paper_id][label] = []
            continue
        if not isinstance(parsed, list):
            parsed = []
        data[paper_id][label] = parsed
    return data


# ---------------------------------------------------------------------------
# 1. Formula-set membership: Krippendorff α on binary "extracted F?" ratings
# ---------------------------------------------------------------------------


def alpha_formula_set(data: dict) -> float:
    """For each (paper, formula-in-union), each rater gives 0/1.
    Build the matrix and feed to Krippendorff nominal α.
    """
    rows_per_rater: dict[str, list[int]] = {m: [] for m in MODEL_ORDER}
    for paper_id in sorted(data.keys()):
        per_model = data[paper_id]
        if any(m not in per_model for m in MODEL_ORDER):
            continue
        # Union of formulas extracted by any of the four models
        union = set()
        for m in MODEL_ORDER:
            for rec in per_model[m]:
                f = normalize_formula(rec.get("formula", ""))
                if f:
                    union.add(f)
        for f in sorted(union):
            for m in MODEL_ORDER:
                extracted_by_m = {
                    normalize_formula(rec.get("formula", "")) for rec in per_model[m]
                }
                rows_per_rater[m].append(1 if f in extracted_by_m else 0)

    matrix = np.array([rows_per_rater[m] for m in MODEL_ORDER], dtype=float)
    if matrix.size == 0:
        return float("nan")
    return float(krippendorff.alpha(reliability_data=matrix, level_of_measurement="nominal"))


# ---------------------------------------------------------------------------
# 2. Family classification: Krippendorff α + Fleiss κ on formula-overlap subset
# ---------------------------------------------------------------------------


def family_agreement(data: dict) -> dict:
    """Over the (paper, formula) subset where ≥2 models extracted the formula,
    compute Krippendorff α and Fleiss κ on family classification.
    """
    paper_formula_labels: list[dict[str, str]] = []
    for paper_id in sorted(data.keys()):
        per_model = data[paper_id]
        if any(m not in per_model for m in MODEL_ORDER):
            continue

        formula_labels_by_model: dict[str, dict[str, str]] = {}
        for m in MODEL_ORDER:
            formula_labels_by_model[m] = {}
            for rec in per_model[m]:
                f = normalize_formula(rec.get("formula", ""))
                if not f:
                    continue
                family = (rec.get("family") or "").strip().lower() or "unknown"
                formula_labels_by_model[m][f] = family

        all_formulas = set()
        for fl in formula_labels_by_model.values():
            all_formulas.update(fl.keys())

        for f in all_formulas:
            n_models_with_f = sum(1 for m in MODEL_ORDER if f in formula_labels_by_model[m])
            if n_models_with_f < 2:
                continue
            entry = {}
            for m in MODEL_ORDER:
                entry[m] = formula_labels_by_model[m].get(f, "__missing__")
            paper_formula_labels.append(entry)

    if not paper_formula_labels:
        return {"alpha": float("nan"), "fleiss_kappa": float("nan"), "n": 0}

    # All categories present
    categories = sorted(
        {entry[m] for entry in paper_formula_labels for m in MODEL_ORDER if entry[m] != "__missing__"}
    )
    cat_idx = {c: i for i, c in enumerate(categories)}

    # Krippendorff: missing values allowed as np.nan
    matrix_raters_x_items = []
    for m in MODEL_ORDER:
        row = []
        for entry in paper_formula_labels:
            v = entry[m]
            row.append(np.nan if v == "__missing__" else cat_idx[v])
        matrix_raters_x_items.append(row)
    alpha = float(
        krippendorff.alpha(
            reliability_data=np.array(matrix_raters_x_items, dtype=float),
            level_of_measurement="nominal",
        )
    )

    # Fleiss κ: restrict to items where all 4 models labeled the formula
    fully_labeled = [e for e in paper_formula_labels if all(e[m] != "__missing__" for m in MODEL_ORDER)]
    if fully_labeled:
        n_items = len(fully_labeled)
        n_cat = len(categories)
        counts = np.zeros((n_items, n_cat), dtype=int)
        for i, entry in enumerate(fully_labeled):
            for m in MODEL_ORDER:
                counts[i, cat_idx[entry[m]]] += 1
        fk = float(fleiss_kappa(counts))
    else:
        fk = float("nan")

    return {"alpha": alpha, "fleiss_kappa": fk, "n_pairs": len(paper_formula_labels), "n_fully_labeled": len(fully_labeled)}


# ---------------------------------------------------------------------------
# 3. Evidence-type: Krippendorff α
# ---------------------------------------------------------------------------


def evidence_agreement(data: dict) -> dict:
    """Over (paper, formula) subset where ≥2 models extracted the formula,
    compute Krippendorff α on evidence_type.
    """
    paper_formula_labels: list[dict[str, str]] = []
    for paper_id in sorted(data.keys()):
        per_model = data[paper_id]
        if any(m not in per_model for m in MODEL_ORDER):
            continue
        formula_labels_by_model: dict[str, dict[str, str]] = {}
        for m in MODEL_ORDER:
            formula_labels_by_model[m] = {}
            for rec in per_model[m]:
                f = normalize_formula(rec.get("formula", ""))
                if not f:
                    continue
                ev = (rec.get("evidence_type") or "").strip().lower() or "unknown"
                formula_labels_by_model[m][f] = ev

        all_formulas = set()
        for fl in formula_labels_by_model.values():
            all_formulas.update(fl.keys())

        for f in all_formulas:
            n_models_with_f = sum(1 for m in MODEL_ORDER if f in formula_labels_by_model[m])
            if n_models_with_f < 2:
                continue
            entry = {}
            for m in MODEL_ORDER:
                entry[m] = formula_labels_by_model[m].get(f, "__missing__")
            paper_formula_labels.append(entry)

    if not paper_formula_labels:
        return {"alpha": float("nan"), "n": 0}

    categories = sorted(
        {entry[m] for entry in paper_formula_labels for m in MODEL_ORDER if entry[m] != "__missing__"}
    )
    cat_idx = {c: i for i, c in enumerate(categories)}
    matrix_raters_x_items = []
    for m in MODEL_ORDER:
        row = []
        for entry in paper_formula_labels:
            v = entry[m]
            row.append(np.nan if v == "__missing__" else cat_idx[v])
        matrix_raters_x_items.append(row)
    alpha = float(
        krippendorff.alpha(
            reliability_data=np.array(matrix_raters_x_items, dtype=float),
            level_of_measurement="nominal",
        )
    )
    return {"alpha": alpha, "n_pairs": len(paper_formula_labels), "categories": categories}


# ---------------------------------------------------------------------------
# 4. Cohen κ pairwise on family
# ---------------------------------------------------------------------------


def pairwise_cohen_kappa_family(data: dict) -> list[dict]:
    """For each model pair, over (paper, formula) where both models extracted
    the formula, compute Cohen κ on family classification.
    """
    out = []
    for i, ma in enumerate(MODEL_ORDER):
        for mb in MODEL_ORDER[i + 1:]:
            la, lb = [], []
            for paper_id in sorted(data.keys()):
                per_model = data[paper_id]
                if ma not in per_model or mb not in per_model:
                    continue
                fam_a = {}
                fam_b = {}
                for rec in per_model[ma]:
                    f = normalize_formula(rec.get("formula", ""))
                    if f:
                        fam_a[f] = (rec.get("family") or "unknown").strip().lower() or "unknown"
                for rec in per_model[mb]:
                    f = normalize_formula(rec.get("formula", ""))
                    if f:
                        fam_b[f] = (rec.get("family") or "unknown").strip().lower() or "unknown"
                shared = set(fam_a.keys()) & set(fam_b.keys())
                for f in shared:
                    la.append(fam_a[f])
                    lb.append(fam_b[f])
            if not la:
                out.append({"pair": f"{ma} vs {mb}", "n": 0, "kappa": float("nan"), "agree_pct": float("nan")})
                continue
            agree = sum(1 for x, y in zip(la, lb) if x == y)
            kappa = cohen_kappa_score(la, lb)
            out.append(
                {
                    "pair": f"{ma} vs {mb}",
                    "n": len(la),
                    "kappa": float(kappa),
                    "agree_pct": 100.0 * agree / len(la),
                }
            )
    return out


# ---------------------------------------------------------------------------
# 5. Tc value Krippendorff α (interval-level) for shared formulas
# ---------------------------------------------------------------------------


def tc_agreement_interval(data: dict) -> dict:
    """For (paper, formula) where ≥2 models extracted the formula, compute
    Krippendorff α at interval level on tc_kelvin.
    """
    pf_tc: list[dict[str, float]] = []
    for paper_id in sorted(data.keys()):
        per_model = data[paper_id]
        if any(m not in per_model for m in MODEL_ORDER):
            continue
        tc_by_model: dict[str, dict[str, float]] = {}
        for m in MODEL_ORDER:
            tc_by_model[m] = {}
            for rec in per_model[m]:
                f = normalize_formula(rec.get("formula", ""))
                if not f:
                    continue
                tc = rec.get("tc_kelvin")
                if isinstance(tc, (int, float)) and 0 < tc <= 300:
                    tc_by_model[m][f] = float(tc)

        all_formulas = set()
        for tm in tc_by_model.values():
            all_formulas.update(tm.keys())

        for f in all_formulas:
            n_models_with_f = sum(1 for m in MODEL_ORDER if f in tc_by_model[m])
            if n_models_with_f < 2:
                continue
            entry = {}
            for m in MODEL_ORDER:
                entry[m] = tc_by_model[m].get(f, float("nan"))
            pf_tc.append(entry)

    if not pf_tc:
        return {"alpha": float("nan"), "n": 0}

    matrix = np.array(
        [[entry[m] for entry in pf_tc] for m in MODEL_ORDER],
        dtype=float,
    )
    alpha = float(
        krippendorff.alpha(reliability_data=matrix, level_of_measurement="interval")
    )
    return {"alpha": alpha, "n_pairs": len(pf_tc)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    conn = sqlite3.connect(DB)
    data = load_run0_extractions(conn)
    print(f"Loaded {len(data)} papers from audit DB")

    # 1) Formula-set Krippendorff α
    alpha_fs = alpha_formula_set(data)

    # 2) Family Krippendorff α + Fleiss κ
    fam = family_agreement(data)

    # 3) Evidence Krippendorff α
    evi = evidence_agreement(data)

    # 4) Pairwise Cohen κ on family
    cohen = pairwise_cohen_kappa_family(data)

    # 5) Tc value Krippendorff α (interval)
    tc_iv = tc_agreement_interval(data)

    # ----- print + write CSV -----
    print("\n=== IRR summary (4 models, run_idx=0) ===\n")
    print(f"Krippendorff α (formula-set membership, nominal): {alpha_fs:.3f}")
    print(
        f"Krippendorff α (family classification, nominal,"
        f" n={fam.get('n_pairs', 0)} (paper, formula) pairs with ≥2 models): {fam['alpha']:.3f}"
    )
    print(
        f"Fleiss κ (family classification, 4-rater consensus subset,"
        f" n={fam.get('n_fully_labeled', 0)}): {fam['fleiss_kappa']:.3f}"
    )
    print(
        f"Krippendorff α (evidence_type, nominal,"
        f" n={evi.get('n_pairs', 0)}): {evi['alpha']:.3f}"
    )
    print(
        f"Krippendorff α (tc_kelvin, interval,"
        f" n={tc_iv.get('n_pairs', 0)}): {tc_iv['alpha']:.3f}"
    )
    print(f"\nCategories observed for evidence_type: {evi.get('categories', [])}\n")
    print("Pairwise Cohen κ on family classification (over shared-formula subset):")
    for r in cohen:
        print(f"  {r['pair']:>22}  n={r['n']:>4}  agree={r['agree_pct']:.1f}%  κ={r['kappa']:.3f}")

    # Write CSV outputs
    OUT_DIR.mkdir(exist_ok=True)
    with (OUT_DIR / "irr_summary.csv").open("w") as f:
        f.write("metric,scope,n,value\n")
        f.write(f"krippendorff_alpha_formula_set,binary;4 raters;all papers,N/A,{alpha_fs:.4f}\n")
        f.write(f"krippendorff_alpha_family,categorical;4 raters;{fam['n_pairs']} formula-overlaps,{fam['n_pairs']},{fam['alpha']:.4f}\n")
        f.write(f"fleiss_kappa_family,categorical;4-rater consensus;{fam['n_fully_labeled']} fully-labeled,{fam['n_fully_labeled']},{fam['fleiss_kappa']:.4f}\n")
        f.write(f"krippendorff_alpha_evidence,categorical;4 raters;{evi['n_pairs']} formula-overlaps,{evi['n_pairs']},{evi['alpha']:.4f}\n")
        f.write(f"krippendorff_alpha_tc_interval,interval;4 raters;{tc_iv['n_pairs']} formula-overlaps,{tc_iv['n_pairs']},{tc_iv['alpha']:.4f}\n")

    with (OUT_DIR / "irr_cohen_pairwise.csv").open("w") as f:
        f.write("pair,n,agree_pct,cohen_kappa\n")
        for r in cohen:
            f.write(f"{r['pair']},{r['n']},{r['agree_pct']:.2f},{r['kappa']:.4f}\n")

    print(f"\nSaved IRR summary CSV to {OUT_DIR}/irr_summary.csv and irr_cohen_pairwise.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
