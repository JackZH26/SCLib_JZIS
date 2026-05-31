#!/usr/bin/env python3
"""Find overlap between SuperMat hand-annotated corpus and our golden set.

For overlapping papers, compute precision / recall / F1 of each LLM's
extractions against SuperMat as ground truth.

SuperMat repo: https://github.com/lfoppiano/SuperMat (cloned to /tmp/SuperMat)
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

SUPERMAT_DIR = Path("/tmp/SuperMat")
GOLDEN_DB = Path(__file__).resolve().parent.parent / "audit" / "audit_review.db"
OUT_DIR = Path(__file__).resolve().parent.parent / "audit" / "refresh_2026_05_26"
OUT_DIR.mkdir(exist_ok=True)


def normalize_arxiv_id(s: str) -> str:
    """Normalize an arXiv ID string from various formats."""
    if not s:
        return ""
    # Common formats: "arXiv:cond-mat/9903117v1[..]", "1609.04957", "arxiv:cond-mat/0xxxxxx"
    s = s.lower().strip()
    s = re.sub(r"\[.*\]", "", s)
    s = re.sub(r"v\d+$", "", s)
    s = s.replace("arxiv:", "")
    return s.strip()


def normalize_formula(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    s = "".join(s.split())
    return s.lower()


def collect_supermat_papers() -> dict[str, dict]:
    """Walk SuperMat biblio JSONs, find papers with arxiv IDs, group records."""
    papers: dict[str, dict] = {}  # filename -> {arxiv_id, materials: [...]}
    for json_path in (SUPERMAT_DIR / "data" / "biblio").rglob("*.tei.json"):
        try:
            with json_path.open() as f:
                meta = json.load(f)
        except Exception:
            continue
        arxiv = meta.get("arXiv") or meta.get("arxiv")
        if not arxiv:
            continue
        npl_id = meta.get("npl_publn_id", "")
        if not npl_id:
            continue
        papers[npl_id] = {
            "arxiv_id_raw": arxiv,
            "arxiv_norm": normalize_arxiv_id(arxiv),
            "doi": meta.get("DOI", ""),
            "title": meta.get("title_a", "")[:80],
            "materials": [],
        }

    # Also handle the simpler arxiv-based files (e.g., "1609.04957-CC.json")
    for json_path in (SUPERMAT_DIR / "data" / "biblio").rglob("*.json"):
        if json_path.name.endswith(".tei.json"):
            continue
        try:
            with json_path.open() as f:
                meta = json.load(f)
        except Exception:
            continue
        # arxiv IDs in file name like "1609.04957-CC.json"
        m = re.match(r"^(\d{4}\.\d{4,5})", json_path.stem)
        if m:
            arxiv_id = m.group(1)
            npl_id = meta.get("npl_publn_id", "") or json_path.stem
            papers[npl_id] = {
                "arxiv_id_raw": arxiv_id,
                "arxiv_norm": arxiv_id,
                "doi": meta.get("DOI", ""),
                "title": meta.get("title_a", json_path.stem)[:80],
                "materials": [],
            }

    return papers


def collect_supermat_materials(papers: dict[str, dict]) -> None:
    """Parse the SuperMat CSV and attach materials to the corresponding papers."""
    csv_path = SUPERMAT_DIR / "data" / "csv" / "SuperMat-2.0.csv"
    with csv_path.open() as f:
        # skip header
        next(f)
        for line in f:
            parts = line.rstrip("\n").split(",")
            if len(parts) < 6:
                continue
            _id, material, tcValue, pressure, me_method, filename = parts[:6]
            filename = filename.strip()
            # SuperMat filename: "PR06014617-CC.superconductors.tei.xml" or "1609.04957-CC.superconductors.tei.xml"
            base = filename.replace(".superconductors.tei.xml", "")
            npl_candidates = [
                f"{base}.tei.xml",
                f"{base}.tei.json",
            ]
            target_npl = None
            for cand in npl_candidates:
                if cand in papers:
                    target_npl = cand
                    break
            if target_npl is None:
                continue
            # parse tcValue (possibly "30", "30 K", "60K")
            tc_str = tcValue.strip().replace("K", "").strip()
            try:
                tc = float(tc_str) if tc_str else None
            except ValueError:
                tc = None
            papers[target_npl]["materials"].append(
                {
                    "material_raw": material.strip(),
                    "material_norm": normalize_formula(material),
                    "tc_kelvin": tc,
                    "pressure_raw": pressure.strip(),
                }
            )


def get_golden_paper_ids() -> set[str]:
    conn = sqlite3.connect(GOLDEN_DB)
    return {row[0] for row in conn.execute("SELECT paper_id FROM audit_sample")}


def get_golden_extractions(paper_id: str) -> dict[str, list[dict]]:
    """For a paper, return all 4-model run_idx=0 extractions."""
    conn = sqlite3.connect(GOLDEN_DB)
    rows = conn.execute(
        """
        SELECT vendor, model_name, materials_json
        FROM audit_extraction_model
        WHERE paper_id=? AND run_idx=0
        """,
        (paper_id,),
    ).fetchall()
    out: dict[str, list[dict]] = defaultdict(list)
    label_map = {
        ("anthropic", "claude-opus-4-7"): "Opus",
        ("openai", "gpt-5.5"): "GPT-5.5",
        ("openai", "gpt-5.4-mini"): "GPT-mini",
        ("google", "gemini-2.5-flash"): "Gemini",
    }
    for vendor, model, mj in rows:
        label = label_map.get((vendor, model))
        if not label or not mj:
            continue
        try:
            parsed = json.loads(mj)
        except Exception:
            parsed = []
        out[label] = parsed if isinstance(parsed, list) else []
    return dict(out)


def normalize_golden_arxiv(paper_id: str) -> str:
    """Our golden paper_id format: 'arxiv:cond-mat/0xxxxx' or 'arxiv:1xxx.xxxx'."""
    s = paper_id.lower().strip()
    s = s.replace("arxiv:", "")
    s = re.sub(r"v\d+$", "", s)
    return s


def main() -> int:
    print("Loading SuperMat metadata...")
    sm_papers = collect_supermat_papers()
    print(f"  found {len(sm_papers)} SuperMat papers with arxiv IDs")
    collect_supermat_materials(sm_papers)
    sm_with_mats = {k: v for k, v in sm_papers.items() if v["materials"]}
    print(f"  of these, {len(sm_with_mats)} have at least one material annotation")

    # Build arxiv -> paper map
    sm_by_arxiv = {v["arxiv_norm"]: v for v in sm_with_mats.values() if v["arxiv_norm"]}
    print(f"  unique arxiv IDs in SuperMat: {len(sm_by_arxiv)}")

    print("\nLoading our golden set arxiv IDs...")
    golden_pids = get_golden_paper_ids()
    print(f"  golden set has {len(golden_pids)} papers")
    golden_arxiv = {normalize_golden_arxiv(p): p for p in golden_pids}

    overlap = set(sm_by_arxiv.keys()) & set(golden_arxiv.keys())
    print(f"\n>>> SuperMat ∩ golden-set overlap: {len(overlap)} papers <<<\n")

    if not overlap:
        print("(no overlap; cannot do ground-truth precision/recall against SuperMat)")
        with (OUT_DIR / "supermat_overlap.csv").open("w") as f:
            f.write("metric,value\n")
            f.write(f"supermat_papers_with_arxiv,{len(sm_by_arxiv)}\n")
            f.write(f"golden_set,{len(golden_pids)}\n")
            f.write(f"overlap,0\n")
        return 0

    # Compute per-model precision/recall/F1 against SuperMat
    model_stats: dict[str, dict] = {
        m: {"tp": 0, "fp": 0, "fn": 0, "tc_close": 0, "tc_compared": 0}
        for m in ["Opus", "GPT-5.5", "GPT-mini", "Gemini"]
    }

    for arxiv in sorted(overlap):
        golden_pid = golden_arxiv[arxiv]
        sm_entry = sm_by_arxiv[arxiv]
        sm_formulas = {m["material_norm"] for m in sm_entry["materials"] if m["material_norm"]}
        sm_tc_by_formula = {
            m["material_norm"]: m["tc_kelvin"]
            for m in sm_entry["materials"]
            if m["material_norm"] and m["tc_kelvin"] is not None
        }
        if not sm_formulas:
            continue

        for label, recs in get_golden_extractions(golden_pid).items():
            llm_formulas = {normalize_formula(r.get("formula", "")) for r in recs}
            llm_formulas.discard("")
            tp = sm_formulas & llm_formulas
            fp = llm_formulas - sm_formulas
            fn = sm_formulas - llm_formulas
            model_stats[label]["tp"] += len(tp)
            model_stats[label]["fp"] += len(fp)
            model_stats[label]["fn"] += len(fn)

            # Tc closeness on tp set
            llm_tc_by_formula = {
                normalize_formula(r.get("formula", "")): r.get("tc_kelvin")
                for r in recs
                if r.get("tc_kelvin") is not None
            }
            for f in tp:
                if f in sm_tc_by_formula and f in llm_tc_by_formula:
                    sm_tc = sm_tc_by_formula[f]
                    llm_tc = llm_tc_by_formula[f]
                    try:
                        if abs(float(llm_tc) - float(sm_tc)) <= 2.0:
                            model_stats[label]["tc_close"] += 1
                    except (TypeError, ValueError):
                        continue
                    model_stats[label]["tc_compared"] += 1

    # Compute and print
    print(f"{'Model':<10} {'TP':>5} {'FP':>5} {'FN':>5} {'Prec':>7} {'Recall':>7} {'F1':>6} {'Tc<2K':>10}")
    rows = []
    for m, s in model_stats.items():
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        tc_rate = s["tc_close"] / s["tc_compared"] if s["tc_compared"] > 0 else 0.0
        print(f"{m:<10} {tp:>5} {fp:>5} {fn:>5} {prec:>7.3f} {rec:>7.3f} {f1:>6.3f} {s['tc_close']}/{s['tc_compared']} ({tc_rate*100:.0f}%)")
        rows.append((m, tp, fp, fn, prec, rec, f1, s["tc_close"], s["tc_compared"]))

    with (OUT_DIR / "supermat_precision_recall.csv").open("w") as f:
        f.write("model,tp,fp,fn,precision,recall,f1,tc_close_2K,tc_compared\n")
        for m, tp, fp, fn, p, r, f1, tcc, tcm in rows:
            f.write(f"{m},{tp},{fp},{fn},{p:.4f},{r:.4f},{f1:.4f},{tcc},{tcm}\n")

    # Also list the overlap papers for documentation
    with (OUT_DIR / "supermat_overlap_papers.csv").open("w") as f:
        f.write("arxiv_id,sm_filename,sm_title,n_sm_materials\n")
        for a in sorted(overlap):
            sm = sm_by_arxiv[a]
            title_clean = sm["title"].replace(",", ";").replace("\n", " ")[:60]
            f.write(f"{a},{sm.get('npl_publn_id','')},{title_clean},{len(sm['materials'])}\n")

    print(f"\nWrote {OUT_DIR/'supermat_precision_recall.csv'} and supermat_overlap_papers.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
